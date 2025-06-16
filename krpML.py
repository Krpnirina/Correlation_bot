import tkinter as tk
from tkinter import messagebox, scrolledtext
import websocket
import threading
import json
import time
import datetime

# --- Configuration ---
API_TOKEN = "REzKac9b5BR7DmF"
APP_ID = "71130"
WS_URL = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
SYMBOL = "R_100"
CONTRACT_DURATION = 60  # 60 minutes = 1 hour

# Multi-timeframe candles
TIMEFRAMES = ["15m", "30m", "1h"]

class DerivBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Deriv Trading Bot")
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.balance = None
        self.last_price = None
        self.status = "Disconnected"
        self.win_count = 0
        self.loss_count = 0

        # Stockage candles multi-timeframe { timeframe: last_candle }
        self.candles = {tf: None for tf in TIMEFRAMES}
        # Stockage volume ticks vs transaction volume (derain update)
        self.volume_ticks = 0
        self.volume_transaction = 0

        self.create_widgets()
        self.log("Application started")

    def create_widgets(self):
        frame_status = tk.Frame(self.root)
        frame_status.pack(padx=10, pady=5, fill="x")

        tk.Label(frame_status, text="Bot Status:").grid(row=0, column=0, sticky="w")
        self.lbl_status = tk.Label(frame_status, text=self.status, fg="red")
        self.lbl_status.grid(row=0, column=1, sticky="w")

        tk.Label(frame_status, text="Symbole:").grid(row=1, column=0, sticky="w")
        self.lbl_symbol = tk.Label(frame_status, text=SYMBOL)
        self.lbl_symbol.grid(row=1, column=1, sticky="w")

        tk.Label(frame_status, text="Dernier Prix:").grid(row=2, column=0, sticky="w")
        self.lbl_last_price = tk.Label(frame_status, text="N/A")
        self.lbl_last_price.grid(row=2, column=1, sticky="w")

        tk.Label(frame_status, text="Balance:").grid(row=3, column=0, sticky="w")
        self.lbl_balance = tk.Label(frame_status, text="N/A")
        self.lbl_balance.grid(row=3, column=1, sticky="w")

        tk.Label(frame_status, text="Win/Loss:").grid(row=4, column=0, sticky="w")
        self.lbl_win_loss = tk.Label(frame_status, text="0 / 0")
        self.lbl_win_loss.grid(row=4, column=1, sticky="w")

        frame_buttons = tk.Frame(self.root)
        frame_buttons.pack(padx=10, pady=5, fill="x")

        self.btn_start = tk.Button(frame_buttons, text="Lancer le Bot", command=self.start_bot)
        self.btn_start.grid(row=0, column=0, padx=5)

        self.btn_stop = tk.Button(frame_buttons, text="Arrêter le Bot", command=self.stop_bot, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=5)

        self.btn_balance = tk.Button(frame_buttons, text="Afficher Balance", command=self.request_balance)
        self.btn_balance.grid(row=0, column=2, padx=5)

        self.btn_quit = tk.Button(frame_buttons, text="Quitter", command=self.quit_app)
        self.btn_quit.grid(row=0, column=3, padx=5)

        frame_log = tk.Frame(self.root)
        frame_log.pack(padx=10, pady=5, fill="both", expand=True)

        self.txt_log = scrolledtext.ScrolledText(frame_log, height=15, state="disabled", wrap="word")
        self.txt_log.pack(fill="both", expand=True)

    def log(self, message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert(tk.END, f"[{timestamp}] {message}\n")
        self.txt_log.configure(state="disabled")
        self.txt_log.see(tk.END)

    def start_bot(self):
        if self.running:
            self.log("Bot déjà en marche")
            return
        self.running = True
        self.status = "Connecting..."
        self.update_status()
        self.log("Connexion au WebSocket Deriv...")
        self.ws_thread = threading.Thread(target=self.run_ws)
        self.ws_thread.daemon = True
        self.ws_thread.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

    def stop_bot(self):
        if not self.running:
            self.log("Bot déjà arrêté")
            return
        self.running = False
        self.status = "Disconnecting..."
        self.update_status()
        if self.ws:
            self.ws.close()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.log("Bot arrêté")

    def quit_app(self):
        self.stop_bot()
        self.root.quit()

    def update_status(self):
        self.lbl_status.config(text=self.status, fg="green" if self.running else "red")

    def update_last_price(self, price):
        self.last_price = price
        self.lbl_last_price.config(text=f"{price:.2f}")

    def update_balance(self, balance):
        self.balance = balance
        self.lbl_balance.config(text=f"{balance:.2f}")

    def update_win_loss(self):
        self.lbl_win_loss.config(text=f"{self.win_count} / {self.loss_count}")

    def request_balance(self):
        if self.ws and self.running:
            self.log("Demande de balance...")
            get_account_status_msg = {"get_account_status": 1}
            self.ws.send(json.dumps(get_account_status_msg))
            self.log("Request sent: get_account_status")
        else:
            self.log("WebSocket non connecté ou bot non démarré")

    def buy_rise_fall(self, action, amount=1):
        """
        Envoi une commande d'achat Rise ou Fall
        action: "rise" ou "fall"
        amount: montant du stake en USD
        """
        if not self.ws:
            self.log("WebSocket non connecté")
            return

        contract_type = "rise" if action.lower() == "rise" else "fall"
        msg = {
            "buy": 1,
            "parameters": {
                "contract_type": contract_type,
                "symbol": SYMBOL,
                "amount": amount,
                "duration": CONTRACT_DURATION,
                "duration_unit": "m",
                "basis": "stake",
                "currency": "USD",
            },
            "subscribe": 1
        }
        self.ws.send(json.dumps(msg))
        self.log(f"Trade envoyé: {action.upper()} {amount} USD durée {CONTRACT_DURATION} min")

    def analyze_candle_direction(self, candle):
        # Retourne "up" si bougie haussière, "down" si baissière
        if candle is None:
            return None
        return "up" if candle["close"] > candle["open"] else "down"

    def all_timeframes_agree(self):
        directions = []
        for tf in TIMEFRAMES:
            dir = self.analyze_candle_direction(self.candles[tf])
            if dir is None:
                return False
            directions.append(dir)
        # Jereo raha mitovy daholo
        return all(d == directions[0] for d in directions)

    def decide_trade(self):
        """
        Logique selon :
        - Volume ticks vs volume transaction (fampitahana "matanjaka" na "tsy matanjaka")
        - Direction bougies farany M15, M30, H1
        """
        if not self.all_timeframes_agree():
            self.log("Timeframes tsy mitovy direction, tsy manao trade")
            return None  # Tsy mitovy direction

        candle_dir = self.analyze_candle_direction(self.candles[TIMEFRAMES[0]])  # Direction M15

        volume_ratio = self.volume_ticks / self.volume_transaction if self.volume_transaction > 0 else 0

        # Famaritana hoe matanjaka ny volume ticks raha > 1.5 ny ratio (azonao ovaina araka ny fitsapana)
        volume_strong = volume_ratio > 1.5

        # Règles trading araka ny fanazavana
        if volume_strong and candle_dir == "down":
            return "SELL"
        elif volume_strong and candle_dir == "up":
            return "BUY"
        elif not volume_strong and candle_dir == "down":
            return "BUY"
        elif not volume_strong and candle_dir == "up":
            return "SELL"

        return None

    def execute_trade(self, action, price):
        if action not in ["BUY", "SELL"]:
            self.log("Action de trade invalide")
            return

        self.log(f"Execution trade: {action} au prix {price:.2f}")
        # Mampiasa buy_rise_fall avec contract duration 60 min
        if action == "BUY":
            self.buy_rise_fall("rise")
        else:
            self.buy_rise_fall("fall")

    def subscribe_ticks(self, ws):
        # Abonne à ticks
        tick_req = {"ticks": SYMBOL, "subscribe": 1}
        ws.send(json.dumps(tick_req))
        self.log("Subscription ticks envoyée")

    def subscribe_candles(self, ws, timeframe):
        # Subscribe candles pour timeframe (ex: 15m, 30m, 1h)
        req = {
            "ticks_history": SYMBOL,
            "end": "latest",
            "count": 1,
            "style": "candles",
            "granularity": self.timeframe_to_seconds(timeframe),
            "subscribe": 1
        }
        ws.send(json.dumps(req))
        self.log(f"Subscription candles {timeframe} envoyée")

    def timeframe_to_seconds(self, timeframe):
        # Convertir timeframe string en secondes
        unit = timeframe[-1]
        value = int(timeframe[:-1])
        if unit == "m":
            return value * 60
        elif unit == "h":
            return value * 3600
        else:
            return 60  # default 1 minute

    def on_message(self, ws, message):
        data = json.loads(message)
        self.log(f"Message reçu: {message}")

        if "authorize" in data:
            if data["authorize"].get("error") is None:
                self.status = "Bot Running"
                self.update_status()
                self.update_balance(data["authorize"].get("balance", 0))
                self.log(f"Autorisation réussie. Solde: {self.balance}")
                self.subscribe_ticks(ws)
                for tf in TIMEFRAMES:
                    self.subscribe_candles(ws, tf)
            else:
                self.status = "Erreur Authorization"
                self.update_status()
                error_msg = data["authorize"].get("error", {}).get("message", "Unknown error")
                self.log(f"Erreur autorisation: {error_msg}")
                ws.close()

        elif "tick" in data:
            price = data["tick"]["quote"]
            self.update_last_price(price)

            # Mety haka volume ticks eto raha misy (raha tsy misy dia 0 fotsiny)
            self.volume_ticks = data["tick"].get("volume", 0)

            # Raha afaka mandray trade isika dia atao fanapahan-kevitra eto
            trade_decision = self.decide_trade()
            if trade_decision:
                self.execute_trade(trade_decision, price)

        elif "history" in data:
            # Candles (tsirairay timeframe)
            candles = data["history"].get("candles", [])
            gran = data["history"].get("granularity")
            timeframe = self.seconds_to_timeframe(gran)
            if candles:
                self.candles[timeframe] = candles[-1]  # dernier candle
                self.log(f"Candle {timeframe} mise à jour")

        elif "buy" in data:
            # Réponse achat contrat
            bought = data["buy"]
            if bought.get("contract_id"):
                self.log(f"Trade contract_id: {bought['contract_id']} acheté")
            else:
                self.log("Erreur achat contrat")

        elif "get_account_status" in data:
            bal = data["get_account_status"].get("balance")
            if bal is not None:
                self.update_balance(bal)

        elif "error" in data:
            error_msg = data["error"].get("message", "Unknown error")
            self.log(f"Erreur API: {error_msg}")

    def seconds_to_timeframe(self, seconds):
        if seconds == 900:
            return "15m"
        elif seconds == 1800:
            return "30m"
        elif seconds == 3600:
            return "1h"
        else:
            return None

    def on_error(self, ws, error):
        self.status = "Erreur WebSocket"
        self.update_status()
        self.log(f"Erreur WebSocket: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.status = "Déconnecté"
        self.update_status()
        self.log(f"Connexion fermée: {close_status_code} - {close_msg}")

    def on_open(self, ws):
        self.log("Connexion WebSocket ouverte, envoi d'autorisation...")
        auth_data = {"authorize": API_TOKEN}
        ws.send(json.dumps(auth_data))

    def run_ws(self):
        self.ws = websocket.WebSocketApp(
            WS_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        while self.running:
            try:
                self.ws.run_forever()
            except Exception as e:
                self.log(f"Exception WebSocket: {e}")
                time.sleep(5)


if __name__ == "__main__":
    root = tk.Tk()
    app = DerivBotApp(root)
    root.mainloop()