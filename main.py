import asyncio
import websockets
import json
from datetime import datetime, timedelta
from collections import deque

API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130
SYMBOLS = [
    "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V",
    "R_10", "R_25", "R_50", "R_75", "R_100"
]

# Mitahiry ny vidiny isaky ny symbol
price_data = {symbol: deque(maxlen=900) for symbol in SYMBOLS}  # maxlen = 900 amin'ny 1s = 15 minitra
M15_highs = {}
M15_lows = {}

def get_current_time():
    return datetime.utcnow().strftime("%H:%M:%S")

async def subscribe(ws, symbol):
    await ws.send(json.dumps({
        "ticks_subscribe": symbol
    }))

async def authorize(ws):
    await ws.send(json.dumps({
        "authorize": API_TOKEN
    }))

async def handle_message(message):
    msg = json.loads(message)

    if msg.get("msg_type") == "tick":
        symbol = msg["tick"]["symbol"]
        price = float(msg["tick"]["quote"])
        timestamp = datetime.utcnow()

        # Mitahiry vidiny
        price_data[symbol].append((timestamp, price))

        # Raha efa manan-data 15 min (900s), dia manisa high/low
        if len(price_data[symbol]) >= 900:
            prices = [p for t, p in price_data[symbol]]
            M15_highs[symbol] = max(prices)
            M15_lows[symbol] = min(prices)
            print(f"[{get_current_time()}] ✅ {symbol} | 🔼 M15 High: {M15_highs[symbol]} | 🔽 M15 Low: {M15_lows[symbol]}")

    elif msg.get("msg_type") == "authorize":
        print("✅ Authorized successfully!")

async def main():
    url = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    async with websockets.connect(url) as ws:
        await authorize(ws)

        for symbol in SYMBOLS:
            await subscribe(ws, symbol)

        while True:
            message = await ws.recv()
            await handle_message(message)

if __name__ == "__main__":
    asyncio.run(main())
