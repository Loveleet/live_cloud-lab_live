# core/setup_single_position.py

from utils.global_store import all_pairs, all_pairs_locks
from utils.utils import  get_lock
from utils.logger import log_error

def setup_single_position(uid):
    """
    Resets the pair status to single position mode after hedge exit.

    Args:
        uid (str): Unique ID of the pair
    """
    try:
        if uid in all_pairs:
            # with get_lock(all_pairs_locks, uid):
                action = all_pairs[uid].get("action")
                trade_type = all_pairs[uid].get("type")

                # --- If BUY Position running ---
                if action == 'BUY' and trade_type == 'running':
                    all_pairs[uid].update({
                        "sell_qty": 0,
                        "sell_price": 0,
                        "sell_pl": 0,
                        "hedge_1_1_bool": False,
                        "hedge": False
                    })

                # --- If SELL Position running ---
                elif action == 'SELL' and trade_type == 'running':
                    all_pairs[uid].update({
                        "buy_qty": 0,
                        "buy_price": 0,
                        "buy_pl": 0,
                        "hedge_1_1_bool": False,
                        "hedge": False
                    })

    except Exception as e:
        log_error(e, "setup_single_position", uid)
