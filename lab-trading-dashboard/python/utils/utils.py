import threading
from utils.global_store import  analysis_tracker_locks,analysis_tracker
from utils.Final_olab_database import olab_fetch_single_pair_from_db
# from FinalVersionTrading_AWS import process_candle_patterns_for_symbol
import time
from utils.global_store import last_update_time_signal_data
from utils.logger import log_event


interval_seconds = 300

def calculate_commission(entry_price, qty_entry, exit_price, qty_exit):
    try:
        amount = abs(entry_price * qty_entry) + abs(exit_price * qty_exit)
        return amount * 0.001
    except:
        return 0


def calculate_pnl(entry_price, qty, current_price, direction):
    try:
        if direction == 'BUY':
            return (current_price - entry_price) * qty
        else:
            return (entry_price - current_price) * qty
    except:
        return 0


def get_lock(lock_dict, uid):
    """Return thread-safe lock for UID."""
    if uid not in lock_dict:
        lock_dict[uid] = threading.Lock()
    return lock_dict[uid]

# utils/global_store.py or utils/utils.py

def get_default_analysis_tracker():
    return {       
        'SinglePostionDecision': None,  # core/setlastpairPrice.py (set)
        'SinglePostionWarning': False,  # core/setlastpairPrice.py (set/get)
        'Buy_Activate_loss_5_percent': False,  # core/setlastpairPrice.py (set/get)
        'Sell_Activate_loss_5_percent': False,  # core/setlastpairPrice.py (set/get)
        '1min_Check_IMACD': False,  # core/setlastpairPrice.py (set/get)
        'Current_Price': 0,  # core/ws_handler.py (set/get), core/signal_engine.py (set)
        'StopPriceHedge': None,  # core/signal_engine.py (set)
        'Candle_Time': None,  # core/signal_engine.py (set)
        'signal_data': None,  # core/signal_engine.py (set)
        # The following are accessed via .get in check_and_release_hedge
        'Candle_High': None,  # core/check_and_release_hedge.py (get)
        'Candle_Low': None,  # core/check_and_release_hedge.py (get)
        'Decision': None,  # core/check_and_release_hedge.py (get/set), core/setlastpairPrice.py (get), core/signal_engine.py (set)
		'SuperTrend' : False
    }


def get_and_update_signal_data_for_uid(symbol, uid,unrealized_profit,monitorFrom):
    """
    Fetches the latest signal context for a symbol from the PairStatus table,
    runs process_candle_patterns_for_symbol(symbol, '15m', 'heiken'),
    and updates analysis_tracker[uid]['signal_data'] with the result, using a lock for thread safety.
    """

    now = time.time()
    last_update = last_update_time_signal_data.get(uid, 0)
    if now - last_update < interval_seconds:
        return

    last_update_time_signal_data[uid] = now
    # 1. Get context from DB
    pair_info = olab_fetch_single_pair_from_db(symbol)
    context = {
        'active_squeeze_trend': None,
        'overall_trend_RC': None,
        'overall_trend_percentage_RC': None,
        'overall_trend_HC': None,
        'overall_trend_percentage_HC': None
    }
    if pair_info:
        context.update({
            'active_squeeze_trend': pair_info.get('active_squeeze_trend'),
            'overall_trend_RC': pair_info.get('overall_trend_RC'),
            'overall_trend_percentage_RC': pair_info.get('overall_trend_percentage_RC'),
            'overall_trend_HC': pair_info.get('overall_trend_HC'),
            'overall_trend_percentage_HC': pair_info.get('overall_trend_percentage_HC')
        })

    # # 2. Get latest candle analysis
    # results = process_candle_patterns_for_symbol(symbol, '15m', 'heiken')
    # # 3. Build signal_data and update analysis_tracker[uid]['signal_data'] with lock
    # for candle, (dfs, all_last_rows) in results.items():
    #     signal_data = {
    #         'active_squeeze_trend': context['active_squeeze_trend'],
    #         'overall_trend_RC': context['overall_trend_RC'],
    #         'overall_trend_percentage_RC': context['overall_trend_percentage_RC'],
    #         'overall_trend_HC': context['overall_trend_HC'],
    #         'overall_trend_percentage_HC': context['overall_trend_percentage_HC'],
    #         'all_last_rows': {k: v for k, v in all_last_rows.items() if k != 'df'}
    #     }
    #     with get_lock(analysis_tracker_locks, uid):
    #         if uid in analysis_tracker:
    #             analysis_tracker[uid]['signal_data'] = signal_data
    #             log_event(uid, monitorFrom, monitorFrom, unrealized_profit)
      

