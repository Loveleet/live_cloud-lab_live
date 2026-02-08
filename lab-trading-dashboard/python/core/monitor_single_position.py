# core/monitor_single_position.py
from utils.logger import  log_error, safe_print
from utils.utils import get_lock
from utils.global_store import all_pairs_locks
from utils.utils import calculate_pnl, calculate_commission
from utils.utils import get_and_update_signal_data_for_uid



def monitor_single_position(uid, current_price):
    """
    Monitors an active single position (BUY or SELL) and updates
    profit/loss, commission, and flags like Profit journey / Commission journey.
    """
    from utils.global_store import all_pairs  # dynamic import to avoid circular ref

    try:
        if current_price is None or current_price <= 0:
            return

        pair_data = all_pairs.get(uid, {})
        pair = pair_data.get("pair")
        hedge = pair_data.get("hedge", False)
        action = pair_data.get("action")
        save_price = pair_data.get("save_price")
        stop_price = pair_data.get("stop_price")
        buy_qty = float(pair_data.get("buy_qty", 0.0))
        sell_qty = float(pair_data.get("sell_qty", 0.0))

        swing1 = float(pair_data.get("swing1", 0.0))
        swing2 = float(pair_data.get("swing2", 0.0))
        swing3 = float(pair_data.get("swing3", 0.0))
        commision_journey = all_pairs[uid].get("commision_journey", False)
 

        unrealized_profit = 0
        commission = 0
        desired_profit =0.8


        # --- BUY Position ---
        if not hedge and buy_qty > 0:
            order_price = float(pair_data["buy_price"])
            unrealized_profit = calculate_pnl(order_price, buy_qty, current_price, 'BUY')
            commission = calculate_commission(order_price, buy_qty, current_price, buy_qty)
            total_profit = unrealized_profit - commission

            with get_lock(all_pairs_locks, uid):
                if (current_price > swing1 and total_profit > 3) or total_profit > 3:
                    if not commision_journey:
                        new_stop_price = order_price + (desired_profit / buy_qty)
                        # pair_data["stop_price"] = new_stop_price
                    pair_data["commision_journey"] = True

                if (current_price > swing2 and total_profit > 5) or total_profit > 5:
                    pair_data["profit_journey"] = True
                    pair_data["commision_journey"] = True

                pair_data["min_comm"] = order_price + (commission / buy_qty)
                pair_data["buy_pl"] = unrealized_profit
                pair_data["commission"] = commission
                pair_data["pl_after_comm"] = total_profit

        # --- SELL Position ---
        elif not hedge and sell_qty > 0:
            order_price = float(pair_data["sell_price"])
            unrealized_profit = calculate_pnl(order_price, sell_qty, current_price, 'SELL')
            commission = calculate_commission(current_price, sell_qty, order_price, sell_qty)
            total_profit = unrealized_profit - commission

            with get_lock(all_pairs_locks, uid):
                if (current_price < swing1 and total_profit > 3) or total_profit > 3:
                    if not commision_journey:
                        new_stop_price = order_price - (desired_profit / sell_qty)
                        # pair_data["stop_price"] = new_stop_price
                    
                    pair_data["commision_journey"] = True
                if (current_price < swing2 and total_profit > 5) or total_profit > 5:
                    pair_data["profit_journey"] = True
                    pair_data["commision_journey"] = True

                pair_data["min_comm"] = order_price - (commission / sell_qty)
                pair_data["sell_pl"] = unrealized_profit
                pair_data["commission"] = commission
                pair_data["pl_after_comm"] = total_profit

        # ✅ Optional console debug
        lines = [
            "=" * 80,
            f"🔍 ******************** Single Position Monitoring: {uid} ********************",
            f"    🔹 Action            : {action}",
            f"    🔸 Total Commission  : {commission:.4f}",
            f"    ✅ PL After Comm.    : {unrealized_profit:.4f}",
            f"    🔹 Current Price     : {current_price:.4f}",
            f"    🔹 Stop Price         : {stop_price:.4f}",
            
            "=" * 80
        ]
        # safe_print("\n" + "\n".join(lines) + "\n")
        # get_and_update_signal_data_for_uid(pair, uid,unrealized_profit,"monitor_single_position")


            

    except Exception as e:
        log_error(e, "monitor_single_position", uid)
