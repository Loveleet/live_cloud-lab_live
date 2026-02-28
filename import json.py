import json
import random
import time
import os
from datetime import datetime, timedelta

# Set file paths to the same directory as this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Get script directory
TRADE_FILE = os.path.join(BASE_DIR, "tradeData.json")
CLIENT_FILE = os.path.join(BASE_DIR, "clients.json")
LOG_FILE = os.path.join(BASE_DIR, "logs.json")

# Ensure the directory exists
os.makedirs(BASE_DIR, exist_ok=True)

# Get today's and yesterday's date for filtering counts
TODAY = datetime.now().strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Function to generate random trade data
def generate_trade():
    unique_id = str(random.randint(100000, 999999))
    pair = random.choice(["BTCUSDT", "ETHUSDT", "DOGEUSDT", "BNBUSDT"])
    investment = round(random.uniform(50, 500), 2)
    interval = random.choice(["1m", "3m", "5m", "15m", "30m", "1h", "4h"])
    stop_price = round(random.uniform(20, 100), 2)
    buy_price = round(random.uniform(0.2, 2), 5)
    buy_qty = round(investment / buy_price, 2)
    hedge = random.choice([True, False])
    
    # Ensure that Hold Hedge is properly populated and has a meaningful distribution
    hold_hedge = hedge and random.choice([True, False])
    profit_journey = random.choice([True, False])
    
    return {
        "Unique_id": unique_id,
        "pair": pair,
        "investment": investment,
        "interval": interval,
        "stop_price": stop_price,
        "save_price": round(random.uniform(0.1, 10), 2),
        "min_comm": round(random.uniform(0.01, 1), 5),
        "hedge": hedge,
        "hedge_1_1_bool": 1 if hold_hedge else 0,  # ✅ Hold Hedge now properly set
        "quantity": random.randint(10, 1000),
        "action": random.choice(["BUY", "SELL"]),
        "buy_qty": buy_qty,
        "commision_journey": random.choice([True, False]),
        "added_qty": round(investment / buy_price, 2),
        "min_comm_after_hedge": round(random.uniform(0.01, 1), 5),
        "buy_price": buy_price,
        "buy_pl": round(random.uniform(-100, 100), 2),
        "sell_qty": random.randint(100, 2000),
        "sell_price": round(random.uniform(0.5, 5), 5),
        "sell_pl": round(random.uniform(-150, 150), 2),
        "commission": round(random.uniform(0.1, 1), 5),
        "pl_after_comm": round(random.uniform(-150, 150), 2),
        "profit_journey": profit_journey,  # ✅ Fixed missing Profit Journey values
        "min_profit": round(random.uniform(0.1, 0.5), 5),
        "hedge_order_size": round(random.uniform(0.1, 1), 5),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": random.choice([TODAY, YESTERDAY])  # Randomly assign today or yesterday
    }

# Function to generate random client data
def generate_client():
    client_id = f"INV{random.randint(1000, 9999)}"
    investment_allowed = round(random.uniform(100, 1000), 2)
    active = random.choice([True, False])  # ✅ More realistic Active Clients
    return {
        "Client_id": client_id,
        "Investment_allowed": investment_allowed,
        "Active": active,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# Function to generate random log data
def generate_log():
    noticed = random.choice([True, False])
    auto_resolved = random.choice([True, False]) if noticed else False  # ✅ Ensures auto_resolved only applies if noticed

    return {
        "trade_id": str(random.randint(100000, 999999)),
        "status": random.choice(["failed", "successful"]),
        "error": random.choice(["Execution timeout", "API error", "Insufficient funds", "Price slippage"]),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Noticed": noticed,  # ✅ Some errors are noticed now
        "auto_resolved": auto_resolved  # ✅ Some errors are auto-resolved now
    }

# Continuous data generation loop
def generate_dummy_data():
    while True:
        try:
            # Generate and save 500 trades
            tradeData = [generate_trade() for _ in range(500)]
            with open(TRADE_FILE, "w", encoding="utf-8") as f:
                json.dump(tradeData, f, indent=4)

            # Generate and save 50 clients
            clients = [generate_client() for _ in range(50)]
            with open(CLIENT_FILE, "w", encoding="utf-8") as f:
                json.dump(clients, f, indent=4)

            # Generate and save 100 logs
            logs = [generate_log() for _ in range(100)]
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=4)

            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Updated JSON files with 500 trades, 50 clients, 100 logs.")
        except Exception as e:
            print(f"❌ Error writing to file: {e}")

        time.sleep(5)  # Update every 5 seconds

# Run the dummy data provider
if __name__ == "__main__":
    generate_dummy_data()