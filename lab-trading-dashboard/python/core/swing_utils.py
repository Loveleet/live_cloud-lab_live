# core/swing_utils.py

from utils.logger import log_event, log_error, log_to_file
from FinalVersionTrading import CalculateSignals, get_high_swings_zones, get_low_swings_zones
from utils.global_store import high_and_low_swings, all_pairs, all_pairs_locks, high_and_low_swings_locks
from machine_id import get_machine_id
from utils.Final_olab_database import olab_update_single_uid_in_table
from utils.utils import get_lock, get_default_analysis_tracker

def get_safe_swing_point(uid, swing_type, current_price, pair):
    """
    Get a valid hedge swing point:
    Tries 15m → 30m → 1h → 4h → 1d, then fallback deviation.
    """
    try:
        intervals = ['15m', '30m', '1h', '4h', '1d']
        for interval in intervals:
            df = CalculateSignals(pair, interval)
            if df is not None:
                if swing_type == "high":
                    result = get_high_swings_zones(df)
                    if result is not None:
                        last_high_swing, higher_swings = result
                        for item in [last_high_swing] + (higher_swings if higher_swings is not None else []):
                            if item and len(item) == 2 and item[1] > current_price:
                                # log_event(uid, "swing_utils.get_safe_swing_point", "Found high swing point", 0)
                                return item[1]
                elif swing_type == "low":
                    result = get_low_swings_zones(df)
                    if result is not None:
                        last_low_swing, lower_swings = result
                        for item in [last_low_swing] + (lower_swings if lower_swings is not None else []):
                            if item and len(item) == 2 and item[1] < current_price:
                                # log_event(uid, "swing_utils.get_safe_swing_point", "Found low swing point", 0)
                                return item[1]
    except Exception as e:
        log_error(e, "get_safe_swing_point", uid)


def update_swing_dictonary(uid, pair):
    try:
        df = CalculateSignals(pair, '15m')
        if df is not None:
            low_result = get_low_swings_zones(df)
            high_result = get_high_swings_zones(df)
            if low_result is not None and high_result is not None:
                last_low_swing, lower_swings = low_result
                last_high_swing, higher_swings = high_result
                with get_lock(high_and_low_swings_locks, uid):
                    if uid not in high_and_low_swings:
                        high_and_low_swings[uid] = {}
                    high_and_low_swings[uid]["lower_swings"] = [last_low_swing] + (lower_swings if lower_swings is not None else [])
                    high_and_low_swings[uid]["higher_swings"] = [last_high_swing] + (higher_swings if higher_swings is not None else [])

    except Exception as e:
        log_error(e, "update_swing_dictonary", uid)


def refresh_swing_points(uid, current_price, pair):
    try:
        intervals = ['15m', '30m', '1h', '4h', '1d']
        found_high = found_low = False
        latest_open = latest_close = latest_high = latest_low = None
        for interval in intervals:
            df = CalculateSignals(pair, interval)
            if df is not None:
                if latest_open is None:
                    latest_open = df['open'].iloc[-1]
                    latest_close = df['close'].iloc[-1]
                    latest_high = df['high'].iloc[-1]
                    latest_low = df['low'].iloc[-1]
                high_result = get_high_swings_zones(df)
                low_result = get_low_swings_zones(df)
                if high_result is not None and low_result is not None:
                    last_high_swing, higher_swings = high_result
                    last_low_swing, lower_swings = low_result
                    allhighs = ([last_high_swing] if last_high_swing is not None else []) + (higher_swings if higher_swings is not None else [])
                    alllows = ([last_low_swing] if last_low_swing is not None else []) + (lower_swings if lower_swings is not None else [])
                    with get_lock(high_and_low_swings_locks, uid):
                        if uid not in high_and_low_swings:
                            high_and_low_swings[uid] = {}
                        high_and_low_swings[uid]["higher_swings"] = allhighs
                        high_and_low_swings[uid]["lower_swings"] = alllows
                    with get_lock(all_pairs_locks, uid):
                        if not found_high:
                            old_high = all_pairs[uid].get("hedge_swing_high_point", 0)
                            if current_price > old_high:
                                if (latest_open > old_high and latest_close > old_high and
                                    latest_high > old_high and latest_low > old_high):
                                    if allhighs is not None:
                                        for _, swing_price in allhighs:
                                            if swing_price > current_price:
                                                all_pairs[uid]["hedge_swing_high_point"] = swing_price
                                                all_pairs[uid]["temp_low_point"] = old_high
                                                log_to_file(f"✅ SWING HIGH UPDATED from {old_high} to {swing_price} | UID: {uid}", "swing_update")
                                                machine_id = get_machine_id()
                                                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                                                found_high = True
                                                break
                                else:
                                    log_to_file(f"⛔ SWING HIGH NOT UPDATED → candle not closed above {old_high} | UID: {uid}", "swing_update")
                        if not found_low:
                            old_low = all_pairs[uid].get("hedge_swing_low_point", 999999)
                            if current_price < old_low:
                                if (latest_open < old_low and latest_close < old_low and
                                    latest_high < old_low and latest_low < old_low):
                                    if alllows is not None:
                                        for _, swing_price in alllows:
                                            if swing_price < current_price:
                                                all_pairs[uid]["hedge_swing_low_point"] = swing_price
                                                all_pairs[uid]["temp_high_point"] = old_low
                                                log_to_file(f"✅ SWING LOW UPDATED from {old_low} to {swing_price} | UID: {uid}", "swing_update")
                                                machine_id = get_machine_id()
                                                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                                                found_low = True
                                                break
                                else:
                                    log_to_file(f"⛔ SWING LOW NOT UPDATED → candle not closed below {old_low} | UID: {uid}", "swing_update")
                    if found_high and found_low:
                        break

    except Exception as e:
        log_error(e, "refresh_swing_points", uid)
