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
simulation_executor = ThreadPoolExecutor(max_workers=20)  # Reduced from 200 to prevent thread explosion

hedge_thread_locks = {}
monitor_locks = {}
simulation_locks = {}

class WebSocketHandler:
    def __init__(self):
        self.ws_url = BINANCE_WS_URL
        self.running_flags = {}  # Add per-UID running flags

    def stop_worker(self, uid):
        # Signal the worker thread for this UID to stop
        self.running_flags[uid] = False

    def worker(self, uid):
        log_info(f"WORKER STARTED for {uid}")
        self.running_flags[uid] = True  # Set running flag to True when starting
        trade_type = None
        log_info(f"step1: 🤮 Worker started for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
        print(f"🤮 Worker started for UID: {uid}")

        monitor_lock = monitor_locks.setdefault(uid, threading.Lock())

        def wrapped_simulation():
            log_info(f"step2: 🚦 Simulation thread started for: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
            sim_lock = simulation_locks.setdefault(uid, threading.Lock())
            
            # Track simulation start time for monitoring
            simulation_thread_monitor[uid] = time.time()
            
            try:
                with sim_lock:
                    log_info(f"step3: [SIM_ACTION] Calling test_simulation_handle_trade_action for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    test_simulation_handle_trade_action(uid, current_price)
                    log_info(f"step4: 🔚 Simulation thread completed successfully for: {uid}", uid=uid)
            except Exception as e:
                log_error(e, "simulation_thread", uid)
            finally:
                # Clean up monitoring
                simulation_thread_monitor.pop(uid, None)
                log_info(f"step4: 🔚 Simulation thread finished for: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)

        step = 5
        while self.running_flags.get(uid, False):
            # Always fetch latest details and trade_type at the start of the loop
            with get_lock(all_pairs_locks, uid):
                details = all_pairs.get(uid)
            trade_type = details.get("type") if details else None
            log_info(f"[LOOP_FETCH] UID: {uid} trade_type: {trade_type} | details: {details}", uid=uid)

            log_info(f"step{step}: [WORKER_LOOP] UID: {uid} is active | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
            step += 1
            try:
                # ✅ Get current price
                with get_lock(analysis_tracker_locks, uid):
                    current_price = analysis_tracker.get(uid, {}).get("Current_Price")
                    log_info(f"step{step}: [PRICE_CHECK] UID: {uid}, current_price: {current_price} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                step += 1

                # For hedge_release records, process immediately without waiting for price
                if trade_type == "hedge_release":
                    log_info(f"step{step}: [HEDGE_RELEASE_PROCESS] UID: {uid} processing hedge_release immediately | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # Process hedge_release logic here (will be handled in the elif below)
                elif not current_price or current_price <= 0:
                    log_info(f"step{step}: [WAIT] UID: {uid} waiting for valid price | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    time.sleep(1)
                    continue

                # Only trigger simulation if not a 1:1 hedge
                should_trigger_sim = not details.get('hedge_1_1_bool', False)
                if should_trigger_sim:
                    log_info(f"step{step}: [SIM_SUBMIT] Submitting simulation for UID: {uid} (hedge_1_1_bool is False) | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    simulation_executor.submit(wrapped_simulation)

                # ✅ Run lightweight async tasks
                # Only submit signal_engine if 3 minutes have passed since last check
                now = utc_now()
                last_signal_check = last_5min_check_time.get(uid)
                if not last_signal_check or (now - last_signal_check).total_seconds() >= 60:
                    log_info(f"step{step}: [SIGNAL_ENGINE] Submitting Current_Analysis for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # executor.submit(Current_Analysis, all_pairs, current_price, uid)

                # details and trade_type already fetched at loop start
                log_info(f"step{step}: [DETAILS_FETCHED] UID: {uid} details: {details} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                step += 1

                if not details:
                    log_error(Exception(uid), "worker", uid)
                    log_info(f"step{step}: [NO_DETAILS] UID: {uid} details missing | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    time.sleep(1)
                    continue



                # Log before checking running logic
                log_info(f"[CHECK_RUNNING] UID: {uid} about to check running logic | trade_type: {trade_type}", uid=uid)

                if trade_type == "assign":
                    log_info(f"step{step}: [ASSIGN] UID: {uid} about to check running logic | trade_type: {trade_type}", uid=uid)

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
                    log_info(f"step{step}: [ASSIGN] UID: {uid} calculated quantity: {quantity} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    if quantity == 0:
                        details["type"] = "Close_Low_Investment"
                        log_info(f"step{step}: [ASSIGN] UID: {uid} set to Close_Low_Investment | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1
                    else:
                        log_info(f"step{step}: [ASSIGN_PlaceOrderFromFlatMarketSignal] UID: {uid} placing order | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1
                        PlaceOrderFromFlatMarketSignal(
                            all_pairs, uid, quantity, action,
                            "LONG" if action == "BUY" else "SHORT",
                            current_price, hedge,
                            interval, stop_price, 1, 0
                        )
                        log_info(f"step{step}: [After_PlaceOrderFromFlatMarketSignal] UID: {uid} placing order | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1

                elif trade_type == "running":
                    log_info(f"[ENTER_RUNNING] UID: {uid} entering running logic | trade_type: {trade_type}", uid=uid)
                    log_info(f"step{step}: [RUNNING] UID: {uid} entering running logic | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # ✅ Monitor hedge/single position
                    if details.get("hedge", False):
                        if monitor_lock.locked():
                            log_info(f"step{step}: [RUNNING] UID: {uid} monitor_lock locked, waiting | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            time.sleep(0.1)
                            continue
                        with monitor_lock:
                            if not details.get("hedge_1_1_bool", False):
                                log_info(f"step{step}: [RUNNING] UID: {uid} monitoring hedge position | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                                step += 1
                                monitor_hedge_position(uid, current_price)
                        if details.get("hedge_1_1_bool", False):
                            log_info(f"step{step}: [RUNNING] UID: {uid} checking and releasing hedge | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            # check_and_release_hedge(uid,current_price)  # Removed: now called from signal_engine after signal
                    else:
                        if monitor_lock.locked():
                            log_info(f"step{step}: [RUNNING] UID: {uid} monitor_lock locked, waiting | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            time.sleep(0.1)
                            continue
                        with monitor_lock:
                            log_info(f"step{step}: [RUNNING] UID: {uid} monitoring single position | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                            step += 1
                            #monitor_single_position(uid, current_price)
                            if not details.get("hedge", False):
                                log_info(f"step{step}: [SET_LAST_PRICE] UID: {uid} updating last price | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                                step += 1
                                executor.submit(setlastpairPrice, uid, current_price)

                    log_info(f"step{step}: [SIM_TRIGGER_CHECK] UID: {uid}, details: {details} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                    step += 1
                    # Only trigger simulation if not a 1:1 hedge
                    should_trigger_sim = not details.get('hedge_1_1_bool', False)
                    if should_trigger_sim:
                        log_info(f"step{step}: [SIM_TRIGGER] Starting simulation for UID: {uid} (hedge_1_1_bool is False), details: {details} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1
                        simulation_executor.submit(wrapped_simulation)
                    else:
                        log_info(f"step{step}: [SIM_TRIGGER] Not starting simulation for UID: {uid} (hedge_1_1_bool is True), details: {details} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                        step += 1
                elif trade_type == "hedge_release":
                    with get_lock(all_pairs_locks, uid):
                        all_pairs[uid]["type"] = "running"
                        # Update the database to reflect the status change
                        machine_id = get_machine_id()
                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        log_info(f"step{step}: [HEDGE_RELEASE] Updated UID: {uid} from hedge_release to running in database", uid=uid)
                    step += 1

            except Exception as e:
                print(f"[{utc_now()}] ❌ Error in worker({uid}):\n{str(e)}")
                log_error(e, "worker")
                log_info(f"step{step}: [EXCEPTION] UID: {uid} exception occurred | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
                step += 1
                time.sleep(3)
            time.sleep(1)  # Throttle the worker loop
            log_info(f"step{step}: [LOOP_END] UID: {uid} end of loop | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
            step += 1
        # Cleanup after thread stops
        log_info(f"step{step}: 🛑 Worker stopped for UID: {uid} | all_pairs[uid]: {all_pairs.get(uid)} | trade_type: {trade_type}", uid=uid)
        print(f"🛑 Worker stopped for UID: {uid}")
        log_info(f"WORKER EXITED for {uid}")

    async def mark_price_listener(self):
        log_info("📱 Connecting to Binance WebSocket...")
        print("📱 Connecting to Binance WebSocket...")

        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20) as ws:
                    log_info("✅ WebSocket connected.")
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
                            log_info(f"[WS_UPDATE] Updated price for UID: {uid}, symbol: {symbol}, price: {mark_price}")
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
