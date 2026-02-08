# core/setlastpairPrice.py

from datetime import datetime as dt
from machine_id import get_machine_id
# from utils.FinalVersionTradingDB_PostgreSQL_before_duplicate_insert import buy_is_loss_exceeding_5_percent_with_min_trades
# from utils.backtestdb import buy_is_loss_exceeding_5_percent_with_min_trades
from utils.logger import log_error, utc_now
from utils.utils import get_lock
from utils.global_store import (
    last_3min_check_time,
    last_added_invest_check_time,
    analysis_tracker_locks,
    all_pairs_locks,
   
)
from utils.logger import log_event
from FinalVersionTrading_AWS import CalculateSignals
from core.book_profit import ProfitBooker
profit_booker = ProfitBooker(CalculateSignals)
from utils.utils import get_default_analysis_tracker
from datetime import timedelta
from utils.Final_olab_database import sql_helper
from core.deleteFromGlobalList import deleteFromGlobalList


# from utils.FinalVersionTradingDB_PostgreSQL import (
#     buy_is_loss_exceeding_5_percent_with_min_trades,
#     sell_is_loss_exceeding_5_percent_with_min_trades,
#     update_tmux_log, update_single_uid_in_table,
#     getSuperTrend, getSuperTrendPercent, check_and_deactivate_supertrend
# )

from utils.Final_olab_database import ( 
   olab_update_single_uid_in_table,
    olab_buy_is_loss_exceeding_5_percent_with_min_trades, 
    olab_sell_is_loss_exceeding_5_percent_with_min_trades,
    olab_update_active_loss,
    olab_count_running_trades
        
)

from utils import global_store
from utils.global_store import (
    all_pairs,
    analysis_tracker,
    last_3min_check_time,
    last_added_invest_check_time,
    analysis_tracker_locks,
    all_pairs_locks,
)

def next_15m_boundary(dt):
    dt = dt.replace(second=0, microsecond=0)
    minutes_to_add = 15 - (dt.minute % 15)
    if minutes_to_add == 0:
        minutes_to_add = 15
    return dt + timedelta(minutes=minutes_to_add)

def setlastpairPrice(uid, current_price):
    """
    Monitors the last closed candle and updates stop/save price if breakout or confirmation conditions are met.
    Meant for single-leg trades, called within each worker loop.
    """
    try:
        # ------- load snapshot under lock -------
        now = utc_now()
        with get_lock(all_pairs_locks, uid):
            if uid not in all_pairs:
                # log_error(f"UID {uid} not found in all_pairs", "setlastpairPrice", uid)
                return
            pair            = all_pairs[uid].get("pair")
            interval        = all_pairs[uid].get("interval")
            Pl_after_comm   = float(all_pairs[uid].get("pl_after_comm", 0.0))
            min_profit = float(all_pairs[uid].get("min_profit", 20))
            min_close = all_pairs[uid].get("min_close")
            stop_price      = all_pairs[uid].get("stop_price")
            action          = all_pairs[uid].get("action")
            profit_journey  = all_pairs[uid].get("profit_journey", False)
            commision_journey = all_pairs[uid].get("commision_journey", False)
            signalFrom      = all_pairs[uid].get("signalfrom")
            macd_action          = all_pairs[uid].get("macd_action")
            invest_updated_time = all_pairs[uid].get("updated_at")  # In-memory value (may be stale)
            trade_type = all_pairs[uid].get("type")
            hedge = int(all_pairs[uid].get("hedge", 0))

            invest = float(all_pairs[uid].get("investment", 0.0))
            buy_price = float(all_pairs[uid].get("buy_price", 0.0))
            sell_price = float(all_pairs[uid].get("sell_price", 0.0))
            close_price = float(all_pairs[uid].get("close_price", 0.0))

            machine_id = get_machine_id()
            
            # Fetch updated_at directly from database to get the actual value
            db_updated_at = None
            try:
                query = f"SELECT updated_at FROM {machine_id.lower()} WHERE unique_id = :uid"
                result = sql_helper.fetch_one(query, {"uid": uid})
                if result and result[0] is not None:
                    db_updated_at = result[0]
            except Exception as e:
                log_error(e, "setlastpairPrice - fetch updated_at from DB", uid)
                db_updated_at = None
            
            # Use database value as source of truth, fallback to in-memory if DB query fails
            invest_updated_time = db_updated_at if db_updated_at is not None else invest_updated_time

         


        # default stop to current price if empty
        if stop_price is None and current_price is not None:
            stop_price = float(current_price)

        # ------- throttle -------
        
        if uid not in last_3min_check_time:
            last_3min_check_time[uid] = now

        # Note: We'll sync last_added_invest_check_time with database value later in the code
        # This initialization is kept for backward compatibility but will be overridden


        seconds = 120
       
        if analysis_tracker.get(uid, {}).get('SinglePostionWarning'):
            seconds = 60

        last_check = last_3min_check_time.get(uid)
        if last_check and (now - last_check).total_seconds() < seconds:
            return  # ⏳ Too soon to re-check

        
       
        last_3min_check_time[uid] = now  # ✅ mark timestamp

        # ------- ensure analysis_tracker scaffold -------
        if uid not in analysis_tracker:
            analysis_tracker[uid] = get_default_analysis_tracker()

        # SuperTrend active loss: set from DB when loss exceeds threshold; clear when running count is low
        # Coerce to bool so string "False"/0/None from DB are falsy; only True, "true", "1", 1 are truthy
        _b = global_store.buy_active_loss
        _s = global_store.sell_active_loss
        buy_active_loss = _b is True or (isinstance(_b, str) and _b.strip().lower() in ('true', '1'))
        sell_active_loss = _s is True or (isinstance(_s, str) and _s.strip().lower() in ('true', '1'))

        print(f'buy_active_loss = {buy_active_loss}')
        print(f'sell_active_loss = {sell_active_loss}')

        if not buy_active_loss:
            if olab_buy_is_loss_exceeding_5_percent_with_min_trades():
                global_store.buy_active_loss = True
                olab_update_active_loss('BUY', True)
                log_event(uid, "setlastpairPrice", f"Buy SuperTrend Active Loss set to True", Pl_after_comm)

        if not sell_active_loss:
            print('ssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss')
            if olab_sell_is_loss_exceeding_5_percent_with_min_trades():
                print('rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr')
                global_store.sell_active_loss = True
                olab_update_active_loss('SELL', True)
                log_event(uid, "setlastpairPrice", f"Sell SuperTrend Active Loss set to True", Pl_after_comm)

        if global_store.buy_active_loss:
            if olab_count_running_trades('BUY') < 15:
                global_store.buy_active_loss = False
                olab_update_active_loss('BUY', False)
                log_event(uid, "setlastpairPrice", f"Buy SuperTrend Active Loss set to False", Pl_after_comm)

        if global_store.sell_active_loss:
            if olab_count_running_trades('SELL') < 15:
                global_store.sell_active_loss = False
                olab_update_active_loss('SELL',False)   
                log_event(uid, "setlastpairPrice", f"Sell SuperTrend Active Loss set to False", Pl_after_comm)


        if macd_action == 'Active' and action == 'BUY' and global_store.buy_active_loss:
            with get_lock(all_pairs_locks, uid):                    
                all_pairs[uid]["macd_action"] = 'FollowTrend'	
                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                log_event(uid, "setlastpairPrice",
                    f"macd_action change from Active to FollowTrend and min_close didnot change from NOT_ACTIVE to ACTIVE",
                    Pl_after_comm)
                
        if macd_action == 'Active' and  action == 'SELL' and global_store.sell_active_loss:
            with get_lock(all_pairs_locks, uid):                    
                all_pairs[uid]["macd_action"] = 'FollowTrend'	
                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                log_event(uid, "setlastpairPrice",
                    f"macd_action change from Active to FollowTrend and min_close didnot change from NOT_ACTIVE to ACTIVE",
                    Pl_after_comm)


        if (signalFrom == 'Spike' or signalFrom == 'ProGap' or signalFrom == 'Kicker') and macd_action == 'Active' and trade_type == 'running' and Pl_after_comm > 5:
             with get_lock(all_pairs_locks, uid):                    
                all_pairs[uid]["macd_action"] = 'FollowTrend'	
                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                log_event(uid, "setlastpairPrice",
                    f"macd_action change from Active to FollowTrend and min_close didnot change from NOT_ACTIVE to ACTIVE For PROGAP AND SPIKE",
                    Pl_after_comm)


        if trade_type == 'hedge_close' or trade_type == 'hedge_hold' and hedge == 0: 

            result_chk_trade, reason = profit_booker.CheckForNewTrade(pair, action,Pl_after_comm,invest,buy_price,sell_price,close_price,current_price,trade_type)
            if result_chk_trade == 'close_now':
                if trade_type == 'hedge_close' :
                    with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                "type": 'close'                             
                            })
                    olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    deleteFromGlobalList(uid)
                    log_event(uid, "setlastpairPrice", f"update from hedge_close/hedge_hold - {reason}", 0)
                    return
                
                elif trade_type == 'hedge_hold' :
                    with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                 "hedge_1_1_bool": True,
                                 "hedge": True,                             
                            })
                    olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    deleteFromGlobalList(uid)
                    log_event(uid, "setlastpairPrice", f"update from hedge_close/hedge_hold - {reason}", 0)
                    return

            elif result_chk_trade == 'close_now_new_trade':
                if trade_type == 'hedge_close' :
                    with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                "type": 'close'                             
                            })
                    olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    deleteFromGlobalList(uid)
                    log_event(uid, "setlastpairPrice", f"update from hedge_close/hedge_hold - {reason}", 0)
                    return
                
                elif trade_type == 'hedge_hold' :
                    with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                 "hedge_1_1_bool": True,
                                 "hedge": True,                             
                            })
                    olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    deleteFromGlobalList(uid)
                    log_event(uid, "setlastpairPrice", f"update from hedge_close/hedge_hold - {reason}", 0)
                    return
                
        if trade_type !='running' :
            print(f'{uid}trade type is not running anymore')
            return

        # Use database value as source of truth (invest_updated_time loaded at line 63)
        # The in-memory all_pairs might be out of sync with database
        # Only use all_pairs value if it's more recent than database value (updated in this session)
        with get_lock(all_pairs_locks, uid):
            current_updated_at = all_pairs[uid].get("updated_at")
        
        # Prefer database value as source of truth, but use all_pairs if it's clearly more recent
        # (meaning it was updated in this session after loading from DB)
        if current_updated_at is not None and invest_updated_time is not None:
            # Use the more recent one, but only if all_pairs is significantly newer (within last hour)
            # This handles the case where all_pairs was updated in this session
            if current_updated_at > invest_updated_time:
                time_diff = (current_updated_at - invest_updated_time).total_seconds() / 60
                if time_diff < 60:  # Only trust all_pairs if updated within last hour (same session)
                    last_add_invest_time = current_updated_at
                else:
                    # all_pairs is too far ahead, likely stale - use database
                    last_add_invest_time = invest_updated_time
            else:
                # Database is more recent or equal - use database
                last_add_invest_time = invest_updated_time
        else:
            # Use whichever is available
            last_add_invest_time = current_updated_at if current_updated_at is not None else invest_updated_time
        
        # Sync in-memory value for consistency
        last_added_invest_check_time[uid] = last_add_invest_time
        
        # print(uid, "setlastpairPrice", f" last_add_invest_time = {last_add_invest_time} | from all_pairs: {current_updated_at} | from DB direct query: {invest_updated_time}", Pl_after_comm)
        
        # Check if 30 minutes have passed since last investment was added
        should_check = False
        if last_add_invest_time is None:
            # First time - no previous investment, allow check
            should_check = True
         #   print(uid, "setlastpairPrice", f" First time check - no previous investment added")
        else:
            time_diff_minutes = (now - last_add_invest_time).total_seconds() / 60  # minutes
            #print(uid, "setlastpairPrice", f" now = {now}, time_diff = {time_diff_minutes:.2f} minutes since last investment")
            if time_diff_minutes >= 30:
                should_check = True
               # print(uid, "setlastpairPrice", f" 30+ minutes have passed - allowing check")
            else:
                print(uid, "setlastpairPrice", f" Only {time_diff_minutes:.2f} minutes passed, need {30 - time_diff_minutes:.2f} more minutes")

        #if Pl_after_comm > 5 : ##here we need to add he 15m delay after
        old_added_qty = float(all_pairs[uid].get("added_qty", 0.0))
        old_invest = float(all_pairs[uid].get("investment", 0.0))

        

        if should_check:
            # Only add investment if profit_journey is True
            # Reload profit_journey from all_pairs to get latest value
            with get_lock(all_pairs_locks, uid):
                current_profit_journey = all_pairs[uid].get("profit_journey", False)
            
            if not current_profit_journey:
                print(uid, "setlastpairPrice", f" Skipping investment check - profit_journey is False", Pl_after_comm)
            else:
                print('I am going to check to add the investment now')

                if profit_booker.check_for_add_investment( pair, action):

                    added_invest =2000             
                    new_quantity = added_invest /current_price

                    if action == 'BUY':    
                        old_quantity = all_pairs[uid].get("buy_qty")
                        old_buy_price = float(all_pairs[uid].get("buy_price", 0.0))
                        
                        
                        invest = old_invest + added_invest
                        quantity = old_quantity + new_quantity
                        entry_price = invest / quantity

                        with get_lock(all_pairs_locks, uid):                        
                            
                            all_pairs[uid]["buy_qty"] = quantity
                            all_pairs[uid]["investment"] = invest
                            all_pairs[uid]["buy_price"] = entry_price
                            all_pairs[uid]["added_qty"] = new_quantity + old_added_qty

                            # Update time AFTER investment is successfully added
                            all_pairs[uid]["updated_at"] = now
                            last_added_invest_check_time[uid] = now

                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                            log_event(uid, "ADD_QTY",
                            f"added quantity = {new_quantity}, new buyprice = {entry_price}, old quantity = {old_quantity}, old buyprice = {old_buy_price}, old invest = {old_invest}, new invest= {added_invest}, total_investment= {invest} , add_q_price= {current_price}",
                                Pl_after_comm)

                    elif action == 'SELL':    

                        old_quantity = all_pairs[uid].get("sell_qty")
                        old_sellprice = float(all_pairs[uid].get("sell_price", 0.0))
                        old_added_qty = float(all_pairs[uid].get("added_qty", 0.0))
                        
                        invest = old_invest + added_invest
                        quantity = old_quantity + new_quantity
                        entry_price = invest / quantity

                        with get_lock(all_pairs_locks, uid):
                            
                            all_pairs[uid]["sell_qty"] = quantity
                            all_pairs[uid]["investment"] = invest
                            all_pairs[uid]["sell_price"] = entry_price
                            all_pairs[uid]["added_qty"] = new_quantity + old_added_qty

                            # Update time AFTER investment is successfully added
                            all_pairs[uid]["updated_at"] = now
                            last_added_invest_check_time[uid] = now

                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                            log_event(uid, "setlastpairPrice",
                                f"added quantity = {new_quantity}, new sellprice = {entry_price}, old quantity = {old_quantity}, old sellprice = {old_sellprice}, old invest = {old_invest}, new invest= {added_invest}, total_investment= {invest} , add_q_price= {current_price}",
                                Pl_after_comm)




        if Pl_after_comm < min_profit and min_close == 'NOT_ACTIVE' and   macd_action == 'Active':
            print(uid, "setlastpairPrice", f"Pl_after_comm is < minprofit {min_profit}")
            log_event(uid, "setlastpairPrice", f"Pl_after_comm is < minprofit {min_profit}", Pl_after_comm)
            return
        
        if Pl_after_comm > min_profit or macd_action == 'FollowTrend' :

            if macd_action == 'Active':
                with get_lock(all_pairs_locks, uid):                    
                    all_pairs[uid]["macd_action"] = 'FollowTrend'
                    all_pairs[uid]["min_close"] = 'ACTIVE'
                    olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    log_event(uid, "setlastpairPrice",
                    f"macd_action change from Active to FollowTrend and min_close change from NOT_ACTIVE to ACTIVE",
                    Pl_after_comm)
                    


            output, result = profit_booker.FollowTrend(pair, action, interval,current_price,Pl_after_comm)

            if output == 'volatility_detected' :
            # if output == 'volatility_detected' and Pl_after_comm > 0:

                log_event(uid, "setlastpairPrice",
                        f"Volatile Detected -- Current Price = {current_price}",
                        Pl_after_comm)

            #     if action == 'BUY' and current_price > stop_price:
            #         new_stop_price = current_price - (current_price * 0.004)  # 0.6% lower
            #         if new_stop_price> stop_price:
            #             with get_lock(all_pairs_locks, uid):
            #                 all_pairs[uid]["stop_price"] = new_stop_price
            #                 olab_update_single_uid_in_table(uid, all_pairs, machine_id)
            #                 log_event(uid, "setlastpairPrice", f"High Volatility detected. Buy Position -old_stop_price = {stop_price} - new_stop_price = {new_stop_price} ", Pl_after_comm)
            #     elif action == 'SELL' and current_price < stop_price:
            #         new_stop_price = current_price + (current_price * 0.004)  # 0.6% higher
            #         if new_stop_price < stop_price:
            #             with get_lock(all_pairs_locks, uid):
            #                 all_pairs[uid]["stop_price"] = new_stop_price
            #                 olab_update_single_uid_in_table(uid, all_pairs, machine_id)       
            #                 log_event(uid, "setlastpairPrice", f"High Volatility detected. Sell Position -old_stop_price = {stop_price} - new_stop_price = {new_stop_price} ", Pl_after_comm)                 

                

             # ------- process FollowTrend outputs -------

            

            if output == 'update_interval':
                new_interval = (str(result).strip().lower() if result is not None else None)
                if new_interval and new_interval != interval:
                    with get_lock(all_pairs_locks, uid):
                        old_interval = all_pairs[uid].get("interval")
                        if old_interval != new_interval:
                            all_pairs[uid]["interval"] = new_interval
                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    log_event(uid, "setlastpairPrice",
                              f"FollowTrend updated interval from {interval} to {new_interval}",
                              Pl_after_comm)

            # elif output == 'exit_trade' and Pl_after_comm > 0:
            elif output == 'exit_trade' :
                if current_price is not None:
                    with get_lock(all_pairs_locks, uid):
                        old_stop = all_pairs[uid].get("stop_price")
                        all_pairs[uid]["stop_price"] = float(current_price)
                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                    log_event(uid, "setlastpairPrice",
                              f"FollowTrend signaled exit_trade, updated stop price from {old_stop} to currentPrice = {current_price}",
                              Pl_after_comm)

            elif output == 'update_stop_price' and Pl_after_comm > 0:  # <-- keep this EXACT string consistent with FollowTrend
                if result is not None:
                    new_stop_price = float(result)
                    
                    if new_stop_price> stop_price and action == 'BUY':
                        with get_lock(all_pairs_locks, uid):
                            old_stop = all_pairs[uid].get("stop_price")
                            all_pairs[uid]["stop_price"] = new_stop_price
                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        log_event(uid, "setlastpairPrice",
                                f"FollowTrend updated stop_price for BUY from {old_stop} to {new_stop_price}",
                                Pl_after_comm)
                        
                    elif new_stop_price < stop_price and action == 'SELL':
                        with get_lock(all_pairs_locks, uid):
                            old_stop = all_pairs[uid].get("stop_price")
                            all_pairs[uid]["stop_price"] = new_stop_price
                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        log_event(uid, "setlastpairPrice",
                                f"FollowTrend updated stop_price for SELL from {old_stop} to {new_stop_price}",
                                Pl_after_comm)             
                        
            elif output == 'update_stop_price_rsi':
                if action == 'BUY' and current_price > stop_price:
                    new_stop_price = current_price - (current_price * 0.002)  # 0.6% lower
                    if new_stop_price> stop_price:
                        with get_lock(all_pairs_locks, uid):
                            all_pairs[uid]["stop_price"] = new_stop_price
                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                            log_event(uid, "setlastpairPrice", f"RSI ABOVE 90. Buy Position -old_stop_price = {stop_price} - new_stop_price = {new_stop_price} ", Pl_after_comm)
                elif action == 'SELL' and current_price < stop_price:
                    new_stop_price = current_price + (current_price * 0.002)  # 0.6% higher
                    if new_stop_price < stop_price:
                        with get_lock(all_pairs_locks, uid):
                            all_pairs[uid]["stop_price"] = new_stop_price
                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)       
                            log_event(uid, "setlastpairPrice", f"RSI BELOW 10. Sell Position -old_stop_price = {stop_price} - new_stop_price = {new_stop_price} ", Pl_after_comm)                 

        
        
       # loop info
        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
        log_event(uid, "setlastpairPrice", f"Loop in {seconds/60:.1f} minutes", Pl_after_comm)
        print(uid, "setlastpairPrice", f"Loop in {seconds/60:.1f} minutes", Pl_after_comm)

    except Exception as e:
        log_error(e, "setlastpairPrice", uid)
