--- MAIN EXECUTION ---

async def main(): initialize_files() print("\033[96m" + "━"*70) print(f"● AUTOMATED VOLATILITY INDEX TRADING SYSTEM | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}") print(f"● SYMBOLS: {', '.join(SYMBOLS)}") print(f"● TRADING: {'ENABLED' if TRADING_ENABLED else 'DISABLED'} | Amount: ${TRADE_AMOUNT} | Duration: {TRADE_DURATION}min") print(f"● RISK MANAGEMENT: SL={STOP_LOSS_PERCENT}% | TP={TAKE_PROFIT_PERCENT}%") print(f"● STRATEGY: Strength={STRONG_LEVEL_THRESHOLD}+ hits | Max signals/day={MAX_SIGNALS_PER_DAY}") print("━"*70 + "\033[0m")

while True:
    try:
        await run_trading_system()
    except Exception as e:
        print(f"\033[91m● System Error: {e} (Restarting in 30s)\033[0m")
        await asyncio.sleep(30)

--- WEBSOCKET MANAGEMENT ---

async def run_trading_system(): market_url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}" trade_url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

market_ws = await websockets.connect(market_url)
trade_ws = await websockets.connect(trade_url)

try:
    # Authorize both
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
        await market_ws.send(json.dumps({"ticks": symbol, "subscribe": 1}))
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

    # Main loop
    while True:
        try:
            message = await asyncio.wait_for(market_ws.recv(), timeout=30)
            if message is None:
                print(f"\033[91m● Warning: Empty message received from WebSocket.\033[0m")
                continue

            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print(f"\033[91m● JSON Decode Error: {message}\033[0m")
                continue

            if 'tick' in data:
                await handle_tick(data['tick'], trade_ws)
            elif 'candles' in data:
                await handle_candle(data['candles'])
            elif 'error' in data and data['error']['code'] != 'UnrecognisedRequest':
                print(f"\033[93m● API Warning: {data['error']['message']}\033[0m")

        except asyncio.TimeoutError:
            print(f"\033[94m● Timeout reached. Sending ping to keep connections alive...\033[0m")
            await market_ws.send(json.dumps({"ping": 1}))
            await trade_ws.send(json.dumps({"ping": 1}))
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"\033[91m● Connection closed with error: {e} — restarting...\033[0m")
            break
        except websockets.exceptions.ConnectionClosedOK:
            print(f"\033[91m● Connection closed cleanly by server.\033[0m")
            break
        except Exception as e:
            print(f"\033[91m● Unexpected Error: {e} (continuing...)\033[0m")

finally:
    if not market_ws.closed:
        await market_ws.close()
        print("\033[93m● Market WebSocket closed.\033[0m")
    if not trade_ws.closed:
        await trade_ws.close()
        print("\033[93m● Trade WebSocket closed.\033[0m")

