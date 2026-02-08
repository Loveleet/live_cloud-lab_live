# utils/watchdog.py

import threading
import time
from datetime import datetime, timezone

from utils.logger import log_info, log_error
from utils.global_store import last_heartbeat, active_threads, message_queues
from core.ws_handler import WebSocketHandler

WATCHDOG_INTERVAL = 60  # seconds
HEARTBEAT_TIMEOUT = 120  # seconds

# Stub for alerting (e.g., email, Telegram)
def send_alert(uid, message):
    # Integrate with your alerting/notification system
    pass

def start_watchdog():
    def watchdog_loop():
        log_info("🔒 Watchdog started. Monitoring heartbeats...")
        ws_handler = WebSocketHandler()  # For restarting workers
        while True:
            try:
                now = datetime.now(timezone.utc)
                for uid, last_time in list(last_heartbeat.items()):
                    # Handle both float and datetime heartbeats
                    if isinstance(last_time, float):
                        delta = time.time() - last_time
                    elif isinstance(last_time, datetime):
                        delta = (now - last_time).total_seconds()
                    else:
                        log_error(Exception("Invalid heartbeat"), f"[Watchdog] Invalid heartbeat format for {uid}: {last_time}")
                        continue

                    if delta > HEARTBEAT_TIMEOUT:
                        log_error(Exception("HEARTBEAT_TIMEOUT"), f"[Watchdog] No heartbeat from {uid} in {delta:.0f}s. Thread might be frozen.")

                        send_alert(uid, f"No heartbeat from {uid} in {delta:.0f}s. Attempting restart.")
                        # Attempt to restart the worker thread if not alive
                        t = active_threads.get(uid)
                        if not t or not t.is_alive():
                            # Clean up old thread and queue
                            message_queues.pop(uid, None)
                            active_threads.pop(uid, None)
                            # Start a new worker thread
                            new_thread = threading.Thread(target=ws_handler.worker, args=(uid,), daemon=True)
                            new_thread.start()
                            active_threads[uid] = new_thread
                            log_info(f"✅ Watchdog restarted worker for UID: {uid}")

            except Exception as e:
                log_error(e, "watchdog_loop")

            time.sleep(WATCHDOG_INTERVAL)

    # Start watchdog thread
    t = threading.Thread(target=watchdog_loop, daemon=True)
    t.start()
