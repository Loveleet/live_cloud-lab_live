# core/place_order.py

import time
from datetime import datetime as dt, timezone
from utils.global_store import all_pairs_locks, high_and_low_swings
from utils.utils import calculate_commission, get_lock, get_default_analysis_tracker
from core.swing_utils import update_swing_dictonary
from utils.logger import log_event, log_error, safe_print, log_info
from core.setup_single_position import setup_single_position
from utils.FinalVersionTradingDB_PostgreSQL import fetch_qty_precision_from_db
from utils.Final_olab_database import olab_update_single_uid_in_table
from FinalVersionTrading import get3SwingsByMachines
from machine_id import get_machine_id

def PlaceOrderFromFlatMarketSignal(
    all_pairs, uid, quantity, action, positionSide,
    current_price, hedge, interval, stopPrice,
    trade_signal, profit_journey
):
    """
    Places or prepares an order based on signal.
    trade_signal = 0 → prep only
    trade_signal = 1 → live execution
    """
    try:
        log_info(f"STEP PLACE_ORDER 1: Entered PlaceOrderFromFlatMarketSignal | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
        if uid not in all_pairs:
            log_error(Exception(f"UID {uid} not found in all_pairs"), "PlaceOrderFromFlatMarketSignal", uid)
            log_info(f"STEP PLACE_ORDER 2: UID not in all_pairs, exiting | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
            return

        if current_price is None or current_price == 0:
            safe_print(f"[{uid}] ❌ Invalid price, skipping.")
            log_info(f"STEP PLACE_ORDER 3: Invalid price, skipping | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
            return

        start_time = time.time()
        utc_now_str = dt.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        log_info(f"STEP PLACE_ORDER 4: Start processing order | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

        with get_lock(all_pairs_locks, uid):
            log_info(f"STEP PLACE_ORDER 5: Acquired lock for UID | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
            pair = all_pairs[uid]["pair"]
            qty_precision = fetch_qty_precision_from_db(pair)
            hedge_quantity = round(quantity, qty_precision)
            log_info(f"STEP PLACE_ORDER 6: Calculated hedge_quantity={hedge_quantity} | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

            if hedge_quantity == 0:
                all_pairs[uid]["type"] = 'NO_QTY'
                safe_print(f"[{uid}] ❌ Quantity rounded to 0, skipping.")
                log_info(f"STEP PLACE_ORDER 7: Quantity rounded to 0, skipping | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
                return

            if trade_signal == 0:
                # Just prep the data
                all_pairs[uid]["added_qty"] = hedge_quantity
                all_pairs[uid]["interval"] = interval
                all_pairs[uid]["profit_journey"] = profit_journey
                if not hedge:
                    setup_single_position(uid)
                safe_print(f"[{uid}] ✅ Preparation complete.")
                log_event(uid, "PlaceOrderFromFlatMarketSignal", "Preparation complete", 0)
                log_info(f"STEP PLACE_ORDER 8: Preparation complete | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)
                return

            # Proceed with actual trade logic
            time_now = dt.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            commission = calculate_commission(current_price, hedge_quantity, current_price, hedge_quantity)
            log_info(f"STEP PLACE_ORDER 9: Calculated commission | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

            update_data = {
                "hedge_order_size": hedge_quantity,
                "stop_price": stopPrice
            }

            if action == 'BUY':
                min_stop_price = current_price + (commission / hedge_quantity)
                save_price = current_price + (current_price * 0.0105)
                stopPrice = min(stopPrice, current_price - (current_price * 0.02))

                update_data.update({
                    "buy_qty": hedge_quantity,
                    "buy_price": current_price
                })

                swings = get3SwingsByMachines(pair, interval, action, current_price)
                if swings:
                    if len(swings) > 0: update_data["swing1"] = swings[0] * 1.010
                    if len(swings) > 1: update_data["swing2"] = swings[1] * 1.020
                    if len(swings) > 2: update_data["swing3"] = swings[2] * 1.030
                log_info(f"STEP PLACE_ORDER 10: BUY logic processed | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

            elif action == 'SELL':
                min_stop_price = current_price - (commission / hedge_quantity)
                save_price = current_price - (current_price * 0.0105)
                stopPrice = max(stopPrice, current_price + (current_price * 0.02))

                update_data.update({
                    "sell_qty": hedge_quantity,
                    "sell_price": current_price
                })

                swings = get3SwingsByMachines(pair, interval, action, current_price)
                if swings:
                    if len(swings) > 0: update_data["swing1"] = swings[0] * 0.990
                    if len(swings) > 1: update_data["swing2"] = swings[1] * 0.980
                    if len(swings) > 2: update_data["swing3"] = swings[2] * 0.970
                log_info(f"STEP PLACE_ORDER 11: SELL logic processed | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

            # Update main dict with trade data
            all_pairs[uid].update(update_data)
            log_info(f"STEP PLACE_ORDER 12: Updated all_pairs[uid] with trade data | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

            if trade_signal == 1:
                # Finalize trade
                all_pairs[uid].update({
                    "operator_trade_time": time_now,
                    "min_comm_after_hedge": min_stop_price,
                    "interval": interval,
                    "save_price": save_price,
                    "type": "running"
                })
                log_info(f"STEP PLACE_ORDER 13: Finalized trade in all_pairs[uid] | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

                # Set hedge swing points from memory
                lower_swings = high_and_low_swings.get(uid, {}).get("lower_swings", [])
                higher_swings = high_and_low_swings.get(uid, {}).get("higher_swings", [])

                for _, swing_price in lower_swings:
                    if swing_price < current_price:
                        all_pairs[uid]["hedge_swing_low_point"] = swing_price
                        break

                for _, swing_price in higher_swings:
                    if swing_price > current_price:
                        all_pairs[uid]["hedge_swing_high_point"] = swing_price
                        break

                log_info(f"STEP PLACE_ORDER 14: Set hedge swing points | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

                # Save to DB
                machine_id = get_machine_id()
                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                log_info(f"STEP PLACE_ORDER 15: Updated DB for UID | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

                # Finalize setup
                setup_single_position(uid)
                log_info(f"STEP PLACE_ORDER 16: Finalized setup_single_position | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

                log_event(uid, "PlaceOrderFromFlatMarketSignal", "Assign_To_Running", 0)
                log_info(f"STEP PLACE_ORDER 17: Placed order event logged | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

                update_swing_dictonary(uid, pair)
                log_info(f"STEP PLACE_ORDER 18: Updated swing dictionary | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

        safe_print(f"[{uid}] ✅ Trade completed in {round(time.time() - start_time, 2)}s")
        log_info(f"STEP PLACE_ORDER 19: Trade completed | all_pairs[uid]: {all_pairs.get(uid)}", uid=uid)

    except Exception as e:
        log_error(e, "PlaceOrderFromFlatMarketSignal", uid)
        safe_print(f"[{uid}] ❌ Exception: {e}")
        log_info(f"STEP PLACE_ORDER 20: Exception occurred | all_pairs[uid]: {all_pairs.get(uid)} Exception: {e}", uid=uid)
