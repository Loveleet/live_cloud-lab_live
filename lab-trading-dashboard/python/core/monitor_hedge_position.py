from core.setlastpairPrice import setlastpairPrice
from machine_id import get_machine_id
from utils.logger import  log_error, safe_print,log_event
from utils.global_store import all_pairs_locks, high_and_low_swings
from utils.utils import get_lock, calculate_pnl, calculate_commission
from core.signal_engine import Current_Analysis
from core.swing_utils import get_safe_swing_point, update_swing_dictonary, refresh_swing_points
from FinalVersionTrading_AWS import CalculateSignals
import datetime
# from utils.FinalVersionTradingDB_PostgreSQL import update_single_uid_in_table,getSuperTrendPercent,check_and_deactivate_supertrend           
from utils.Final_olab_database import olab_update_single_uid_in_table



from core.book_profit import ProfitBooker
profit_booker = ProfitBooker(CalculateSignals)


def monitor_hedge_position(uid, current_price):
    """
    Monitors an active hedge trade and updates profit, commissions, and swing points.
    """
    from utils.global_store import all_pairs, analysis_tracker  # Avoid circular imports

    try:
        if current_price is None or current_price <= 0:
            return

        data = all_pairs.get(uid, {})
        if not data.get("hedge", False) or not data:
            return

        buy_qty = float(data.get("buy_qty", 0.0))
        sell_qty = float(data.get("sell_qty", 0.0))
        hedge_1_1 = data.get("hedge_1_1_bool", False)
        pair = data.get("pair")
        stop_price = data.get("stop_price", 0.0)
        action = data.get("action")
        interval = data.get("interval")

        high = data.get("hedge_swing_high_point") or 0
        low = data.get("hedge_swing_low_point") or 0

        # Refresh swing high if far enough or missing
        if high == 0 or (current_price - low) / current_price > 0.005:
            high = get_safe_swing_point(uid, "high", current_price, pair)
            if high is None:
                high = 0
            with get_lock(all_pairs_locks, uid):
                data["hedge_swing_high_point"] = high

        # Refresh swing low if far enough or missing
        if low == 0 or (high - current_price) / current_price > 0.005:
            low = get_safe_swing_point(uid, "low", current_price, pair)
            if low is None:
                low = 0
            with get_lock(all_pairs_locks, uid):
                data["hedge_swing_low_point"] = low

        # Refresh both if price broke out and hedge_1_1 is True
        if (current_price < low or current_price > high) and hedge_1_1:
            refresh_swing_points(uid, current_price, pair)

        # Populate swing dict if needed
        if uid not in high_and_low_swings or not high_and_low_swings[uid]:
            update_swing_dictonary(uid, pair)

        # Buy leg PnL
        buy_price = float(data.get("buy_price", 0))
        if buy_qty > 0 and buy_price > 0:
            buy_pnl = calculate_pnl(buy_price, buy_qty, current_price, 'BUY')
            buy_comm = calculate_commission(buy_price, buy_qty, current_price, buy_qty)
            with get_lock(all_pairs_locks, uid):
                data["buy_pl"] = buy_pnl
                # log_event(uid, "buy_qty > 0 and buy_price > 0", f"Buy_pl {buy_pnl} - stop_Price = {stop_price}", 0)
        else:
            buy_pnl = 0  # Leg closed, do not include in live PnL
            buy_comm = 0

        # Sell leg PnL
        sell_price = float(data.get("sell_price", 0))
        if sell_qty > 0 and sell_price > 0:
            sell_pnl = calculate_pnl(sell_price, sell_qty, current_price, 'SELL')
            sell_comm = calculate_commission(current_price, sell_qty, sell_price, sell_qty)
            with get_lock(all_pairs_locks, uid):
                data["sell_pl"] = sell_pnl
                # log_event(uid, "sell_qty > 0 and sell_price > 0:", f"Sell_pl {sell_pnl} - stop_Price = {stop_price}", 0)
        else:
            sell_pnl = 0  # Leg closed, do not include in live PnL
            sell_comm = 0

        hedge_sell_pl = float(data.get("hedge_sell_pl", 0.0))
        hedge_buy_pl = float(data.get("hedge_buy_pl", 0.0))

        # Only include live PnL for open legs, realized for closed
        total_profit = buy_pnl + sell_pnl + hedge_buy_pl + hedge_sell_pl
        # if buy_qty > 0 and buy_price > 0    :
        #     total_profit += buy_pnl
        #     # log_event(uid, "buy_qty > 0 and buy_price > 0", f"Current Price = {current_price} Buy_pl {buy_pnl} total_profit {total_profit} - stop_Price = {stop_price}", 0)
            
        # else:
        #     total_profit += hedge_buy_pl
        #     # log_event(uid, "total_profit += hedge_buy_pl", f"Current Price = {current_price} Buy_pl {buy_pnl} total_profit {total_profit} - stop_Price = {stop_price}", 0)
        # if sell_qty > 0 and sell_price > 0:
        #     total_profit += sell_pnl
        #     # log_event(uid, "sell_qty > 0 and sell_price > 0", f"Current Price = {current_price} Sell_pl {sell_pnl} total_profit {total_profit} - stop_Price = {stop_price}", 0)
        # else:
        #     total_profit += hedge_sell_pl
        #     # log_event(uid, "total_profit += hedge_sell_pl", f"Current Price = {current_price} Sell_pl {sell_pnl} total_profit {total_profit} - stop_Price = {stop_price}", 0)

        total_comm = buy_comm + sell_comm
        pl_after_comm = total_profit - total_comm

        # Update values in shared dict (with lock)
        with get_lock(all_pairs_locks, uid):
            data["commission"] = total_comm
            data["pl_after_comm"] = pl_after_comm

        # Log for terminal visibility
        safe_print("\n" + "\n".join([
            "=" * 80,
            f"🔍 Hedge Monitoring: {uid}",
            f"    🔹 Buy PNL         : {buy_pnl:.4f}",
            f"    🔹 Sell PNL        : {sell_pnl:.4f}",
            f"    🔸 Total Commission: {total_comm:.4f}",
            f"    🔸 Stop Price: {stop_price:.4f}",
            f"    ✅ PL After Comm.  : {pl_after_comm:.4f}",
            "=" * 80
        ]) + "\n")

        import time
        current_time = time.time()
        machine_id = get_machine_id()
        
        # Global dictionary to track last DB update time per UID
        if not hasattr(monitor_hedge_position, 'uid_db_timestamps'):
            monitor_hedge_position.uid_db_timestamps = {}
        
        # Get last update time for this specific UID
        last_db_update = monitor_hedge_position.uid_db_timestamps.get(uid, 0)
        
        # Determine update interval based on hedge_1_1_bool
        if hedge_1_1:
            update_interval = 3000  # 5 minutes = 300 seconds
        else:
            update_interval = 120   # 30 seconds
        
        # Check if enough time has passed for database update
        if current_time - last_db_update >= update_interval:
            # Direct database update (single update approach)
            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
            
            # Update last database update time for this specific UID
            monitor_hedge_position.uid_db_timestamps[uid] = current_time
            
            safe_print(f"🔄 Database updated: {uid} (hedge_1_1: {hedge_1_1}, interval: {update_interval}s)")

            if not hedge_1_1:
                setlastpairPrice(uid, current_price)

     # Ensure signal is refreshed if not in analysis_tracker
        if uid not in analysis_tracker:
            Current_Analysis(all_pairs, current_price, uid)

    except Exception as e:
        log_error(e, "monitor_hedge_position", uid)
