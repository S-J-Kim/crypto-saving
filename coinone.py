"""
This module provides functions to interact with the Coinone cryptocurrency exchange API,
including checking balances, placing buy orders, and sending notifications to Discord.

Functions:
    get_encoded_payload(payload):
        Encodes the given payload with a nonce and returns the base64 encoded JSON string.

    get_signature(encoded_payload):
        Generates an HMAC SHA-512 signature for the given encoded payload using the secret key.

    get_response(action, payload, method="POST"):
        Sends an HTTP request to the Coinone API with the given action, payload, and method,
        and returns the JSON response.

    get_balance(*currencies):
        Retrieves the balance for the specified currencies from the Coinone account.

    buy(price, target=BTC):
        Places a market buy order for the specified target currency at the given price.

    get_current_price(target=BTC):
        Retrieves the current price of the specified target currency in the quote currency.

    send_discord_message(message):
        Sends a message to the configured Discord webhook URL.

    place_buy_order():
        Checks the KRW balance, retrieves the current BTC price, and places a buy order if the
        balance is sufficient. Sends a notification to Discord with the result.
"""

import base64
import hashlib
import hmac
import json
import uuid
import os
from functools import reduce
import time
import datetime
import pprint
import httplib2
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv("API_ACCESS_KEY_COINONE")
SECRET_KEY = bytes(os.getenv("API_SECRET_KEY_COINONE"), "utf-8")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

AMOUNT = os.getenv("AMOUNT")
CURRENCY_BUY = os.getenv("CURRENCY_BUY", "BTC")
CURRENCY_HOLD = os.getenv("CURRENCY_HOLD", "KRW")

IS_ACTIVE = os.getenv("IS_ACTIVE", "FALSE")
IS_ACTIVE = IS_ACTIVE.strip().lower() in ["true", "1", "yes"]


def get_encoded_payload(payload):
    payload["nonce"] = str(uuid.uuid4())

    dumped_json = json.dumps(payload)
    encoded_json = base64.b64encode(bytes(dumped_json, "utf-8"))
    return encoded_json


def get_signature(encoded_payload):
    signature = hmac.new(SECRET_KEY, encoded_payload, hashlib.sha512)
    return signature.hexdigest()


def get_response(action, payload, method="POST"):
    url = "{}{}".format("https://api.coinone.co.kr", action)

    encoded_payload = get_encoded_payload(payload)

    headers = {
        "Content-type": "application/json",
        "X-COINONE-PAYLOAD": encoded_payload,
        "X-COINONE-SIGNATURE": get_signature(encoded_payload),
    }

    http = httplib2.Http()

    try:
        _, content = http.request(url, method, headers=headers)
        return json.loads(content)
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        raise


def get_balance(*currencies):
    arg_balance = {
        "action": "/v2.1/account/balance",
        "payload": {"access_token": ACCESS_TOKEN, "currencies": currencies},
    }

    return get_response(**arg_balance)


def get_balance_info(*currencies):
    balance = get_balance(*currencies)
    balances = balance["balances"]

    def format_balance(acc, curr):
        return (
            acc
            + f"\n**[{curr['currency']}]**\n"
            + f"현재 보유량: {float(curr['available']):,} {curr['currency']}\n"
            + f"매수 평균가: {float(curr['average_price']):,} {CURRENCY_HOLD}\n"
            + f"총 보유 가치: {int(float(curr['available']) * float(get_current_price(curr['currency']))):,} {CURRENCY_HOLD}\n"
        )

    report = reduce(format_balance, balances, "")

    report = "=== 자산 별 보유 현황 ===\n" + report
    return report


def buy(amount, limit_price, target=CURRENCY_BUY):

    order_id = str(uuid.uuid4())

    arg_buy = {
        "action": "/v2.1/order",
        "payload": {
            "access_token": ACCESS_TOKEN,
            "quote_currency": CURRENCY_HOLD,
            "target_currency": target,
            "type": "MARKET",
            "side": "BUY",
            "amount": amount,
            "limit_price": limit_price,
            "user_order_id": order_id,
        },
    }

    return get_response(**arg_buy)


def get_order_info(order_id, target=CURRENCY_BUY):
    arg_order_info = {
        "action": "/v2.1/order/detail",
        "payload": {
            "access_token": ACCESS_TOKEN,
            "order_id": order_id,
            "quote_currency": CURRENCY_HOLD,
            "target_currency": target,
        },
    }

    return get_response(**arg_order_info)


def get_current_price(target=CURRENCY_BUY):
    arg_ticker = {
        "action": f"/public/v2/ticker_new/{CURRENCY_HOLD}/{target}",
        "payload": {},
    }

    price = get_response(**arg_ticker, method="GET")

    return price["tickers"][0]["best_asks"][0]["price"]


def send_discord_message(message):
    payload = {"content": str(message)}
    headers = {"Content-Type": "application/json"}
    http = httplib2.Http()
    try:
        response, content = http.request(
            DISCORD_WEBHOOK_URL, "POST", headers=headers, body=json.dumps(payload)
        )
        if response.status != 204:
            print(f"Failed to send message to Discord: {content}")
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        raise


def get_order_result_report(order, currency=CURRENCY_BUY):
    return (
        f"**[주문 ID]**\n {order['order_id']}\n\n"
        + f"**[주문 시각]**\n{datetime.datetime.fromtimestamp(order['ordered_at']/1000)}\n\n"
        + f"**[주문 가격]**\n{int(order['average_executed_price']):,} {CURRENCY_HOLD}\n\n"
        + f"**[체결 수량]**\n{order['executed_qty']} {currency}\n\n"
        + f"**[체결 금액]**\n{float(order['traded_amount']):,} {CURRENCY_HOLD}\n\n"
        + f"**[주문 상태]**\n{order['status']}\n\n"
        + f"**[수수료]**\n{float(order['fee']):,} {CURRENCY_HOLD}\n\n"
    )


def place_buy_order(amount=AMOUNT, currency=CURRENCY_BUY):

    # balance = get_balance(CURRENCY_HOLD, currency)
    # hold_balance = float(balance[CURRENCY_HOLD.lower()]["balance"])
    current_price = float(get_current_price(currency))

    # if hold_balance < 5000:
    #     send_discord_message(f"{CURRENCY_HOLD} balance is less than 5000")
    #     return

    buy_response = buy(amount=amount, limit_price=current_price * 1.03, target=currency)

    time.sleep(1)
    if buy_response["result"] == "success":
        order_info = get_order_info(buy_response["order_id"], target=currency)

        pprint.pprint(order_info)

        send_discord_message(
            "**===== 주문이 접수되었습니다 =====**\n\n"
            + get_order_result_report(order_info["order"], currency)
            + "\n"
            + get_balance_info(CURRENCY_HOLD, currency)
        )

    else:
        fail_msg = f"❌ 자동 매수 주문이 실패했습니다.\n사유: {buy_response}"
        send_discord_message(fail_msg)


if __name__ == "__main__":
    if IS_ACTIVE:
        place_buy_order(currency=CURRENCY_BUY)
    else:
        user_msg = (
            "⏸️ 자동 매수 기능이 현재 비활성화되어 있습니다.\n"
            "환경변수 IS_ACTIVE가 활성화(예: TRUE, 1, yes)로 설정되어 있지 않아 오늘의 자동 매수가 실행되지 않았습니다."
        )
        send_discord_message(user_msg)
