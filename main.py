import asyncio
import websockets
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130

SYMBOLS = [
    "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V",
    "R_10", "R_25", "R_50", "R_75", "R_100"
]

# Hanangona ticks mandritra ny 15 min (900 segondra)
TICKS_WINDOW_SECONDS = 900
MIN_TICKS_REQUIRED = 900

# Data storage: isaky ny symbol dia hitahiry timestamp sy price ny ticks
price_data = defaultdict(deque)

M15_highs = {}
M15_lows = {}

def get_current_time():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

async def subscribe_ticks(ws):
    for symbol in SYMBOLS:
        subscribe_msg = {
            "ticks": symbol,
            "subscribe": 1
        }
        await ws.send(json.dumps(subscribe_msg))
        print(f"[{get_current_time()}] ➜ Subscribed to ticks for {symbol}")
        await asyncio.sleep(0.05)  # kely fotsiny mba tsy enta-mavesatra ny server

async def handle_tick(msg):
    symbol = msg["symbol"]
    price = float(msg["quote"])
    timestamp = datetime.utcnow()

    # Append tick and remove old ticks beyond 15 min
    ticks = price_data[symbol]
    ticks.append((timestamp, price))

    # Remove ticks older than 15 min
    while ticks and (timestamp - ticks[0][0]).total_seconds() > TICKS_WINDOW_SECONDS:
        ticks.popleft()

    if len(ticks) >= MIN_TICKS_REQUIRED:
        prices = [p for t, p in ticks]
        M15_highs[symbol] = max(prices)
        M15_lows[symbol] = min(prices)
        print(f"[{get_current_time()}] 🟢 {symbol} M15 High: {M15_highs[symbol]:.2f}")
        print(f"[{get_current_time()}] 🔵 {symbol} M15 Low: {M15_lows[symbol]:.2f}")

async def main():
    url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
    async with websockets.connect(url) as ws:
        # Authorize
        auth_msg = {"authorize": API_TOKEN}
        await ws.send(json.dumps(auth_msg))
        auth_resp = await ws.recv()
        auth_data = json.loads(auth_resp)
        if "error" in auth_data:
            print(f"Authorization failed: {auth_data['error']['message']}")
            return
        print(f"[{get_current_time()}] ✅ Authorized successfully!")

        # Subscribe ticks for all symbols
        await subscribe_ticks(ws)

        # Listen for messages
        while True:
            try:
                message = await ws.recv()
                data = json.loads(message)

                if "tick" in data:
                    await handle_tick(data["tick"])

                elif "error" in data:
                    print(f"API error: {data['error']['message']}")

            except websockets.ConnectionClosed:
                print(f"[{get_current_time()}] Connection closed, reconnecting...")
                await asyncio.sleep(5)
                break
            except Exception as e:
                print(f"[{get_current_time()}] Error: {str(e)}")
                await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram stopped by user")
