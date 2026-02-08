# utils/db_updater.py

import time
import traceback
import threading
from utils.global_store import all_pairs, all_pairs_lock, shutdown_event
from utils.logger import log_error, log_info
from utils.Final_olab_database import olab_update_table_from_all_pairs, olab_update_tmux_log
from machine_id import get_machine_id

class DBUpdater:
    def __init__(self, interval_seconds=20):
        self.interval = interval_seconds
        self.running = True
        self.last_successful_update = time.time()

    def stop(self):
        """Stop the DB updater gracefully"""
        log_info("🛑 Stopping DBUpdater...")
        self.running = False

    def run(self):
        log_info("📤 DBUpdater thread started...")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.running and not shutdown_event.is_set():
            try:
                start_time = time.time()
                olab_update_tmux_log('BotMain')
                
                # ✅ Add timeout protection
                
                machine_id = get_machine_id() or 'UNKNOWN'
                with all_pairs_lock:
                    update_thread = threading.Thread(
                        target= olab_update_table_from_all_pairs, 
                        args=(all_pairs, machine_id)
                    )
                update_thread.daemon = True
                update_thread.start()
                
                # Wait for update with timeout
                update_thread.join(timeout=30)  # 30 second timeout
                
                if update_thread.is_alive():
                    log_error(Exception("DB Update timeout"), "DBUpdater.run", "timeout")
                    consecutive_errors += 1
                else:
                    # Success
                    consecutive_errors = 0
                    self.last_successful_update = time.time()
                    processing_time = time.time() - start_time
                    log_info(f"✅ DB Update All Pairs completed in {processing_time:.2f}s")
                
                # Check for consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    log_error(Exception("Too many consecutive DB update errors"), "DBUpdater.run", "critical")
                    break  # Exit the loop

            except Exception as e:
                log_error(e, traceback.format_exc(), "DBUpdater.run")
                consecutive_errors += 1
            
            # Wait for the next interval in a cancellable way
            shutdown_event.wait(self.interval)
        
        log_info("📤 DBUpdater thread finished.")
