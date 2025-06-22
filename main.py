import asyncio
import websockets
import json
from datetime import datetime

API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130
SYMBOL = "R_100"

async def get_m15_high_low():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=" + str(APP_ID)

    async with websockets.connect(uri) as websocket:
        # ✅ Authorize
        await websocket.send(json.dumps({
            "authorize": API_TOKEN
        }))
        auth_response = await websocket.recv()
        auth_data = json.loads(auth_response)
        if "error" in auth_data:
            print("⛔ Authorization failed:", auth_data["error"]["message"])
            return
        print("✅ Authorized successfully!\n")

        # ✅ Request M15 candles (15 min = 900s) - last 2 candles just in case
        await websocket.send(json.dumps({
            "ticks_history": SYMBOL,
            "style": "candles",
            "granularity": 900,
            "count": 2,
            "end": "latest"
        }))

        candles_response = await websocket.recv()
        candles_data = json.loads(candles_response)

        # ✅ Check for errors
        if "error" in candles_data:
            print("⛔ Error fetching candles:", candles_data["error"]["message"])
            return

        candles = candles_data["history"]["candles"]

        # ✅ Calculate M15 high and low
        m15_high = max(candle["high"] for candle in candles)
        m15_low = min(candle["low"] for candle in candles)

        print(f"🟢 M15 High: {m15_high}")
        print(f"🔵 M15 Low: {m15_low}")

# 🔁 Run the function
asyncio.run(get_m15_high_low())
