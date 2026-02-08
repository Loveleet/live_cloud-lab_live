# main.py

import time
import traceback
import threading
import sys
import subprocess
import os

from core.ws_handler import WebSocketHandler
from bot_manager import BotManager
from utils.logger import log_error, log_info, log_system_health, utc_now
from utils.db_updater import DBUpdater
from utils.watchdog import start_watchdog
from utils.global_store import last_heartbeat

def setup_machine_config():
    """Setup machine configuration from environment variables"""
    # Read MACHINE_ID from environment variable
    machine_id = os.environ.get('MACHINE_ID', 'M2')
    
    # Set the global machine ID
    from machine_id import set_machine_id
    set_machine_id(machine_id)
    
    # Log the machine setup
    log_info(f"🤖 Starting machine: {machine_id}")
    print(f"🤖 Machine {machine_id} initialized")
    
    return machine_id

def restart_program():
    print("🔄 Restarting process now...")
    log_error(Exception("Restart Program"), "restart_program")
    subprocess.Popen([sys.executable] + sys.argv)
    sys.exit(0)


def start_system_health_logger():
    def periodic_health_logger():
        while True:
            try:
                log_system_health()
            except Exception as e:
                print(f"❌ Health Monitor Error: {e}")
            time.sleep(300)  # 5 minutes

    thread = threading.Thread(target=periodic_health_logger, daemon=True, name="SystemHealthLogger")
    thread.start()
    log_info("✅ System health logger started.")

def start_main_heartbeat():
    def heartbeat_loop():
        while True:
            last_heartbeat["main"] = time.time()
            time.sleep(5)
    thread = threading.Thread(target=heartbeat_loop, daemon=True, name="MainHeartbeat")
    thread.start()
    log_info("✅ Main heartbeat thread started.")

def start_all_threads():
    log_info("🚀 Starting main bot threads...")

    # Start watchdog
    start_watchdog()

    # Start main heartbeat
    start_main_heartbeat()

    # Start system health monitor
    start_system_health_logger()

    # Initialize components
    bot_manager = BotManager()
    ws_handler = WebSocketHandler()
    db_updater = [DBUpdater()]  # Use a list to hold the instance

    # Add DB updater health monitoring
    def monitor_db_updater():
        while True:
            try:
                current_time = time.time()
                last_update = db_updater[0].last_successful_update
                # Check if DB updater is stuck (no updates in 2 minutes)
                if current_time - last_update > 120:  # 2 minutes
                    log_error(Exception("DB Updater appears stuck"), "monitor_db_updater", "health_check")
                    # Restart DB updater
                    db_updater[0].stop()
                    time.sleep(5)
                    db_updater[0] = DBUpdater()
                    db_thread = threading.Thread(target=db_updater[0].run, daemon=True, name="DBUpdater")
                    db_thread.start()
                    log_info("✅ DB Updater restarted due to health check")
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                log_error(e, "monitor_db_updater")
                time.sleep(30)

    threads = [
        threading.Thread(target=bot_manager.run, daemon=True, name="BotManager"),
        threading.Thread(target=ws_handler.run, daemon=True, name="WebSocketHandler"),
        threading.Thread(target=db_updater[0].run, daemon=True, name="DBUpdater"),
        # threading.Thread(target=monitor_db_updater, daemon=True, name="DBUpdaterMonitor"),
    ]

    for t in threads:
        t.start()
        log_info(f"✅ Thread started: {t.name}")

    # Run continuously
    from machine_id import get_machine_id
    machine_id = get_machine_id() or 'UNKNOWN'
    print(f"🤖 Machine {machine_id} running continuously...")
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"🤖 Machine {machine_id} received shutdown signal")

def main():
    try:
        # Setup machine configuration first
        machine_id = setup_machine_config()
        
        start_all_threads()
    except Exception as e:
        print(f"[{utc_now()}] 🔴 Fatal error in main():\n{traceback.format_exc()}")
        log_error(e, "main")

if __name__ == "__main__":
    try:
        main()
        from machine_id import get_machine_id
        machine_id = get_machine_id() or 'UNKNOWN'
        print(f"[{utc_now()}] ✅ Machine {machine_id} completed successfully")
    except Exception as e:
        from machine_id import get_machine_id
        machine_id = get_machine_id() or 'UNKNOWN'
        print(f"[{utc_now()}] ❌ Machine {machine_id} failed:\n{traceback.format_exc()}")
        log_error(e, "main")
        sys.exit(1)
