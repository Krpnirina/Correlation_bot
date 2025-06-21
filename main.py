import asyncio
import websockets
import json
import csv
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict

# --- CONFIGURATION ---
CSV_FILE = "daily_trades.csv"
STRONG_LEVEL_THRESHOLD = 2
SUPPORT_ZONE_PERCENT = 0.10
RESISTANCE_ZONE_PERCENT = 0.10
TICKS_WINDOW_HOURS = 24
MIN_TICKS_REQUIRED = 300
VOLUME_THRESHOLD = 500
MAX_SIGNALS_PER_DAY = 4
API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130

# All symbols are volatility indices
SYMBOLS = [
    "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V",
    "R_10", "R_25", "R_50", "R_75", "R_100"
]

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
            "daily_min", "daily_max", "volume_status"
        ])

# --- VOLUME CHECK (FLEXIBLE) ---
def volume_confirmed(symbol):
    c1d = candles_data[symbol]["1d"]
    c4h = candles_data[symbol]["4h"]
    c15m = candles_data[symbol]["15m"]
    return any([
        c1d and c1d["volume"] >= VOLUME_THRESHOLD,
        c4h and c4h["volume"] >= VOLUME_THRESHOLD,
        c15m and c15m["volume"] >= VOLUME_THRESHOLD
    ])

# --- OUTPUT FORMATTING ---
def print_level(symbol, price, level_type, strength, daily_min, daily_max, timestamp):
    color = "\033[91m" if level_type == "SUPPORT" else "\033[92m"
    reset = "\033[0m"
    
    time_str = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
    strength_display = "★" * min(strength, 3) + "!" * max(0, strength - 3)
    vol_status = "✅" if volume_confirmed(symbol) else "❌"

    print(f"{color}┏{'━'*70}┓")
    print(f"┃ VOLATILITY {level_type.ljust(10)} {symbol} @ {price:.5f} (Strength: {strength_display})")
    print(f"┃ {'Range:'.ljust(10)} {daily_min:.5f} - {daily_max:.5f} | Vol: {vol_status}")
    print(f"┃ {'Time:'.ljust(10)} {time_str}")
    print(f"┗{'━'*70}┛{reset}")

    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            symbol, price, level_type, strength,
            daily_min, daily_max, vol_status
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

    while data["ticks"] and (now - data["ticks"][0][1]) > timedelta(hours=TICKS_WINDOW_HOURS):
        data["ticks"].popleft()

    if len(data["ticks"]) % 25 == 0:
        print(f"\033[94m[{symbol}] ➜ Collected {len(data['ticks'])} ticks | Signals left: {MAX_SIGNALS_PER_DAY - data['signal_counts']}\033[0m")

    if len(data["ticks"]) >= MIN_TICKS_REQUIRED:
        prices = [p for p, _ in data["ticks"]]
        daily_min, daily_max = min(prices), max(prices)
        range_val = daily_max - daily_min
        
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
            auth_msg = {"authorize": API_TOKEN}
            await ws.send(json.dumps(auth_msg))
            auth_resp = await ws.recv()
            auth_data = json.loads(auth_resp)
            if "error" in auth_data:
                print(f"\033[91m● Authorization failed: {auth_data['error']['message']}\033[0m")
                return
            print("\033[92m● Authorized successfully.\033[0m")

            # Prepare subscription requests
            print("\033[95m● Preparing subscriptions...\033[0m")
            
            # Batch 1: Tick subscriptions
            for symbol in SYMBOLS:
                tick_sub = {"ticks": symbol, "subscribe": 1}
                await ws.send(json.dumps(tick_sub))
                await asyncio.sleep(0.05)
            
            # Batch 2: Candle subscriptions
            for symbol in SYMBOLS:
                for gran in GRANULARITIES:
                    candle_sub = {
                        "candles": symbol,
                        "granularity": GRANULARITY_MAP[gran],
                        "subscribe": 1
                    }
                    await ws.send(json.dumps(candle_sub))
                    await asyncio.sleep(0.05)
            
            print("\033[92m● All subscriptions sent. Starting data processing...\033[0m")
            print(f"\n\033[95m● TRACKING {len(SYMBOLS)} VOLATILITY INDICES\033[0m\n")

            # Main processing loop
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(message)
                    
                    # Handle different message types
                    if 'tick' in data:
                        await handle_tick(data['tick'])
                    elif 'candles' in data:
                        await handle_candle(data['candles'])
                    elif 'error' in data:
                        # Skip "Unrecognised request" warnings
                        if data['error']['code'] != 'UnrecognisedRequest':
                            print(f"\033[93m● API Warning: {data['error']['message']}\033[0m")
                    elif 'echo_req' in data:
                        # Skip echo responses
                        continue
                    else:
                        # Skip unhandled messages
                        continue
                    
                except asyncio.TimeoutError:
                    # Send ping to maintain connection
                    await ws.send(json.dumps({"ping": 1}))
                except Exception as e:
                    print(f"\033[91m● Processing Error: {str(e)[:80]}\033[0m")

    except Exception as e:
        print(f"\033[91m● Connection Error: {str(e)[:100]} (Reconnecting in 10s)\033[0m")
        await asyncio.sleep(10)
        await subscribe_data()

# --- MAIN EXECUTION ---
async def main():
    initialize_csv()
    print("\033[96m" + "━"*70)
    print(f"● VOLATILITY INDEX TRACKER | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
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
