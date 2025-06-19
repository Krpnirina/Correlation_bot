import asyncio
import websockets
import json
import csv
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict

# --- CONFIGURATION ---
CSV_FILE = "daily_trades.csv"
STRONG_LEVEL_THRESHOLD = 3
TICKS_WINDOW_HOURS = 24
MIN_TICKS_REQUIRED = 300
VOLUME_THRESHOLD = 1000
API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130

SYMBOLS = ["R_50"]  # Test with one symbol only first
GRANULARITIES = ["1d", "4h", "15m"]
GRANULARITY_MAP = {"15m": 900, "4h": 14400, "1d": 86400}

# --- DATA STORAGE ---
daily_data = defaultdict(lambda: {
    "ticks": deque(),
    "support_hits": defaultdict(int),
    "resistance_hits": defaultdict(int),
    "levels_printed": set(),
    "signal_counts": 0
})

candles_data = defaultdict(lambda: {
    "1d": None,
    "4h": None,
    "15m": None
})

# --- CSV INITIALIZATION ---
def initialize_csv():
    with open(CSV_FILE, mode='w', newline='') as file:
        csv.writer(file).writerow([
            "date", "symbol", "price", "level_type", "strength",
            "daily_min", "daily_max", "timestamp_utc"
        ])

# --- FORMAT & LOG OUTPUT ---
def print_level(symbol, price, level_type, strength, daily_min, daily_max, timestamp):
    color = "\033[91m" if level_type == "SUPPORT" else "\033[92m"
    reset = "\033[0m"
    time_str = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
    diff = abs(price - (daily_min if level_type == "SUPPORT" else daily_max))
    strength_display = "★" * min(strength, 3) + "!" * max(0, strength - 3)

    print(f"{color}┏{'━'*60}┓")
    print(f"┃ {'DAILY '+level_type.ljust(15)} {symbol} @ {price:.5f} (Strength: {strength_display})")
    print(f"┃ {'Range:'.ljust(15)} {daily_min:.5f} - {daily_max:.5f} (Diff: {diff:.5f})")
    print(f"┃ {'Time:'.ljust(15)} {time_str}")
    print(f"┗{'━'*60}┛{reset}")

    with open(CSV_FILE, mode='a', newline='') as file:
        csv.writer(file).writerow([
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            symbol, price, level_type, strength, daily_min, daily_max, time_str
        ])

# --- VOLUME CHECK FUNCTION ---
def volume_confirmed(symbol):
    c1d = candles_data[symbol]["1d"]
    c4h = candles_data[symbol]["4h"]
    c15m = candles_data[symbol]["15m"]
    return c1d and c4h and c15m and all(
        c["volume"] >= VOLUME_THRESHOLD for c in [c1d, c4h, c15m]
    )

# --- HANDLE CANDLES ---
async def handle_candle(candle_data):
    symbol = candle_data["symbol"]
    granularity_seconds = candle_data["granularity"]
    gran_key = next((k for k, v in GRANULARITY_MAP.items() if v == granularity_seconds), None)
    if gran_key:
        candles_data[symbol][gran_key] = {
            "close": candle_data["close"],
            "volume": candle_data["volume"],
            "epoch": candle_data["epoch"]
        }

# --- HANDLE TICK ---
async def handle_tick(tick):
    symbol = tick['symbol']
    price = float(tick['quote'])
    timestamp = tick['epoch']
    now = datetime.now(timezone.utc)

    data = daily_data[symbol]
    data["ticks"].append((price, now))

    while data["ticks"] and (now - data["ticks"][0][1]) > timedelta(hours=TICKS_WINDOW_HOURS):
        data["ticks"].popleft()

    if len(data["ticks"]) % 25 == 0:
        print(f"\033[94m[{symbol}] ➜ {len(data['ticks'])} ticks voaray hatreto\033[0m")

    if len(data["ticks"]) >= MIN_TICKS_REQUIRED:
        prices = [p for p, _ in data["ticks"]]
        daily_min, daily_max = min(prices), max(prices)
        range_val = daily_max - daily_min
        support_zone = daily_min + (range_val * 0.05)
        resistance_zone = daily_max - (range_val * 0.05)

        if price <= support_zone:
            key = f"SUPPORT_{daily_min:.5f}"
            data["support_hits"][key] += 1
            strength = data["support_hits"][key]

            if strength >= STRONG_LEVEL_THRESHOLD and key not in data["levels_printed"] and volume_confirmed(symbol):
                if data["signal_counts"] < 2:
                    data["levels_printed"].add(key)
                    data["signal_counts"] += 1
                    print_level(symbol, price, "SUPPORT", strength, daily_min, daily_max, timestamp)

        elif price >= resistance_zone:
            key = f"RESISTANCE_{daily_max:.5f}"
            data["resistance_hits"][key] += 1
            strength = data["resistance_hits"][key]

            if strength >= STRONG_LEVEL_THRESHOLD and key not in data["levels_printed"] and volume_confirmed(symbol):
                if data["signal_counts"] < 2:
                    data["levels_printed"].add(key)
                    data["signal_counts"] += 1
                    print_level(symbol, price, "RESISTANCE", strength, daily_min, daily_max, timestamp)

# --- SUBSCRIBE TO DATA ---
async def subscribe_data():
    url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
    try:
        async with websockets.connect(url) as ws:
            print("\033[95m● Connecting and authorizing...\033[0m")
            await ws.send(json.dumps({"authorize": API_TOKEN}))
            auth_resp = await ws.recv()
            auth_data = json.loads(auth_resp)
            if auth_data.get("error"):
                print(f"\033[91m● Authorization failed: {auth_data['error']}\033[0m")
                return

            print("\033[92m● Authorized successfully.\033[0m")
            print("\033[95m● Subscribing to ticks and candles...\033[0m")

            for symbol in SYMBOLS:
                await ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                await asyncio.sleep(0.05)

            for symbol in SYMBOLS:
                for gran in GRANULARITIES:
                    await ws.send(json.dumps({"candles": symbol, "granularity": GRANULARITY_MAP[gran], "subscribe": 1}))
                    await asyncio.sleep(0.05)

            print(f"\n\033[95m● TRACKING {len(SYMBOLS)} symbols with volume confirmation (D1,H4,M15)\033[0m\n")

            async for message in ws:
                print("✔️ Message voaray")
                try:
                    data = json.loads(message)
                    if 'error' in data:
                        print(f"\033[91m● API Error: {data['error']}\033[0m")
                        continue
                    if 'tick' in data:
                        await handle_tick(data['tick'])
                    elif 'candles' in data:
                        await handle_candle(data['candles'])
                except Exception as e:
                    print(f"\033[91m● JSON decode error or other exception: {e}\033[0m")

    except Exception as e:
        print(f"\033[91m● Connection or WebSocket error: {e}\033[0m")
        await asyncio.sleep(5)
        await subscribe_data()

# --- MAIN ---
async def main():
    initialize_csv()
    while True:
        try:
            await subscribe_data()
        except Exception as e:
            print(f"\033[91m● Reconnection due to error: {e} (Retrying in 10s)\033[0m")
            await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\033[94m● Tracking stopped by user.\033[0m")
    except Exception as e:
        print(f"\033[91m● Fatal error: {e}\033[0m")
