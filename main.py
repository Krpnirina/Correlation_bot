import asyncio
import websockets
import json
import csv
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict

# --- CONFIGURATION ---
CSV_FILE = "trading_journal.csv"
TRADE_HISTORY_FILE = "trade_history.csv"
STRONG_LEVEL_THRESHOLD = 1
SUPPORT_ZONE_PERCENT = 0.115
RESISTANCE_ZONE_PERCENT = 0.115
TICKS_WINDOW_HOURS = 24
MIN_TICKS_REQUIRED = 900
VOLUME_THRESHOLD = 500
MAX_SIGNALS_PER_DAY = 4
API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = 71130
TRADING_ENABLED = True  # Set to False to disable real trading
TRADE_AMOUNT = 10       # USD per trade
TRADE_DURATION = 5      # Minutes per trade
STOP_LOSS_PERCENT = 1.5 # % from entry price
TAKE_PROFIT_PERCENT = 3 # % from entry price

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
    "signal_counts": 0,
    "active_trades": {}
})

candles_data = defaultdict(lambda: {
    "1d": None,
    "4h": None,
    "15m": None
})

# --- FILE INITIALIZATION ---
def initialize_files():
    # Trading signals journal
    with open(CSV_FILE, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "timestamp_utc", "symbol", "price", "level_type", "strength",
            "m15_min", "m15_max", "volume_status", "action", "trade_id"
        ])
    
    # Trade execution history
    with open(TRADE_HISTORY_FILE, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "timestamp", "trade_id", "symbol", "contract_type", "entry_price",
            "stake", "stop_loss", "take_profit", "duration", "result", "payout"
        ])

# --- VOLUME CHECK (on 15m candle) ---
def volume_confirmed(symbol):
    c15m = candles_data[symbol]["15m"]
    if c15m and c15m["volume"] >= VOLUME_THRESHOLD:
        return True
    return False

# --- TRADE EXECUTION ---
async def execute_trade(ws, symbol, price, level_type, strength):
    """Execute real trade on Deriv API"""
    if not TRADING_ENABLED:
        print(f"\033[93m● [SIMULATION] Would execute {'BUY' if level_type == 'SUPPORT' else 'SELL'} on {symbol} @ {price:.5f}\033[0m")
        return f"SIM-{datetime.now().timestamp()}"

    # Generate unique trade ID
    trade_id = f"{symbol}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    # Determine contract type
    contract_type = "CALL" if level_type == "SUPPORT" else "PUT"

    # Calculate stop loss and take profit
    stop_loss = price * (1 - STOP_LOSS_PERCENT/100) if level_type == "SUPPORT" else price * (1 + STOP_LOSS_PERCENT/100)
    take_profit = price * (1 + TAKE_PROFIT_PERCENT/100) if level_type == "SUPPORT" else price * (1 - TAKE_PROFIT_PERCENT/100)

    # Prepare trade request
    trade_request = {
        "buy": 1,
        "price": TRADE_AMOUNT,
        "parameters": {
            "amount": TRADE_AMOUNT,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": TRADE_DURATION,
            "duration_unit": "m",
            "symbol": symbol,
            "stop_loss": f"{stop_loss:.5f}",
            "take_profit": f"{take_profit:.5f}"
        }
    }

    # Send trade request
    await ws.send(json.dumps(trade_request))
    response = await ws.recv()
    trade_data = json.loads(response)

    # Handle trade response
    if "error" in trade_data:
        print(f"\033[91m● Trade Error: {trade_data['error']['message']}\033[0m")
        return None

    print(f"\033[92m● Trade Executed: {contract_type} on {symbol} @ {price:.5f} (ID: {trade_id})\033[0m")

    # Log trade
    with open(TRADE_HISTORY_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            trade_id, symbol, contract_type, price,
            TRADE_AMOUNT, stop_loss, take_profit,
            f"{TRADE_DURATION}m", "OPEN", ""
        ])

    # Store active trade
    daily_data[symbol]["active_trades"][trade_id] = {
        "entry_price": price,
        "contract_type": contract_type,
        "start_time": datetime.now(timezone.utc),
        "status": "OPEN"
    }

    return trade_id

# --- SIGNAL PROCESSING AND TRADING ---
async def handle_signal(ws, symbol, price, level_type, strength, m15_min, m15_max, timestamp):
    """Process signal and execute trade"""
    color = "\033[91m" if level_type == "SUPPORT" else "\033[92m"
    reset = "\033[0m"

    time_str = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')
    strength_display = "★" * min(strength, 3) + "!" * max(0, strength - 3)
    vol_status = "✅" if volume_confirmed(symbol) else "⚠️"
    action = "BUY" if level_type == "SUPPORT" else "SELL"

    # Execute trade
    trade_id = await execute_trade(ws, symbol, price, level_type, strength)

    print(f"{color}┏{'━'*70}┓")
    print(f"┃ VOLATILITY {level_type.ljust(10)} {symbol} @ {price:.5f} (Strength: {strength_display})")
    print(f"┃ {'Range:'.ljust(10)} {m15_min:.5f} - {m15_max:.5f} | Vol: {vol_status}")
    print(f"┃ {'Action:'.ljust(10)} {action} position executed")
    print(f"┃ {'Trade ID:'.ljust(10)} {trade_id or 'FAILED'}")
    print(f"┃ {'Time:'.ljust(10)} {time_str}")
    print(f"┗{'━'*70}┛{reset}")

    # Log to CSV
    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            symbol, price, level_type, strength,
            m15_min, m15_max, vol_status, action, trade_id or ""
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
async def handle_tick(tick, trade_ws):
    symbol = tick['symbol']
    price = float(tick['quote'])
    timestamp = tick['epoch']
    now = datetime.now(timezone.utc)

    data = daily_data[symbol]

    # Raha misy position misokatra dia tsy manao trade vaovao
    if data["active_trades"]:
        print(f"\033[93m[{symbol}] Trade efa misokatra, tsy manao trade vaovao.\033[0m")
        return

    data["ticks"].append((price, now))

    # Maintain 24-hour window
    while data["ticks"] and (now - data["ticks"][0][1]) > timedelta(hours=TICKS_WINDOW_HOURS):
        data["ticks"].popleft()

    # Periodic status update
    if len(data["ticks"]) % 25 == 0:
        print(f"\033[94m[{symbol}] ➜ Collected {len(data['ticks'])} ticks | Signals left: {MAX_SIGNALS_PER_DAY - data['signal_counts']} | Active trades: {len(data['active_trades'])}\033[0m")

    if len(data["ticks"]) >= MIN_TICKS_REQUIRED:
        prices = [p for p, _ in data["ticks"]]
        m15_min, m15_max = min(prices), max(prices)
        range_val = m15_max - m15_min

        # Dynamic zones
        support_zone = m15_min + (range_val * SUPPORT_ZONE_PERCENT)
        resistance_zone = m15_max - (range_val * RESISTANCE_ZONE_PERCENT)

        # Check volume before signals
        if not volume_confirmed(symbol):
            # Skip signal generation if volume too low
            return

        if price <= support_zone:
            key = f"SUPPORT_{m15_min:.5f}"
            data["support_hits"][key] += 1
            strength = data["support_hits"][key]

            if (strength >= STRONG_LEVEL_THRESHOLD and
                key not in data["levels_printed"] and
                data["signal_counts"] < MAX_SIGNALS_PER_DAY):

                data["levels_printed"].add(key)
                data["signal_counts"] += 1
                await handle_signal(trade_ws, symbol, price, "SUPPORT", strength, m15_min, m15_max, timestamp)

        elif price >= resistance_zone:
            key = f"RESISTANCE_{m15_max:.5f}"
            data["resistance_hits"][key] += 1
            strength = data["resistance_hits"][key]

            if (strength >= STRONG_LEVEL_THRESHOLD and
                key not in data["levels_printed"] and
                data["signal_counts"] < MAX_SIGNALS_PER_DAY):

                data["levels_printed"].add(key)
                data["signal_counts"] += 1
                await handle_signal(trade_ws, symbol, price, "RESISTANCE", strength, m15_min, m15_max, timestamp)

# --- WEBSOCKET MANAGEMENT ---
async def run_trading_system():
    # Create separate connections for market data and trading
    market_url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
    trade_url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

    async with websockets.connect(market_url) as market_ws, \
               websockets.connect(trade_url) as trade_ws:

        # Authorize both connections
        for ws in [market_ws, trade_ws]:
            await ws.send(json.dumps({"authorize": API_TOKEN}))
            auth_resp = await ws.recv()
            auth_data = json.loads(auth_resp)
            if "error" in auth_data:
                print(f"\033[91m● Authorization failed: {auth_data['error']['message']}\033[0m")
                return
        print("\033[92m● Authorized successfully for both connections.\033[0m")

        # Subscribe to market data
        print("\033[95m● Subscribing to market data...\033[0m")
        for symbol in SYMBOLS:
            # Ticks
            await market_ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
            # Candles
            for gran in GRANULARITIES:
                await market_ws.send(json.dumps({
                    "candles": symbol,
                    "granularity": GRANULARITY_MAP[gran],
                    "subscribe": 1
                }))
            await asyncio.sleep(0.05)

        print("\033[92m● Market data subscriptions complete.\033[0m")
        print(f"\n\033[95m● AUTOMATED TRADING ACTIVE | {len(SYMBOLS)} VOLATILITY INDICES\033[0m\n")
        print(f"\033[93m● TRADING {'ENABLED' if TRADING_ENABLED else 'DISABLED'} | Amount: ${TRADE_AMOUNT} | Duration: {TRADE_DURATION} min\033[0m")

        # Main processing loop
        while True:
            try:
                message = await asyncio.wait_for(market_ws.recv(), timeout=30)
                data = json.loads(message)

                # Handle market data
                if 'tick' in data:
                    await handle_tick(data['tick'], trade_ws)
                elif 'candles' in data:
                    await handle_candle(data['candles'])
                elif 'error' in data and data['error']['code'] != 'UnrecognisedRequest':
                    print(f"\033[93m● API Warning: {data['error']['message']}\033[0m")

            except asyncio.TimeoutError:
                # Send ping to maintain connection
                await market_ws.send(json.dumps({"ping": 1}))
                await trade_ws.send(json.dumps({"ping": 1}))
            except Exception as e:
                print(f"\033[91m● Processing Error: {str(e)[:80]}\033[0m")

# --- MAIN EXECUTION ---
async def main():
    initialize_files()
    print("\033[96m" + "━"*70)
    print(f"● AUTOMATED VOLATILITY INDEX TRADING SYSTEM | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"● SYMBOLS: {', '.join(SYMBOLS)}")
    print(f"● TRADING: {'ENABLED' if TRADING_ENABLED else 'DISABLED'} | Amount: ${TRADE_AMOUNT} | Duration: {TRADE_DURATION}min")
    print(f"● RISK MANAGEMENT: SL={STOP_LOSS_PERCENT}% | TP={TAKE_PROFIT_PERCENT}%")
    print(f"● STRATEGY: Strength={STRONG_LEVEL_THRESHOLD}+ hits | Max signals/day={MAX_SIGNALS_PER_DAY}")
    print("━"*70 + "\033[0m")

    while True:
        try:
            await run_trading_system()
        except Exception as e:
            print(f"\033[91m● System Error: {e} (Restarting in 30s)\033[0m")
            await asyncio.sleep(30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\033[94m\n● Trading system stopped by user ●\033[0m")
