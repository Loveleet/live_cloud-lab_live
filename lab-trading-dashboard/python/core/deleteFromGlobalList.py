# core/deleteFromGlobalList.py

from utils.global_store import (
    all_pairs,
    analysis_tracker,
    high_and_low_swings,
    swing_proximity_flags_hedge_close,
    swing_proximity_flags_hedge_release,
    last_3min_check_time,
    active_threads,
    all_pairs_locks,
    analysis_tracker_locks,
    message_queues
)
from utils.logger import log_error, safe_print
from utils.utils import get_lock


def deleteFromGlobalList(uid):
    try:
        with get_lock(all_pairs_locks, uid):
            if uid in all_pairs:
                del all_pairs[uid]

        with get_lock(analysis_tracker_locks, uid):
            if uid in analysis_tracker:
                del analysis_tracker[uid]

        if uid in active_threads:
            del active_threads[uid]

        if uid in last_3min_check_time:
            del last_3min_check_time[uid]

        if uid in high_and_low_swings:
            del high_and_low_swings[uid]

        if uid in swing_proximity_flags_hedge_release:
            del swing_proximity_flags_hedge_release[uid]

        if uid in swing_proximity_flags_hedge_close:
            del swing_proximity_flags_hedge_close[uid]

        if uid in message_queues:
            del message_queues[uid]

        safe_print(f"\n🧹 UID {uid} → all global memory deleted.\n")

    except Exception as e:
        log_error(e, "deleteFromGlobalList", uid)