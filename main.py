import asyncio
import websockets
import json
import csv
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict

# --- CONFIGURATION ---
CSV_FILE = "trading_journal.csv"
TRADE_HISTORY_FILE = "trade_history.csv"
STRONG_LEVEL_THRESHOLD = 0
SUPPORT_ZONE_PERCENT = 0.115
RESISTANCE_ZONE_PERCENT = 0.115
TICKS_WINDOW_HOURS = 24
MIN_TICKS_REQUIRED = 300
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

# --- HELPER FUNCTION TO GET CURRENT TIME ---
def get_current_time():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

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

# --- VOLUME CHECK (RELAXED) ---
def volume_confirmed(symbol):
    c1d = candles_data[symbol]["1d"]
    c4h = candles_data[symbol]["4h"]
    c15m = candles_data[symbol]["15m"]
    
    # Accept if any timeframe meets threshold, or if all have at least minimal volume
    return any([
        (c1d and c1d["volume"] >= VOLUME_THRESHOLD),
        (c4h and c4h["volume"] >= VOLUME_THRESHOLD),
        (c15m and c15m["volume"] >= VOLUME_THRESHOLD),
        (c1d and c4h and c15m and 
         c1d["volume"] > 50 and 
         c4h["volume"] > 50 and 
         c15m["volume"] > 50)
    ])

# --- TRADE EXECUTION ---
async def execute_trade(ws, symbol, price, level_type, strength):
    """Execute real trade on Deriv API"""
    if not TRADING_ENABLED:
        print(f"\033[93m● [SIMULATION] Would execute {'BUY' if level_type == 'SUPPORT' else 'SELL'} on {symbol} @ {price:.5f}\033[0m")
        return f"SIM-{datetime.now(timezone.utc).timestamp()}"

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

        # Dynamic zones based on M15 min/max
        support_zone = m15_min + (range_val * SUPPORT_ZONE_PERCENT)
        resistance_zone = m15_max - (range_val * RESISTANCE_ZONE_PERCENT)

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
            data["resistance_hits"][key] +=
