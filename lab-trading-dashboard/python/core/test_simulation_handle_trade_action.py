# core/test_simulation_handle_trade_action.py

from datetime import datetime as dt, timezone
from utils.logger import log_error
from utils.global_store import (
    all_pairs_locks,
    analysis_tracker_locks,
    analysis_tracker,
    high_and_low_swings,
    all_pairs
)
from FinalVersionTrading_AWS import  CalculateSignalsForConfirmation,calculate_all_indicators_optimized
from utils.utils import get_lock
from utils.logger import log_event  # used if you want extra info logs
from utils.Final_olab_database import olab_update_single_uid_in_table, olab_update_tmux_log
from core.signal_engine import Current_Analysis
from core.deleteFromGlobalList import deleteFromGlobalList
from machine_id import get_machine_id
from utils.utils import get_default_analysis_tracker
from core.monitor_single_position import monitor_single_position




def test_simulation_handle_trade_action(uid, current_price):
    """
    Handles final exit or initial hedge placement for single-leg running trades.
    """
    try:
      #  print(f"🧐 Seperate Thread Started for Trade Simulation: {uid}")
        time_now = dt.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        details = all_pairs.get(uid)
        if not details:
            # This can happen when the function is called multiple times for the same UID
            # after it has already been processed and removed from all_pairs
            # This is not necessarily an error, just a race condition
            # log_error(Exception("UID not in all_pairs"), "test_simulation_handle_trade_action", uid)
            return
                      # Check if current_price is valid before making comparisons
        if current_price is None or current_price <= 0:
            # log_error(Exception(f"Invalid current_price: {current_price}"), "test_simulation_handle_trade_action.hedge_1_1", uid)
            return

        hedge = details.get("hedge", False)
        hedge_1_1 = details.get("hedge_1_1_bool", False)
        action = details.get("action")
        stop_price = details.get("stop_price", 0)
        hedge_order_size = details.get("hedge_order_size", 0)
        Pl_after_comm = details.get("pl_after_comm", 0)
        pair = details.get("pair")

        min_profit = details.get("min_profit",20)
        min_close = details.get("min_close")   
        macd_action = details.get("macd_action")
        signalFrom = details.get("signalfrom")

        

        
        
        # Flag to track if database update is needed
        needs_db_update = False

        # Safe signal read
        signal_decision = None
        try:
            with get_lock(analysis_tracker_locks, uid):
                if uid not in analysis_tracker:
                    analysis_tracker[uid] = get_default_analysis_tracker()
                    Current_Analysis(all_pairs, current_price, uid)
                signal_decision = analysis_tracker[uid].get("SinglePostionDecision")
        except Exception as e:
            log_error(e, "test_simulation_handle_trade_action.signal_decision", uid)

        # 🟢 Entry to hedge logic
        if not hedge and not hedge_1_1:
            monitor_single_position(uid, current_price)
            olab_update_tmux_log('BotMain')
            if action == 'BUY':
                # ❌ LOSS → Hedge SELL
                # if ((current_price < stop_price or signal_decision == 'SELL') and
                # if ((current_price < stop_price and Pl_after_comm < 0 ) or
                #         Pl_after_comm < -60 and current_price > 0):.

                if( 
                ((current_price < stop_price and Pl_after_comm < 0 ) or
                        Pl_after_comm < -60) and current_price > 0 
                        and
                        (macd_action == 'Active' 
                        #  or
                        #      (
                        #          macd_action == 'FollowTrend' and
                        #          (signalFrom == 'ProGap' or signalFrom=='Spike')
                        #      )
                            )
                ):
                    try:
                        with get_lock(all_pairs_locks, uid):
                            details = all_pairs.get(uid)
                            if details is not None and not details.get("hedge") and not details.get("hedge_1_1_bool"):
                                all_pairs[uid].update({
                                    "sell_price": current_price,
                                    "sell_qty": hedge_order_size,
                                    "hedge_1_1_bool": True,
                                    "hedge": True,
                                    "hedge_order_size": hedge_order_size,
                                    "type": 'hedge_hold',
                                    "operator_close_time": time_now
                                })
                                with get_lock(analysis_tracker_locks, uid):
                                    analysis_tracker[uid].update({
                                        'StopPriceHedge': 0,
                                        'SinglePostionDecision': None,
                                        'SinglePostionWarning': False,
                                        'NeedsDBUpdate': True,
                                        'NeedsSwingUpdate': True
                                    })
                                log_event(uid, "test_simulation_handle_trade_action", f"Initial Hedge SELL placed at {current_price}", Pl_after_comm)
                                # Immediate database update BEFORE deleteFromGlobalList
                                machine_id = get_machine_id()
                                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                                deleteFromGlobalList(uid)
                    except Exception as e:
                        log_error(e, "test_simulation_handle_trade_action.hedge_BUY", uid)


                elif( 
                (current_price < stop_price and Pl_after_comm < 0 ) and 
                current_price > 0 
                        and
                        macd_action == 'FollowTrend'
                ):
                    try:
                        with get_lock(all_pairs_locks, uid):
                            details = all_pairs.get(uid)
                            if details is not None and not details.get("hedge") and not details.get("hedge_1_1_bool"):
                                all_pairs[uid].update({
                                    "sell_price": current_price,
                                    "sell_qty": hedge_order_size,						
                                    "type": 'hedge_hold',
                                    "operator_close_time": time_now
                                })
                                
                                log_event(uid, "test_simulation_handle_trade_action", f"HEDGE HOLD at {current_price}", Pl_after_comm)
                                # Immediate database update BEFORE deleteFromGlobalList
                                machine_id = get_machine_id()
                                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                                
                    except Exception as e:
                        log_error(e, "test_simulation_handle_trade_action.hedge_BUY", uid)

# 1. if the profit < min_profit or close in loss and followtrend is true then set "type": 'hedge_close'.capitalize
# 2. if hedge_close then need to check frm setlastprice.py for new entry again.else
# 3. if entry found. place order again. and invest has to be same as the preious hedge_close invest.
# 4. if get the opposite signal for the crossover OB_SIGNAL then 


# change hedge_close to normal close.
# 4. Also need to change the database to get the hedge_close data.

# 5. check re-trade macd_rsi or cci blue cross and cci exit
# 6. not the heddge_close price and if macdrsi and lue cross doesnot match but the price goes bleow the last hedge close price
# then we will execute the trade  but we need to see if the cci is in same direction.

                # ✅ PROFIT → Close
                # elif (signal_decision == 'SELL' or current_price < stop_price) and Pl_after_comm > min_profit and current_price > 0:
                elif (current_price < stop_price) and (Pl_after_comm > min_profit or min_close == 'ACTIVE') and current_price > 0:
                    try:
                        with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                "type": 'close',
                                "close_price": current_price,
                                "operator_close_time": time_now
                            })
                        with get_lock(analysis_tracker_locks, uid):
                            analysis_tracker[uid].update({
                                'SinglePostionDecision': None,
                                'SinglePostionWarning': False
                            })
                        log_event(uid, "test_simulation_handle_trade_action", f"Closed BUY trade with profit at {current_price}", Pl_after_comm)
                        # Immediate database update BEFORE deleteFromGlobalList
                        machine_id = get_machine_id()
                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        deleteFromGlobalList(uid)
                    except Exception as e:
                        log_error(e, "test_simulation_handle_trade_action.close_BUY", uid)

                elif (
                    current_price < stop_price and 
                    Pl_after_comm > 0 and 
                    min_close == 'NOT_ACTIVE' and 
                    current_price > 0):
                    try:
                        with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                "type": 'hedge_close',
                                "close_price": current_price,
                                "operator_close_time": time_now
                            })
                        
                        log_event(uid, "test_simulation_handle_trade_action", f"Hedge Closed BUY trade with profit at {current_price}", Pl_after_comm)
                        # Immediate database update BEFORE deleteFromGlobalList
                        machine_id = get_machine_id()
                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        
                    except Exception as e:
                        log_error(e, "test_simulation_handle_trade_action.close_BUY", uid)                        

            elif action == 'SELL':
                # ❌ LOSS → Hedge BUY
                # if ((current_price > stop_price or signal_decision == 'BUY') and
                # if ((current_price > stop_price and Pl_after_comm < 0 ) or
                #         Pl_after_comm < -60 and current_price > 0):
                if( 
                    ((current_price > stop_price and Pl_after_comm < 0 ) or
                            Pl_after_comm < -60) and current_price > 0 
                            and
                            (macd_action == 'Active' 
                            #  or
                            #  (
                            #      macd_action == 'FollowTrend' and
                            #      (signalFrom == 'ProGap' or signalFrom=='Spike')
                            #  )
                            )
                    ):
                    try:
                        with get_lock(all_pairs_locks, uid):
                            details = all_pairs.get(uid)
                            if details is not None and not details.get("hedge") and not details.get("hedge_1_1_bool"):
                                all_pairs[uid].update({
                                    "buy_price": current_price,
                                    "buy_qty": hedge_order_size,
                                    "hedge_1_1_bool": True,
                                    "hedge": True,
                                    "hedge_order_size": hedge_order_size,
                                    "type": 'hedge_hold',
                                    "operator_close_time": time_now
                                })
                                with get_lock(analysis_tracker_locks, uid):
                                    analysis_tracker[uid].update({
                                        'StopPriceHedge': 0,
                                        'SinglePostionDecision': None,
                                        'SinglePostionWarning': False,
                                        'NeedsDBUpdate': True,
                                        'NeedsSwingUpdate': True
                                    })
                                log_event(uid, "test_simulation_handle_trade_action", f"Initial Hedge BUY placed at {current_price}", Pl_after_comm)
                                # Immediate database update BEFORE deleteFromGlobalList
                                machine_id = get_machine_id()
                                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                                deleteFromGlobalList(uid)
                    except Exception as e:
                        log_error(e, "test_simulation_handle_trade_action.hedge_SELL", uid)

                elif( 
                        (current_price > stop_price and Pl_after_comm < 0 ) and 
                        current_price > 0 
                                and
                                macd_action == 'FollowTrend'
                        ):
                            try:
                                with get_lock(all_pairs_locks, uid):
                                    details = all_pairs.get(uid)
                                    if details is not None and not details.get("hedge") and not details.get("hedge_1_1_bool"):
                                        all_pairs[uid].update({
                                            "buy_price": current_price,
                                            "buy_qty": hedge_order_size,                                  
                                            "type": 'hedge_hold',
                                            "operator_close_time": time_now
                                        })
                                    
                                        log_event(uid, "test_simulation_handle_trade_action", f"HEDGE HOLD  at {current_price}", Pl_after_comm)
                                        # Immediate database update BEFORE deleteFromGlobalList
                                        machine_id = get_machine_id()
                                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                                        
                            except Exception as e:
                                log_error(e, "test_simulation_handle_trade_action.hedge_SELL", uid)                        

                # ✅ PROFIT → Close
                # elif (signal_decision == 'BUY' or current_price > stop_price) and Pl_after_comm > min_profit and current_price > 0:
                elif ( current_price > stop_price) and (Pl_after_comm > min_profit or min_close == 'ACTIVE') and current_price > 0:
                    try:
                        with get_lock(all_pairs_locks, uid):
                            all_pairs[uid].update({
                                "type": 'close',
                                "close_price": current_price,
                                "operator_close_time": time_now
                            })
                        log_event(uid, "test_simulation_handle_trade_action", f"Closed SELL trade with profit at {current_price}", Pl_after_comm)
                        # Immediate database update BEFORE deleteFromGlobalList
                        machine_id = get_machine_id()
                        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
                        deleteFromGlobalList(uid)
                    except Exception as e:
                        log_error(e, "test_simulation_handle_trade_action.close_SELL", uid)

                elif (current_price > stop_price and 
                    Pl_after_comm > 0 and 
                    min_close == 'NOT_ACTIVE' and 
                    current_price > 0):
                        try:
                            with get_lock(all_pairs_locks, uid):
                                all_pairs[uid].update({
                                    "type": 'hedge_close',
                                    "close_price": current_price,
                                    "operator_close_time": time_now
                                })
                            log_event(uid, "test_simulation_handle_trade_action", f"Hedge Closed SELL trade with profit at {current_price}", Pl_after_comm)
                            # Immediate database update BEFORE deleteFromGlobalList
                            machine_id = get_machine_id()
                            olab_update_single_uid_in_table(uid, all_pairs, machine_id)                            
                        except Exception as e:
                            log_error(e, "test_simulation_handle_trade_action.close_SELL", uid)                        


 # 🔒 Ensure 1:1 hedge logic updates are safe
        # elif hedge and not hedge_1_1:
            
        #     try:
        #         if action == 'BUY' and current_price < stop_price and Pl_after_comm < 0:
        #             print("🔥1-1 Hedge Again for BUY as it cross the StopPriceHedge")
        #             with get_lock(all_pairs_locks, uid):
        #                 all_pairs[uid].update({
        #                     "sell_price": current_price,
        #                     "sell_qty": hedge_order_size,
        #                     "hedge_1_1_bool": True,
        #                     "hedge": True,
        #                     "hedge_order_size": hedge_order_size,
        #                     "type": 'hedge_hold'
        #                 })
        #             with get_lock(analysis_tracker_locks, uid):
        #                 analysis_tracker[uid]['StopPriceHedge'] = 0
        #             log_event(uid, "test_simulation_handle_trade_action", "1-1 Hedge Again for BUY as it cross the StopPriceHedge", Pl_after_comm)
        #             # Immediate database update BEFORE deleteFromGlobalList
        #             machine_id = get_machine_id()
        #             olab_update_single_uid_in_table(uid, all_pairs, machine_id)                    
        #             deleteFromGlobalList(uid)

        #         elif action == 'SELL' and current_price > stop_price and Pl_after_comm < 0:
        #             print("🔥 1 - 1 Hedge Again for SELL as it cross the StopPriceHedge")
        #             with get_lock(all_pairs_locks, uid):
        #                 all_pairs[uid].update({
        #                     "buy_price": current_price,
        #                     "buy_qty": hedge_order_size,
        #                     "hedge_1_1_bool": True,
        #                     "hedge": True,
        #                     "hedge_order_size": hedge_order_size,
        #                     "type": 'hedge_hold'
        #                 })
        #             with get_lock(analysis_tracker_locks, uid):
        #                 analysis_tracker[uid]['StopPriceHedge'] = 0
        #             log_event(uid, "test_simulation_handle_trade_action", "1-1 Hedge Again for SELL as it cross the StopPriceHedge", Pl_after_comm)
        #             # Immediate database update BEFORE deleteFromGlobalList
        #             machine_id = get_machine_id()
        #             olab_update_single_uid_in_table(uid, all_pairs, machine_id)                    
        #             deleteFromGlobalList(uid)

        #         elif Pl_after_comm > 0:
        #             try:
        #                 import time
        #                 current_time = time.time()
                        
        #                 # Check if 1 minute has passed since last heavy computation
        #                 with get_lock(analysis_tracker_locks, uid):
        #                     last_1m_check = analysis_tracker[uid].get('last_1m_heavy_computation', 0)
        #                     should_run_heavy_computation = (current_time - last_1m_check) >= 60  # 1 minute = 60 seconds
        #                     time_since_last = current_time - last_1m_check
                        
        #                 # Debug log for timing check
        #                 log_event(uid, "1M_TIMING_CHECK", f"Time since last heavy computation: {time_since_last:.1f}s | Should run: {should_run_heavy_computation}", Pl_after_comm)
                        
        #                 if should_run_heavy_computation:
        #                     # Log start of heavy computation
        #                     log_event(uid, "1M_HEAVY_COMP_START", f"Starting heavy computation for {action} action", Pl_after_comm)
                            
        #                     # Run heavy computation only once per minute with timeout
        #                     start_time = time.time()
        #                     try:
        #                         # Windows compatible timeout for heavy computation
        #                         from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                                
        #                         def run_heavy_computation():
        #                             df_1m = CalculateSignalsForConfirmation(pair, '1m')
        #                             df_1m = calculate_all_indicators_optimized(df_1m, 'heiken')
        #                             return df_1m
                                
        #                         try:
        #                             with ThreadPoolExecutor(max_workers=1) as executor:
        #                                 future = executor.submit(run_heavy_computation)
        #                                 df_1m = future.result(timeout=20)  # 20 second timeout for heavy computation
        #                         except FutureTimeoutError:
        #                             log_error(Exception("Heavy computation timeout after 20s"), "heavy_computation_timeout", uid)
        #                             return  # Exit function if computation times out
                                
        #                         computation_time = time.time() - start_time
        #                         log_event(uid, "1M_HEAVY_COMP_END", f"Heavy computation completed in {computation_time:.3f}s | df_1m available: {df_1m is not None}", Pl_after_comm)
                                
        #                     except Exception as e:
        #                         computation_time = time.time() - start_time
        #                         log_error(e, "test_simulation_handle_trade_action.heavy_computation_error", uid)
        #                         df_1m = None  # Set to None to prevent further processing
                            
        #                     # Update the last computation time
        #                     with get_lock(analysis_tracker_locks, uid):
        #                         analysis_tracker[uid]['last_1m_heavy_computation'] = current_time

        #                     if action == 'BUY':
        #                         if df_1m is not None:
        #                             last_low_price = df_1m['ha_low'].iloc[-1]
        #                             prev_low_price = all_pairs[uid]['stop_price']
        #                             with get_lock(all_pairs_locks, uid):
        #                                 if last_low_price > prev_low_price:
        #                                     all_pairs[uid]['stop_price'] = last_low_price
        #                                     log_event(uid, "1M_STOP_UPDATE_BUY", f"Stop price updated: {prev_low_price:.6f} → {last_low_price:.6f} | HA_Low: {last_low_price:.6f}", Pl_after_comm)
        #                                 else:
        #                                     log_event(uid, "1M_STOP_NO_UPDATE_BUY", f"Stop price unchanged: {prev_low_price:.6f} | HA_Low: {last_low_price:.6f} (not higher)", Pl_after_comm)

        #                             with get_lock(analysis_tracker_locks, uid):
        #                                 analysis_tracker[uid]['StopPriceHedge'] = last_low_price
                        
        #                 # Always check for hedge close (fast operation)
        #                 prev_stop_price = all_pairs[uid]['stop_price']
        #                 log_event(uid, "FAST_HEDGE_CHECK", f"Checking hedge close: current_price={current_price:.6f} vs stop_price={prev_stop_price:.6f} | action={action}", Pl_after_comm)
                        
        #                 if action == 'BUY':
        #                     if current_price < prev_stop_price:
        #                         with get_lock(all_pairs_locks, uid):
        #                             all_pairs[uid].update({
        #                                 "type": 'hedge_close',
        #                                 "close_price": current_price,
        #                                 "operator_close_time": time_now
        #                             })

        #                         log_event(uid, "test_simulation_handle_trade_action", f"HEDGE CLOSED {action}", Pl_after_comm)                                                                   
        #                         # Immediate database update BEFORE deleteFromGlobalList
        #                         machine_id = get_machine_id()
        #                         olab_update_single_uid_in_table(uid, all_pairs, machine_id)
        #                         log_event(uid, "DB_UPDATE_IMMEDIATE", f"Database updated immediately for HEDGE CLOSE {action}", Pl_after_comm)             
        #                         deleteFromGlobalList(uid)

        #                 elif action == 'SELL':
        #                     # Handle SELL action heavy computation if needed
        #                     if should_run_heavy_computation:
        #                         if df_1m is not None:
        #                             last_high_price = df_1m['ha_high'].iloc[-1]
        #                             prev_high_price = all_pairs[uid]['stop_price']
        #                             with get_lock(all_pairs_locks, uid):
        #                                 if last_high_price < prev_high_price:
        #                                     all_pairs[uid]['stop_price'] = last_high_price
        #                                     log_event(uid, "1M_STOP_UPDATE_SELL", f"Stop price updated: {prev_high_price:.6f} → {last_high_price:.6f} | HA_High: {last_high_price:.6f}", Pl_after_comm)
        #                                 else:
        #                                     log_event(uid, "1M_STOP_NO_UPDATE_SELL", f"Stop price unchanged: {prev_high_price:.6f} | HA_High: {last_high_price:.6f} (not lower)", Pl_after_comm)

        #                             with get_lock(analysis_tracker_locks, uid):
        #                                 analysis_tracker[uid]['StopPriceHedge'] = last_high_price
                            
        #                     # Always check for hedge close (fast operation)
        #                     if current_price > prev_stop_price:
        #                         with get_lock(all_pairs_locks, uid):
        #                             all_pairs[uid].update({
        #                                 "type": 'hedge_close',
        #                                 "close_price": current_price,
        #                                 "operator_close_time": time_now
        #                             })
                    
        #                         log_event(uid, "test_simulation_handle_trade_action", f"HEDGE CLOSED {action}", Pl_after_comm)
        #                         # Immediate database update BEFORE deleteFromGlobalList
        #                         machine_id = get_machine_id()
        #                         olab_update_single_uid_in_table(uid, all_pairs, machine_id)
        #                         log_event(uid, "DB_UPDATE_IMMEDIATE", f"Database updated immediately for HEDGE CLOSE {action}", Pl_after_comm)                                        
        #                         deleteFromGlobalList(uid)
                                
        #             except Exception as e:
        #                 log_error(e, "test_simulation_handle_trade_action.hedge_close", uid)
        #     except Exception as e:
        #         log_error(e, "test_simulation_handle_trade_action.hedge_1_1", uid)
                
        # Single database update at the end for better performance
        if needs_db_update:
            try:
                machine_id = get_machine_id()
                olab_update_single_uid_in_table(uid, all_pairs, machine_id)
            except Exception as e:
                log_error(e, "test_simulation_handle_trade_action.db_update", uid)
                
    except Exception as e:
        log_error(e, "test_simulation_handle_trade_action", uid)
