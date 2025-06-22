import asyncio
import websockets
import json
from datetime import datetime, timedelta

API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130
SYMBOL = "R_100"

M15_DURATION = 15 * 60  # 15 minutes in seconds
M15_CANDLE_COUNT = 1    # 1 candle = 15min if granularity is 900

async def get_m15_high_low(ws):
    request = {
        "ticks_history": SYMBOL,
        "style": "candles",
        "granularity": 900,  # 900s = 15min
        "count": M15_CANDLE_COUNT,
        "end": "latest"
    }
    await ws.send(json.dumps(request))
    response = await ws.recv()
    data = json.loads(response)

    try:
        candles = data['candles']
        highs = [candle['high'] for candle in candles]
        lows = [candle['low'] for candle in candles]
        return max(highs), min(lows)
    except KeyError:
        print("❌ Tsy nahazo candlestick data.")
        return None, None

async def authorize(ws):
    await ws.send(json.dumps({"authorize": API_TOKEN}))
    response = await ws.recv()
    data = json.loads(response)
    if data.get("msg_type") == "authorize":
        print("✅ Authorized successfully!")
    else:
        print("❌ Authorization failed.")

async def main():
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    async with websockets.connect(uri) as ws:
        await authorize(ws)
        m15_high, m15_low = await get_m15_high_low(ws)
        if m15_high is not None:
            print(f"🟢 M15 High: {m15_high}")
            print(f"🔵 M15 Low: {m15_low}")
        else:
            print("⚠️ Tsy nahazo M15 High/Low.")

if __name__ == "__main__":
    asyncio.run(main())
