# core/signal_engine.py

from datetime import datetime as dt, timezone
from utils.logger import log_event, log_error, utc_now
from utils.global_store import last_5min_check_time, analysis_tracker_locks, high_and_low_swings, all_pairs_locks
from utils.utils import get_lock
from FinalVersionTrading import find_last_high, BollingerBandBreakout,MacdCrossOver,BBUpLowBand
from utils.utils import get_default_analysis_tracker
from utils.FinalVersionTradingDB_PostgreSQL import fetch_single_pair_from_db
import time
# threading import and semaphore removed

class SignalEngine:
    def __init__(self, all_pairs, analysis_tracker=None):
        self.all_pairs = all_pairs
        self.analysis_tracker = analysis_tracker or {}

    def run(self, uid, current_price):
        try:
            details = self.all_pairs.get(uid, {})
            # ✅ Early exit: Only process full 1:1 hedge positions

            hedge = details.get("hedge", False)
            hedge_1_1 = details.get("hedge_1_1_bool", False)

            if  not hedge_1_1:
                return
            
            action = details.get("action")
            pair = details.get("pair")
            interval = details.get("interval")
            Pl_after_comm = float(details.get("pl_after_comm", 0.0))
            now = utc_now()
            if uid not in last_5min_check_time:
                last_5min_check_time[uid] = now
            tracker = self.analysis_tracker.setdefault(uid, get_default_analysis_tracker())
            last_check = last_5min_check_time[uid]
            Last_check_time_calc = (now - last_check).total_seconds()
            
            if  (not last_check or Last_check_time_calc <= 1) and Last_check_time_calc !=0:
                return
            last_5min_check_time[uid] = now
            tracker['Current_Price'] = current_price
            pair_info = fetch_single_pair_from_db(pair)
            
            # Check if pair_info is None (pair not found in database)
            if pair_info is None:
                print(f"⚠️ Pair {pair} not found in database for UID {uid}")
                log_event(
                    uid,
                    "SignalEngine_PairNotFound",
                    f"Pair {pair} not found in database",
                    Pl_after_comm
                )
                return
            
            # Timing MacdCrossOver
            start_macd = time.time()
            result = MacdCrossOver(pair_info, check_exists=False)
            end_macd = time.time()
            print(f"[TIMER] {pair} MacdCrossOver took {end_macd - start_macd:.3f}s")



            # Timing BollingerBandBreakout
            if not result or not isinstance(result, tuple) or len(result) != 6 or result[1] in (None, 'No_Signal'):
                start_boll = time.time()
                result = BollingerBandBreakout(pair_info, check_exists=False)
                end_boll = time.time()
                print(f"[TIMER] {pair} BollingerBandBreakout took {end_boll - start_boll:.3f}s")

            # Timing BBUpLowBand
            if not result or not isinstance(result, tuple) or len(result) != 6 or result[1] in (None, 'No_Signal'):
                if Pl_after_comm > -3:
                    start_bbuplow = time.time()
                    result = BBUpLowBand(pair_info, check_exists=False)
                    end_bbuplow = time.time()
                    print(f"[TIMER] {pair} BBUpLowBand took {end_bbuplow - start_bbuplow:.3f}s")

            if not result or not isinstance(result, tuple) or len(result) != 6 or result[1] in (None, 'No_Signal'):
                signal_data = result[2] if result and len(result) > 2 else None
                with get_lock(analysis_tracker_locks, uid):
                    tracker['signal_data'] = signal_data
                log_event(
                    uid,
                    "SignalEngine_" + str(result[4] if result else "") + "Interval_" + str(result[5] if result else ""),
                    "NO SIGNAL FOUND TO RELEASE HEDGE",
                    Pl_after_comm
                )
                return  # No valid signal from any method

            # Destructure result only if we know it's valid
            df_mainInterval, signal, signal_data, candle_type, signalFrom, interval = result


            candle_time = df_mainInterval.index[-1]
        
            last_5min_check_time[uid] = now
            if signal == 'BUY':
                new_stop_price = find_last_high(df_mainInterval, 'BUY','heiken')
                with get_lock(analysis_tracker_locks, uid):
                    tracker['StopPriceHedge'] = new_stop_price
                    tracker['Decision'] = 'BUY'
                    tracker['Candle_Time'] = candle_time
                    tracker['signal_data'] = signal_data
                # Use the full tracker as json_data for logging
                with get_lock(all_pairs_locks, uid):
                    self.all_pairs[uid]['stop_price'] = new_stop_price
                
                log_event(
                    uid,
                    "SignalEngine_" + str(signalFrom or "")+ "New Hedge Stop Price" + str(new_stop_price) +  "Interval_" + str(interval or ""),
                    "BUY SIGNAL TO RELEASE HEDGE",
                    Pl_after_comm
                )
                from core.check_and_release_hedge import check_and_release_hedge
                check_and_release_hedge(uid, current_price, signal)  # Pass signal to avoid re-checking
            elif signal == 'SELL':
                new_stop_price = find_last_high(df_mainInterval, 'SELL', 'heiken')
                with get_lock(analysis_tracker_locks, uid):
                    tracker['StopPriceHedge'] = new_stop_price
                    tracker['Decision'] = 'SELL'
                    tracker['Candle_Time'] = candle_time
                    tracker['signal_data'] = signal_data
                # Use the full tracker as json_data for logging
                with get_lock(all_pairs_locks, uid):
                    self.all_pairs[uid]['stop_price'] = new_stop_price
                
                log_event(
                    uid,
                    "SignalEngine_" + str(signalFrom or "") + "New Hedge Stop Price" + str(new_stop_price) + "Interval_" + str(interval or ""),
                    "SELL SIGNAL TO RELEASE HEDGE",
                    Pl_after_comm
                )
                from core.check_and_release_hedge import check_and_release_hedge
                check_and_release_hedge(uid, current_price, signal)  # Pass signal to avoid re-checking
        except Exception as e:
            log_error(e, "SignalEngine.run", uid)


# ✅ Compatibility wrapper
def Current_Analysis(all_pairs, current_price, uid):
    from utils.global_store import analysis_tracker
    engine = SignalEngine(all_pairs, analysis_tracker)
    engine.run(uid, current_price)
