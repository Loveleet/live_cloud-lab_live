from utils.logger import log_event, log_error, safe_print
from utils.global_store import (
    swing_proximity_flags_hedge_release,
    high_and_low_swings,
    all_pairs_locks,
    analysis_tracker_locks,
    analysis_tracker,
    all_pairs
)
from utils.utils import get_lock, calculate_commission, get_default_analysis_tracker
from core.swing_utils import get_safe_swing_point
from core.signal_engine import Current_Analysis
from utils.FinalVersionTradingDB_PostgreSQL import update_single_uid_in_table
from machine_id import get_machine_id


def check_and_release_hedge(uid, current_price, signal=None):
    """
    Releases one leg of a hedge (BUY/SELL) if swing level is near and reversal signal confirmed.
    Now, signal is passed directly from SignalEngine, so we don't need to re-check analysis_tracker[uid]['Decision'].
    """
    try:
        data = all_pairs.get(uid, {})
        hedge = data.get("hedge", False)
        hedge_1_1 = data.get("hedge_1_1_bool", False)
        
        # ✅ Only process full 1:1 hedge positions
        if  not hedge_1_1:
            return

        if uid not in analysis_tracker:
            analysis_tracker[uid] = get_default_analysis_tracker()
            # Current_Analysis(all_pairs, current_price, uid)  # Not needed, already done in SignalEngine

        pair = data.get("pair")
        buy_pl = float(data.get("buy_pl", 0))
        sell_pl = float(data.get("sell_pl", 0))

        last_hedge_high = data.get("hedge_swing_high_point") or get_safe_swing_point(uid, "high", current_price, pair)
        last_hedge_low = data.get("hedge_swing_low_point") or get_safe_swing_point(uid, "low", current_price, pair)

        # target_price = last_hedge_high if buy_pl > 0 else last_hedge_low if sell_pl > 0 else None
        # # if target_price is None:
        # #     return

        # distance = abs(current_price - target_price)
        # if distance <= current_price * 0.002 and not swing_proximity_flags_hedge_release.get(uid, False):
        #     swing_proximity_flags_hedge_release[uid] = True

        safe_print("\n" + "\n".join([
            "=" * 80,
            f"🔍 ******************** Hedge Release Check: {uid} ********************",
            f"    🔸 Current Price       : {current_price:.4f}",
            # f"    🔸 Target Swing Price  : {target_price:.4f}",
            # f"    🔸 Distance to Swing   : {distance:.4f}",
            f"    🔸 Buy PL              : {buy_pl:.4f}",
            f"    🔸 Sell PL             : {sell_pl:.4f}",
            # f"        5 min check        : {analysis_tracker[uid]}",
            "=" * 80
        ]) + "\n")

        # log_event(uid, "check_and_release_hedge", "Hedge release check performed", data.get("pl_after_comm", 0), {"current_price": current_price, "target_price": target_price, "distance": distance, "buy_pl": buy_pl, "sell_pl": sell_pl})

        # Use the passed signal directly, don't re-check analysis_tracker[uid]['Decision']
        decision = signal

        with get_lock(all_pairs_locks, uid):
            if decision == "SELL":
                buy_qty = float(data.get("buy_qty", 0.0))
                buy_price = float(data.get("buy_price", 0.0))
                Pl_after_comm = float(data.get("pl_after_comm", 0.0))
                commission = calculate_commission(buy_price, buy_qty, current_price, buy_qty)

                temp_high = data.get("temp_high_point")
                temp_low = data.get("temp_low_point")

                data["hedge_swing_high_point"] = analysis_tracker[uid].get('Candle_High')
                refreshed_low = get_safe_swing_point(uid, "low", current_price, pair)

                if temp_low and temp_low < current_price:
                    data["hedge_swing_low_point"] = temp_low
                elif refreshed_low and (temp_low is None or refreshed_low > temp_low):
                    data["hedge_swing_low_point"] = refreshed_low

                prev = float(data.get("hedge_buy_pl", 0.0))
                data["hedge_buy_pl"] = prev + (buy_pl - commission)

                data.update({
                    "buy_qty": 0,
                    "buy_price": 0,
                    "buy_pl": 0,
                    "action": "SELL",
                    "hedge_1_1_bool": False
                })

                with get_lock(analysis_tracker_locks, uid):
                    analysis_tracker[uid]["Decision"] = None

                log_event(uid, "check_and_release_hedge", "HEDGE RELEASED BUY POSITION", Pl_after_comm)

            elif decision == "BUY":
                sell_qty = float(data.get("sell_qty", 0.0))
                sell_price = float(data.get("sell_price", 0.0))
                Pl_after_comm = float(data.get("pl_after_comm", 0.0))
                sell_comm = calculate_commission(sell_price, sell_qty, current_price, sell_qty)

                temp_high = data.get("temp_high_point")
                temp_low = data.get("temp_low_point")

                data["hedge_swing_low_point"] = analysis_tracker[uid].get('Candle_Low')
                refreshed_high = get_safe_swing_point(uid, "high", current_price, pair)

                if temp_high and temp_high > current_price:
                    data["hedge_swing_high_point"] = temp_high
                elif refreshed_high and (temp_high is None or refreshed_high < temp_high):
                    data["hedge_swing_high_point"] = refreshed_high

                prev = float(data.get("hedge_sell_pl", 0.0))
                data["hedge_sell_pl"] = prev + (sell_pl - sell_comm)

                data.update({
                    "sell_qty": 0,
                    "sell_price": 0,
                    "sell_pl": 0,
                    "action": "BUY",
                    "hedge_1_1_bool": False
                })

                with get_lock(analysis_tracker_locks, uid):
                    analysis_tracker[uid]["Decision"] = None

                log_event(uid, "check_and_release_hedge", "HEDGE RELEASED SELL POSITION", Pl_after_comm)

        machine_id = get_machine_id()
        olab_update_single_uid_in_table(uid, all_pairs, machine_id)

    except Exception as e:
        log_error(e, "check_and_release_hedge", uid)
