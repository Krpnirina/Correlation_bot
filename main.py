import asyncio
import websockets
import json
import csv
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict

# --- CONFIGURATION ---
CSV_FILE = "daily_trades.csv"
STRONG_LEVEL_THRESHOLD = 2  # Reduced from 3 to 2 for earlier signals [user request]
SUPPORT_ZONE_PERCENT = 0.10  # Widened from 5% to 10% [user request]
RESISTANCE_ZONE_PERCENT = 0.10
TICKS_WINDOW_HOURS = 24
MIN_TICKS_REQUIRED = 300
VOLUME_THRESHOLD = 500  # Reduced from 1000 [user request]
MAX_SIGNALS_PER_DAY = 4  # Increased from 2 [user request]
API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130

# Symbol configuration [user request]
VOLATILITY_INDICES = ["1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"]
RANGE_BREAK_INDICES = ["R_10", "R_25", "R_50", "R_75", "R_100"]
SYMBOLS = VOLATILITY_INDICES + RANGE_BREAK_INDICES

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
        writer = csv.writer(file)
        writer.writerow([
            "timestamp_utc", "symbol", "price", "level_type", "strength",
            "daily_min", "daily_max", "symbol_type", "volume_status"
        ])

# --- VOLUME CHECK (FLEXIBLE) ---
def volume_confirmed(symbol):
    c1d = candles_data[symbol]["1d"]
    c4h = candles_data[symbol]["4h"]
    c15m = candles_data[symbol]["15m"]
    # Only one timeframe needed [optimization]
    return any([
        c1d and c1d["volume"] >= VOLUME_THRESHOLD,
        c4h and c4h["volume"] >= VOLUME_THRESHOLD,
        c15m and c15m["volume"] >= VOLUME_THRESHOLD
    ])

# --- OUTPUT FORMATTING ---
def print_level(symbol, price, level_type, strength, daily_min, daily_max, timestamp):
    # Symbol type identification
    symbol_type = "VOLATILITY" if symbol in VOLATILITY_INDICES else "RANGE_BREAK"
    color = "\033[91m" if level_type == "SUPPORT" else "\033[92m"
    reset = "\033[0m"
    
    time_str = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
    strength_display = "★" * min(strength, 3) + "!" * max(0, strength - 3)
    vol_status = "✅" if volume_confirmed(symbol) else "❌"

    print(f"{color}┏{'━'*70}┓")
    print(f"┃ {symbol_type} {level_type.ljust(12)} {symbol} @ {price:.5f} (Strength: {strength_display})")
    print(f"┃ {'Range:'.ljust(10)} {daily_min:.5f} - {daily_max:.5f} | Vol: {vol_status}")
    print(f"┃ {'Time:'.ljust(10)} {time_str}")
    print(f"┗{'━'*70}┛{reset}")

    # CSV logging with symbol type
    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            symbol, price, level_type, strength,
            daily_min, daily_max, symbol_type, vol_status
        ])

# --- CANDLE PROCESSING ---
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

# --- TICK PROCESSING ---
async def handle_tick(tick):
    symbol = tick['symbol']
    price = float(tick['quote'])
    timestamp = tick['epoch']
    now = datetime.now(timezone.utc)

    data = daily_data[symbol]
    data["ticks"].append((price, now))

    # Maintain 24-hour window
    while data["ticks"] and (now - data["ticks"][0][1]) > timedelta(hours=TICKS_WINDOW_HOURS):
        data["ticks"].popleft()

    # Periodic status update
    if len(data["ticks"]) % 25 == 0:
        print(f"\033[94m[{symbol}] ➜ Collected {len(data['ticks'])} ticks | Max Signals: {MAX_SIGNALS_PER_DAY - data['signal_counts']} left today\033[0m")

    if len(data["ticks"]) >= MIN_TICKS_REQUIRED:
        prices = [p for p, _ in data["ticks"]]
        daily_min, daily_max = min(prices), max(prices)
        range_val = daily_max - daily_min
        
        # Dynamic zones [optimization]
        support_zone = daily_min + (range_val * SUPPORT_ZONE_PERCENT)
        resistance_zone = daily_max - (range_val * RESISTANCE_ZONE_PERCENT)

        if price <= support_zone:
            key = f"SUPPORT_{daily_min:.5f}"
            data["support_hits"][key] += 1
            strength = data["support_hits"][key]

            if (strength >= STRONG_LEVEL_THRESHOLD and 
                key not in data["levels_printed"] and 
                data["signal_counts"] < MAX_SIGNALS_PER_DAY):
                
                data["levels_printed"].add(key)
                data["signal_counts"] += 1
                print_level(symbol, price, "SUPPORT", strength, daily_min, daily_max, timestamp)

        elif price >= resistance_zone:
            key = f"RESISTANCE_{daily_max:.5f}"
            data["resistance_hits"][key] += 1
            strength = data["resistance_hits"][key]

            if (strength >= STRONG_LEVEL_THRESHOLD and 
                key not in data["levels_printed"] and 
                data["signal_counts"] < MAX_SIGNALS_PER_DAY):
                
                data["levels_printed"].add(key)
                data["signal_counts"] += 1
                print_level(symbol, price, "RESISTANCE", strength, daily_min, daily_max, timestamp)

# --- WEBSOCKET MANAGEMENT ---
async def subscribe_data():
    url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
    try:
        async with websockets.connect(url) as ws:
            # Authorization
            await ws.send(json.dumps({"authorize": API_TOKEN}))
            auth_resp = json.loads(await ws.recv())
            if auth_resp.get("error"):
                print(f"\033[91m● Authorization failed: {auth_resp['error']['message']}\033[0m")
                return

            # Symbol subscriptions
            for symbol in SYMBOLS:
                await ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
                await asyncio.sleep(0.1)  # Rate limiting
                for gran in GRANULARITIES:
                    await ws.send(json.dumps({
                        "candles": symbol,
                        "granularity": GRANULARITY_MAP[gran],
                        "subscribe": 1
                    }))
                    await asyncio.sleep(0.1)

            print(f"\n\033[95m● TRACKING {len(SYMBOLS)} SYMBOLS (Volatility:5 | RangeBreak:5)\033[0m\n")

            # Data processing loop
            async for message in ws:
                try:
                    data = json.loads(message)
                    if 'tick' in data:
                        await handle_tick(data['tick'])
                    elif 'candles' in data:
                        await handle_candle(data['candles'])
                    elif 'error' in data:
                        print(f"\033[93m● API Warning: {data['error']['message']}\033[0m")
                except Exception as e:
                    print(f"\033[91m● Processing Error: {str(e)[:80]}...\033[0m")

    except Exception as e:
        print(f"\033[91m● WebSocket Error: {str(e)[:100]} (Reconnecting in 10s)\033[0m")
        await asyncio.sleep(10)
        await subscribe_data()

# --- MAIN EXECUTION ---
async def main():
    initialize_csv()
    print("\033[96m" + "━"*70)
    print(f"● SYSTEM INITIALIZED | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"● SYMBOLS: {', '.join(SYMBOLS)}")
    print(f"● CONFIG: Strength={STRONG_LEVEL_THRESHOLD} hits | Signals/day={MAX_SIGNALS_PER_DAY}")
    print("━"*70 + "\033[0m")
    
    while True:
        try:
            await subscribe_data()
        except Exception as e:
            print(f"\033[91m● Critical Error: {e} (Restarting in 30s)\033[0m")
            await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\033[94m\n● Tracking stopped by user ●\033[0m")
