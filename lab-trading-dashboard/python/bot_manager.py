# bot_manager.py

import time
import threading
import queue
from data_handler import DataHandler
from core.ws_handler import WebSocketHandler
from utils.global_store import all_pairs, active_threads, message_queues
from utils.logger import log_error, log_info
from machine_id import get_machine_id
# from utils.Final_olab_database import olab_update_single_uid_in_table

class BotManager:
    def __init__(self):
        self.last_heartbeat = time.time()
        self.data_handler = DataHandler()
        self.ws_handler = WebSocketHandler()
        self.running = True
        self.thread_monitor_interval = 30  # Check threads every 30 seconds
        self.last_thread_check = time.time()

    def monitor_threads(self):
        """Monitor active threads to ensure they don't silently disappear"""
        current_time = time.time()
        if current_time - self.last_thread_check < self.thread_monitor_interval:
            return
            
        self.last_thread_check = current_time
        
        dead_threads = []
        for uid, thread in active_threads.items():
            if not thread.is_alive():
                dead_threads.append(uid)
                print(f"⚠️ Thread for UID {uid} is dead, will restart")
                log_error(f"Thread for UID {uid} died unexpectedly", "BotManager.monitor_threads")
        
        # Restart dead threads
        for uid in dead_threads:
            if uid in all_pairs:
                message_queues[uid] = queue.Queue()
                print(f"🔄 Restarting dead thread for UID: {uid}")
                
                t = threading.Thread(target=self.ws_handler.worker, args=(uid,), daemon=True)
                t.start()
                active_threads[uid] = t
                print(f"✅ Restarted worker for UID: {uid}")
                log_info(f"BotManager.monitor_threads: [RESTARTED] UID: {uid}", uid=uid)



    def run(self):
        print(f"✅ BotManager.run() executed")
        last_known_uids = set()

        while self.running:
            try:
                # Monitor threads for silent failures
                self.monitor_threads()
                
                machine_id = get_machine_id()
                uid_data = self.data_handler.load_running_uids(machine_id)
                current_uids = set(uid_data.keys())
                new_uids = current_uids - last_known_uids
                removed_uids = last_known_uids - current_uids

                for uid in new_uids:
                    if uid not in active_threads or not active_threads[uid].is_alive():
                        message_queues[uid] = queue.Queue()
                        all_pairs[uid] = uid_data[uid]
                        print(f"✅ Processing UID that is not in active thread: {uid}")

                        t = threading.Thread(target=self.ws_handler.worker, args=(uid,), daemon=True)
                        t.start()
                        active_threads[uid] = t
                        print(f"\U0001F195 Started worker for UID: {uid}")
                        log_info(f"BotManager.run() 1: [NEW] UID: {uid} started | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

                for uid in removed_uids:
                    if uid not in all_pairs:
                        self.ws_handler.stop_worker(uid)
                        message_queues.pop(uid, None)
                        active_threads.pop(uid, None)
                        print(f"\U0001F6D1 Removed UID: {uid} (worker stopped, trade data retained)")
                        log_info(f"BotManager.run() 2: [REMOVED] UID: {uid} removed | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
      

                last_known_uids = current_uids
                self.last_heartbeat = time.time()

            except Exception as e:
                log_error(e, "BotManager.run")
                time.sleep(2)

            time.sleep(1)
