# core/ws_handler.py

import asyncio
import json
import queue
import threading
import time
import websockets
from concurrent.futures import ThreadPoolExecutor
import os

from core.signal_engine import Current_Analysis
from core.setlastpairPrice import setlastpairPrice
from core.monitor_single_position import monitor_single_position
from core.monitor_hedge_position import monitor_hedge_position
from core.test_simulation_handle_trade_action import test_simulation_handle_trade_action
from core.check_and_release_hedge import check_and_release_hedge

from data_handler import DataHandler
from utils.global_store import (
    all_pairs_locks, all_pairs, active_threads, analysis_tracker, analysis_tracker_locks,
    last_heartbeat, message_queues, simulation_flags_lock,
    simulation_running_flags, last_simulation_time, last_5min_check_time,
    simulation_thread_monitor, simulation_timeout
)
from utils.logger import log_info, log_error, utc_now
from utils.utils import get_lock, get_default_analysis_tracker
from machine_id import get_machine_id
from utils.main_binance import getQuantity
from core.place_order import PlaceOrderFromFlatMarketSignal
from utils.FinalVersionTradingDB_PostgreSQL import update_single_uid_in_table

BINANCE_WS_URL = "wss://fstream.binance.com/ws/!markPrice@arr"

executor = ThreadPoolExecutor(max_workers=(os.cpu_count() or 1) * 4)
simulation_executor = ThreadPoolExecutor(max_workers=400)  # Reduced from 200 to prevent thread explosion

# Thread debugging function
def log_thread(message, uid=None):
    """Log thread-specific debugging information"""
    import os
    from datetime import datetime, timezone
    
    # Create logs_error directory if it doesn't exist
    log_dir = "logs_error"
    os.makedirs(log_dir, exist_ok=True)
    
    # Create filename
    if uid:
        # Per-UID thread debug file
        safe_uid = str(uid).replace("/", "_").replace("\\", "_").replace(":", "_")
        filename = f"thread_debug_{safe_uid}.log"
    else:
        # General thread debug file
        filename = "thread_debug.log"
    
    filepath = os.path.join(log_dir, filename)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Write to file
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [THREAD_DEBUG] {message}\n")

# Executor state monitoring function
def log_executor_state():
    """Log ThreadPoolExecutor internal state"""
    try:
        queue_size = simulation_executor._work_queue.qsize()
        active_threads = len([t for t in simulation_executor._threads if t.is_alive()])
        total_threads = len(simulation_executor._threads)
        
        log_thread(f"[EXECUTOR_STATE] Queue: {queue_size}, Active: {active_threads}/{total_threads}, Max: {simulation_executor._max_workers}")
        
        # Log individual thread states
        for i, thread in enumerate(simulation_executor._threads):
            if thread.is_alive():
                log_thread(f"[THREAD_{i}] Alive: {thread.name}")
            else:
                log_thread(f"[THREAD_{i}] Dead: {thread.name}")
                
    except Exception as e:
        log_error(e, "executor_state_logging")

# Periodic executor health check
def periodic_executor_health_check():
    """Run this every 5 minutes to check executor health"""
    while True:
        time.sleep(300)  # 5 minutes
        
        try:
            queue_size = simulation_executor._work_queue.qsize()
            active_threads = len([t for t in simulation_executor._threads if t.is_alive()])
            
            log_thread(f"Executor Health - Queue: {queue_size}, Active: {active_threads}")
            
            # Check for stuck simulations
            current_time = time.time()
            stuck_simulations = []
            for uid, start_time in list(simulation_thread_monitor.items()):
                if current_time - start_time > 60:  # 1 minute
                    stuck_simulations.append((uid, current_time - start_time))
            
            if stuck_simulations:
                log_error(f"Stuck simulations: {stuck_simulations}", "executor_health")
                log_thread(f"Stuck simulations detected: {stuck_simulations}")
            
        except Exception as e:
            log_error(e, "health_check_error")

hedge_thread_locks = {}
monitor_locks = {}
simulation_locks = {}

# Rate limiting for simulations
simulation_rate_limits = {}  # uid: last_simulation_timestamp
SIMULATION_RATE_LIMIT = 2  # seconds between simulations per UID

# Emergency queue clear function
def emergency_clear_queue():
    """Emergency function to clear the simulation queue"""
    try:
        queue_size = simulation_executor._work_queue.qsize()
        if queue_size > 10000:  # Emergency threshold
            log_thread(f"EMERGENCY: Clearing queue with {queue_size} items")
            # Clear the queue by draining it
            while not simulation_executor._work_queue.empty():
                try:
                    simulation_executor._work_queue.get_nowait()
                except:
                    break
            log_thread(f"EMERGENCY: Queue cleared, new size: {simulation_executor._work_queue.qsize()}")
    except Exception as e:
        log_error(e, "emergency_clear_queue")

class WebSocketHandler:
    def __init__(self):
        self.ws_url = BINANCE_WS_URL
        self.running_flags = {}  # Add per-UID running flags

    def stop_worker(self, uid):
        # Signal the worker thread for this UID to stop
        self.running_flags[uid] = False

    def worker(self, uid):
        #log_info(f"WORKER STARTED for {uid}")
        self.running_flags[uid] = True  # Set running flag to True when starting
        trade_type = None
        #log_info(f"step1: 🤮 Worker started for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
        print(f"🤮 Worker started for UID: {uid}")

        monitor_lock = monitor_locks.setdefault(uid, threading.Lock())

        def wrapped_simulation():
            simulation_start_time = time.time()
            log_thread(f"🚦 Simulation thread started for: {uid} | PID: {os.getpid()} | Thread: {threading.current_thread().name}", uid)
            log_thread(f"UID: {uid}, current_price: {current_price}, trade_type: {trade_type}", uid)
            
            sim_lock = simulation_locks.setdefault(uid, threading.Lock())
            
            # Track simulation start time for monitoring
            simulation_thread_monitor[uid] = simulation_start_time
            
            try:
                log_thread(f"UID: {uid} attempting to acquire simulation lock", uid)
                with sim_lock:
                    log_thread(f"UID: {uid} simulation lock acquired", uid)
                    log_thread(f"Calling test_simulation_handle_trade_action for UID: {uid}", uid)
                    
                    # Add timeout protection using ThreadPoolExecutor
                    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                    
                    def run_simulation():
                        return test_simulation_handle_trade_action(uid, current_price)
                    
                    try:
                        with ThreadPoolExecutor(max_workers=1) as timeout_executor:
                            future = timeout_executor.submit(run_simulation)
                            # 30 second timeout for simulation
                            future.result(timeout=30)
                            log_thread(f"test_simulation_handle_trade_action completed for UID: {uid}", uid)
                    except FutureTimeoutError:
                        log_error(Exception(f"Simulation timeout after 30s for UID: {uid}"), "simulation_timeout", uid)
                        log_thread(f"Simulation TIMEOUT for UID: {uid} after 30 seconds", uid)
                    except Exception as e:
                        log_error(e, "simulation_execution_error", uid)
                        log_thread(f"Simulation execution error for UID: {uid}, Error: {str(e)}", uid)
                    
            except Exception as e:
                log_error(e, "simulation_thread", uid)
                log_thread(f"UID: {uid} exception: {str(e)}", uid)
            finally:
                # Clean up monitoring
                simulation_thread_monitor.pop(uid, None)
                simulation_duration = time.time() - simulation_start_time
                log_thread(f"🔚 Simulation thread finished for: {uid} | Duration: {simulation_duration:.2f}s", uid)

        step = 5
        while self.running_flags.get(uid, False):
            # Always fetch latest details and trade_type at the start of the loop
            with get_lock(all_pairs_locks, uid):
                details = all_pairs.get(uid)
            trade_type = details.get("type") if details else None
            #log_info(f"[LOOP_FETCH] UID: {uid} trade_type: {trade_type} | details: {details}", uid=uid)

            #log_info(f"step{step}: [WORKER_LOOP] UID: {uid} is active | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
            log_thread(f"UID: {uid} | should_trigger_sim: {not details.get('hedge_1_1_bool', False)} | hedge_1_1_bool: {details.get('hedge_1_1_bool', False)}", uid)
            
            # Log executor state every 10 loops
            if step % 10 == 0:
                log_executor_state()
                # Emergency queue clear if needed
                emergency_clear_queue()
            
            step += 1
            try:
                # ✅ Get current price
                with get_lock(analysis_tracker_locks, uid):
                    current_price = analysis_tracker.get(uid, {}).get("Current_Price")
                    #log_info(f"step{step}: [PRICE_CHECK] UID: {uid}, current_price: {current_price} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                step += 1

                # For hedge_release records, process immediately without waiting for price
                if trade_type == "hedge_release":
                    #log_info(f"step{step}: [HEDGE_RELEASE_PROCESS] UID: {uid} processing hedge_release immediately | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # Process hedge_release logic here (will be handled in the elif below)
                elif not current_price or current_price <= 0:
                    #log_info(f"step{step}: [WAIT] UID: {uid} waiting for valid price | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    time.sleep(1)
                    continue

                # Only trigger simulation if not a 1:1 hedge
                should_trigger_sim = not details.get('hedge_1_1_bool', False)
                if should_trigger_sim:
                    queue_size = simulation_executor._work_queue.qsize()
                    log_thread(f"UID: {uid}, current_price: {current_price}, trade_type: {trade_type}", uid)
                    log_thread(f"Executor queue size: {queue_size}", uid)
                    
                    # CRITICAL: Prevent queue explosion
                    if queue_size > 1000:  # Limit queue size
                        log_thread(f"QUEUE OVERLOAD: Skipping simulation for UID: {uid}, queue size: {queue_size}", uid)
                        step += 1
                        continue
                    
                    # Rate limiting: Check if enough time has passed since last simulation
                    now = time.time()
                    last_sim_time = simulation_rate_limits.get(uid, 0)
                    if now - last_sim_time < SIMULATION_RATE_LIMIT:
                        log_thread(f"RATE LIMITED: Skipping simulation for UID: {uid}, last sim: {now - last_sim_time:.1f}s ago", uid)
                        step += 1
                        continue
                    
                    # Update rate limit timestamp
                    simulation_rate_limits[uid] = now
                    
                    try:
                        future = simulation_executor.submit(wrapped_simulation)
                        log_thread(f"Simulation submitted successfully for UID: {uid}, Future: {future}", uid)
                    except Exception as e:
                        log_error(e, "simulation_submit_error", uid)
                        log_thread(f"Failed to submit simulation for UID: {uid}, Error: {str(e)}", uid)
                    
                    step += 1

                # ✅ Run lightweight async tasks
                # Only submit signal_engine if 3 minutes have passed since last check
                now = utc_now()
                last_signal_check = last_5min_check_time.get(uid)
                if not last_signal_check or (now - last_signal_check).total_seconds() >= 60:
                    #log_info(f"step{step}: [SIGNAL_ENGINE] Submitting Current_Analysis for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # executor.submit(Current_Analysis, all_pairs, current_price, uid)

                # details and trade_type already fetched at loop start
                #log_info(f"step{step}: [DETAILS_FETCHED] UID: {uid} details: {details} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                step += 1

                if not details:
                    log_error(Exception(uid), "worker", uid)
                    #log_info(f"step{step}: [NO_DETAILS] UID: {uid} details missing | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    time.sleep(1)
                    continue



                # Log before checking running logic
                #log_info(f"[CHECK_RUNNING] UID: {uid} about to check running logic | trade_type: {trade_type}", uid=uid)

                if trade_type == "assign":
                    #log_info(f"step{step}: [ASSIGN] UID: {uid} about to check running logic | trade_type: {trade_type}", uid=uid)

                    pair = details.get("pair")
                    action = details.get("action")
                    interval = details.get("interval")
                    hedge = details.get("hedge", False)
                    stop_price = details.get("stop_price")
                    investment = details.get("investment")

                    if pair is not None and investment is not None:
                        result = getQuantity(pair, investment)
                        if result is not None and hasattr(result, '__iter__') and len(result) >= 1:
                            quantity = result[0]
                        else:
                            quantity = 0
                    else:
                        quantity = 0
                    #log_info(f"step{step}: [ASSIGN] UID: {uid} calculated quantity: {quantity} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    if quantity == 0:
                        details["type"] = "Close_Low_Investment"
                        #log_info(f"step{step}: [ASSIGN] UID: {uid} set to Close_Low_Investment | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1
                    else:
                        #log_info(f"step{step}: [ASSIGN_PlaceOrderFromFlatMarketSignal] UID: {uid} placing order | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1
                        PlaceOrderFromFlatMarketSignal(
                            all_pairs, uid, quantity, action,
                            "LONG" if action == "BUY" else "SHORT",
                            current_price, hedge,
                            interval, stop_price, 1, 0
                        )
                        #log_info(f"step{step}: [After_PlaceOrderFromFlatMarketSignal] UID: {uid} placing order | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1

                elif trade_type == "running":
                    #log_info(f"[ENTER_RUNNING] UID: {uid} entering running logic | trade_type: {trade_type}", uid=uid)
                    #log_info(f"step{step}: [RUNNING] UID: {uid} entering running logic | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # ✅ Monitor hedge/single position
                    if details.get("hedge", False):
                        if monitor_lock.locked():
                            #log_info(f"step{step}: [RUNNING] UID: {uid} monitor_lock locked, waiting | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            time.sleep(0.1)
                            continue
                        with monitor_lock:
                            if not details.get("hedge_1_1_bool", False):
                                #log_info(f"step{step}: [RUNNING] UID: {uid} monitoring hedge position | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                                step += 1
                                monitor_hedge_position(uid, current_price)
                        if details.get("hedge_1_1_bool", False):
                            #log_info(f"step{step}: [RUNNING] UID: {uid} checking and releasing hedge | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            # check_and_release_hedge(uid,current_price)  # Removed: now called from signal_engine after signal
                    else:
                        if monitor_lock.locked():
                            #log_info(f"step{step}: [RUNNING] UID: {uid} monitor_lock locked, waiting | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            time.sleep(0.1)
                            continue
                        with monitor_lock:
                            #log_info(f"step{step}: [RUNNING] UID: {uid} monitoring single position | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            #monitor_single_position(uid, current_price)
                            if not details.get("hedge", False):
                                #log_info(f"step{step}: [SET_LAST_PRICE] UID: {uid} updating last price | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                                step += 1
                                executor.submit(setlastpairPrice, uid, current_price)

                    #log_info(f"step{step}: [SIM_TRIGGER_CHECK] UID: {uid}, details: {details} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # Only trigger simulation if not a 1:1 hedge
                    should_trigger_sim = not details.get('hedge_1_1_bool', False)
                    if should_trigger_sim:
                        queue_size = simulation_executor._work_queue.qsize()
                        log_thread(f"Starting simulation for UID: {uid} (hedge_1_1_bool is False)", uid)
                        log_thread(f"Executor queue size: {queue_size}", uid)
                        
                        # CRITICAL: Prevent queue explosion
                        if queue_size > 1000:  # Limit queue size
                            log_thread(f"QUEUE OVERLOAD: Skipping simulation for UID: {uid}, queue size: {queue_size}", uid)
                            step += 1
                            continue
                        
                        # Rate limiting: Check if enough time has passed since last simulation
                        now = time.time()
                        last_sim_time = simulation_rate_limits.get(uid, 0)
                        if now - last_sim_time < SIMULATION_RATE_LIMIT:
                            log_thread(f"RATE LIMITED: Skipping simulation for UID: {uid}, last sim: {now - last_sim_time:.1f}s ago", uid)
                            step += 1
                            continue
                        
                        # Update rate limit timestamp
                        simulation_rate_limits[uid] = now
                        
                        try:
                            future = simulation_executor.submit(wrapped_simulation)
                            log_thread(f"Simulation submitted successfully for UID: {uid}, Future: {future}", uid)
                        except Exception as e:
                            log_error(e, "simulation_submit_error", uid)
                            log_thread(f"Failed to submit simulation for UID: {uid}, Error: {str(e)}", uid)
                        
                        step += 1
                    else:
                        log_thread(f"Not starting simulation for UID: {uid} (hedge_1_1_bool is True)", uid)
                        step += 1
                elif trade_type == "hedge_release":
                    with get_lock(all_pairs_locks, uid):
                        all_pairs[uid]["type"] = "running"
                        # Update the database to reflect the status change
                        machine_id = get_machine_id()
                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        #log_info(f"step{step}: [HEDGE_RELEASE] Updated UID: {uid} from hedge_release to running in database", uid=uid)
                    step += 1

            except Exception as e:
                print(f"[{utc_now()}] ❌ Error in worker({uid}):\n{str(e)}")
                log_error(e, "worker")
                #log_info(f"step{step}: [EXCEPTION] UID: {uid} exception occurred | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                step += 1
                time.sleep(3)
            time.sleep(1)  # Throttle the worker loop
            #log_info(f"step{step}: [LOOP_END] UID: {uid} end of loop | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
            step += 1
        # Cleanup after thread stops
        #log_info(f"step{step}: 🛑 Worker stopped for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
        print(f"🛑 Worker stopped for UID: {uid}")
        #log_info(f"WORKER EXITED for {uid}")

    async def mark_price_listener(self):
        #log_info("📱 Connecting to Binance WebSocket...")
        print("📱 Connecting to Binance WebSocket...")

        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                    #log_info("✅ WebSocket connected.")
                    print("✅ WebSocket connected.")
                    async for message in ws:
                       
                        self.handle_price_update(message)
                        last_heartbeat["main"] = time.time()

            except Exception as e:
                log_error(e, f" utc_now() mark_price_listener")
                await asyncio.sleep(5)

    def handle_price_update(self, message):
        try:
            data = json.loads(message)

            if isinstance(data, list):
                items = data
            elif isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                items = data["data"]
            else:
                print("⚠️ Unexpected format:", data)
                return

            for item in items:
                symbol = item.get("s")
                mark_price = float(item.get("p", 0))
                with get_lock(all_pairs_locks, "global"):  # Optional: use a global lock if available
                    pairs_snapshot = list(all_pairs.items())    

                for uid, pdata in pairs_snapshot:
                    if pdata.get("pair") == symbol:
                       

                        with get_lock(analysis_tracker_locks, uid):
                            if uid not in analysis_tracker:
                                analysis_tracker[uid] = get_default_analysis_tracker()
                            analysis_tracker[uid]["Current_Price"] = mark_price
                            #log_info(f"[WS_UPDATE] Updated price for UID: {uid}, symbol: {symbol}, price: {mark_price}")
                            # print(f"[WS_UPDATE] Updated price for UID: {uid}, symbol: {symbol}, price: {mark_price}")

                        if uid not in active_threads or not active_threads[uid].is_alive():
                            message_queues[uid] = queue.Queue()
                            print(f"🔍 xxxxxxxxx: {uid}")
                            t = threading.Thread(target=self.worker, args=(uid,), daemon=True)
                            t.start()
                            active_threads[uid] = t
                            print(f"🔟 Started worker for UID: {uid} (from WS)")
                            

        except Exception as e:
            log_error(e, "handle_price_update")

    def run(self):
        # Test logging
        log_thread("WebSocketHandler starting up - logging test")
        
        # Start health check thread
        health_thread = threading.Thread(target=periodic_executor_health_check, daemon=True, name="ExecutorHealthCheck")
        health_thread.start()
        log_thread("Executor health check thread started")
        
        handler = DataHandler()
        machine_id = get_machine_id()
        pair_map = handler.load_initial_data(machine_id, False)

        for uid, pdata in pair_map.items():
            with get_lock(all_pairs_locks, uid):
                all_pairs[uid] = pdata

            if uid not in active_threads or not active_threads[uid].is_alive():
                message_queues[uid] = queue.Queue()
                t = threading.Thread(target=self.worker, args=(uid,), daemon=True)
                t.start()
                active_threads[uid] = t
                print(f"✅ Started worker for running UID: {uid}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.mark_price_listener())
