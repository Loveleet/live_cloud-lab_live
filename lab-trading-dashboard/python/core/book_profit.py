# Example usage:
# from FinalVersionTrading_AWS import CalculateSignals
# profit_booker = ProfitBooker(CalculateSignals)

import pandas as pd
import numpy as np
from FinalVersionTrading_AWS import   CalculateSignals,placeOrder
from utils.logger import log_event, log_error

class ProfitBooker:
    """
    Class to encapsulate the logic for booking profit based on multi-timeframe analysis.
    """
    def __init__(self, CalculateSignals):
        self.CalculateSignals = CalculateSignals

    @staticmethod
    def breakout_levels(df):
        try:
            if df is None or len(df) < 5:
                raise ValueError("DataFrame must have at least 5 rows to calculate breakout levels.")
            df_excl_last = df.iloc[:-1]
            high_level = df_excl_last['ha_high'].tail(4).max()
            low_level = df_excl_last['ha_low'].tail(4).min()
            return high_level, low_level
        except Exception as e:
            log_error(e, "ProfitBooker.breakout_levels")
            return None, None

    def book_profit(self, symbol, interval, currentprice, action):
        try:
            log_event(symbol, "ProfitBooker.book_profit", f"Running BookProfit for {symbol} | Interval: {interval} | Main Action: {action} | Price: {currentprice}", 0)

            # Step 1: Load 15m data
            df_15m = self.CalculateSignals(symbol, '15m''heiken')
          
            if df_15m is None or getattr(df_15m, 'empty', False):
                log_event(symbol, "ProfitBooker.book_profit", "15m DataFrame is empty. Exiting.", 0)
                return None, None

            rsi_15 = df_15m['RSI_9'].iloc[-1]
            candle_color = df_15m['ha_color'].iloc[-1]
            volume_increasing = df_15m['volume_increasing'].iloc[-1]
            macd_color_signal = df_15m['macd_color_signal'].iloc[-1]
            log_event(symbol, "ProfitBooker.book_profit", f"15m RSI: {rsi_15}", 0)

            if action == 'BUY':
                if (70 < rsi_15 < 80 and not volume_increasing or (candle_color == 'RED') or 
                    (macd_color_signal == 'SELL')):
                    log_event(symbol, "ProfitBooker.book_profit", "RSI 70-80 and volume decreasing on 15m, checking 5m...", 0)

                    df_5m = self.CalculateSignals(symbol, '5m', 'heiken')
                   
                    if df_5m is None or getattr(df_5m, 'empty', False):
                        log_event(symbol, "ProfitBooker.book_profit", "5m DataFrame is empty. Exiting.", 0)
                        return None, None
                    candle_color_5m = df_5m['ha_color'].iloc[-1]
                    volume_increasing_5m = df_5m['volume_increasing'].iloc[-1]

                    if not volume_increasing_5m or candle_color_5m == 'RED':    
                        log_event(symbol, "ProfitBooker.book_profit", "Volume decreasing on 5m, checking 1m...", 0)

                        df_1m = self.CalculateSignals(symbol, '1m', 'heiken')
                       
                        if df_1m is None or getattr(df_1m, 'empty', False):
                            log_event(symbol, "ProfitBooker.book_profit", "1m DataFrame is empty. Exiting.", 0)
                            return None, None

                        trend_1m = df_15m['price_trend_direction'].iloc[-1]
                        log_event(symbol, "ProfitBooker.book_profit", f"1m trend: {trend_1m}", 0)

                        if trend_1m == 'DOWNTREND':
                            high_level, low_level = self.breakout_levels(df_1m)
                            log_event(symbol, "ProfitBooker.book_profit", f"Bearish Breakout levels from 1m: High={high_level}, Low={low_level}", 0)
                            return low_level, 'SELL'

                elif rsi_15 > 80 and not volume_increasing:
                    log_event(symbol, "ProfitBooker.book_profit", "RSI > 80 and volume decreasing on 15m, checking 1m...", 0)

                    df_1m = self.CalculateSignals(symbol, '1m', 'heiken')
                   
                    if df_1m is None or getattr(df_1m, 'empty', False):
                        log_event(symbol, "ProfitBooker.book_profit", "1m DataFrame is empty. Exiting.", 0)
                        return None, None

                    trend_1m = df_15m['price_trend_direction'].iloc[-1]
                    log_event(symbol, "ProfitBooker.book_profit", f"1m trend: {trend_1m}", 0)

                    if trend_1m == 'DOWNTREND':
                        high_level, low_level = self.breakout_levels(df_1m)
                        log_event(symbol, "ProfitBooker.book_profit", f"Bearish Breakout levels from 1m: High={high_level}, Low={low_level}", 0)
                        return low_level, 'SELL'

            elif action == 'SELL':
                if (20 < rsi_15 < 30 and not volume_increasing) or (candle_color == 'GREEN') or (macd_color_signal == 'BUY'):
                    log_event(symbol, "ProfitBooker.book_profit", "RSI 20-30 and volume decreasing on 15m, checking 5m...", 0)

                    df_5m = self.CalculateSignals(symbol, '5m', 'heiken')
                  
                    if df_5m is None or getattr(df_5m, 'empty', False):
                        log_event(symbol, "ProfitBooker.book_profit", "5m DataFrame is empty. Exiting.", 0)
                        return None, None
                    candle_color_5m = df_5m['ha_color'].iloc[-1]
                    volume_increasing_5m = df_5m['volume_increasing'].iloc[-1]

                    if not volume_increasing_5m or candle_color_5m == 'GREEN':
                        log_event(symbol, "ProfitBooker.book_profit", "Volume decreasing on 5m, checking 1m...", 0)

                        df_1m = self.CalculateSignals(symbol, '1m', 'heiken')
                     
                        if df_1m is None or getattr(df_1m, 'empty', False):
                            log_event(symbol, "ProfitBooker.book_profit", "1m DataFrame is empty. Exiting.", 0)
                            return None, None

                        trend_1m = df_15m['price_trend_direction'].iloc[-1]
                        log_event(symbol, "ProfitBooker.book_profit", f"1m trend: {trend_1m}", 0)

                        if trend_1m == 'UPTREND':
                            high_level, low_level = self.breakout_levels(df_1m)
                            log_event(symbol, "ProfitBooker.book_profit", f"Bullish  Breakout levels from 1m: High={high_level}, Low={low_level}", 0)
                            return high_level, 'BUY'

                elif rsi_15 < 20 and (not volume_increasing or candle_color == 'GREEN'):
                    log_event(symbol, "ProfitBooker.book_profit", "RSI < 20 and volume decreasing on 15m, checking 1m...", 0)

                    df_1m = self.CalculateSignals(symbol, '1m', 'heiken')
                   
                    if df_1m is None or getattr(df_1m, 'empty', False):
                        log_event(symbol, "ProfitBooker.book_profit", "1m DataFrame is empty. Exiting.", 0)
                        return None, None

                    trend_1m = df_15m['price_trend_direction'].iloc[-1]
                    log_event(symbol, "ProfitBooker.book_profit", f"1m trend: {trend_1m}", 0)

                    if trend_1m == 'UPTREND':
                        high_level, low_level = self.breakout_levels(df_1m)
                        log_event(symbol, "ProfitBooker.book_profit", f"Bullish Breakout levels from 1m: High={high_level}, Low={low_level}", 0)
                        return high_level, 'BUY'

            log_event(symbol, "ProfitBooker.book_profit", "No valid trade signal detected.", 0)
            return None, None
        except Exception as e:
            log_error(e, "ProfitBooker.book_profit", symbol)
            return None, None 

    def should_close_trade_multi(self, symbol, action):
        """
        Checks close conditions across multiple intervals.
        Logs debug info to file.
        Returns True if 2 or more total conditions are true.
        """
        intervals = ['1h', '30m', '15m', '5m']
        total_true_conditions = 0

        def is_volume_above_ma(df):
            try:
                # Assumes 'Volume_MA' is present in df
                return df['volume'].iloc[-1] > df['Volume_MA'].iloc[-1]
            except Exception as e:
                log_error(e, "ProfitBooker.should_close_trade_multi.is_volume_above_ma", symbol)
                return False

        for interval in intervals:
            try:
                log_event(symbol, "ProfitBooker.should_close_trade_multi", f"Analyzing {symbol} for close signal", 0)
                df = self.CalculateSignals(symbol, interval, 'heiken')
               
                if df is None or len(df) < 2:
                    log_event(symbol, "ProfitBooker.should_close_trade_multi", f"[{interval}] ❌ Dataframe empty or too short for {symbol}", 0)
                    continue

                last_candle_color = df['ha_color'].iloc[-1]
                volume_increasing = df['volume_increasing'].iloc[-1] 
                # 1. Volume decreasing
                if action == 'BUY':
                    volume_increasing = volume_increasing and last_candle_color == 'GREEN'
                    # 3. Volume above MA
                    volume_above_ma = is_volume_above_ma(df) and last_candle_color == 'RED'
                elif action == 'SELL':
                    volume_increasing = volume_increasing and last_candle_color == 'RED'
                    # 3. Volume above MA
                    volume_above_ma = is_volume_above_ma(df) and last_candle_color == 'GREEN'
                else:
                    volume_increasing = False
                    volume_above_ma = False

                # 2. RSI < 30 or > 70
                rsi_value = df['RSI_9'].iloc[-1]
                if pd.notna(rsi_value):
                    if action == 'SELL':
                        rsi_condition = rsi_value < 30
                    elif action == 'BUY':
                        rsi_condition = rsi_value > 70
                    else:
                        rsi_condition = False
                else:
                    rsi_condition = False

                # Count how many are true
                count = sum([volume_increasing, rsi_condition, volume_above_ma])
                total_true_conditions += count
                log_event(symbol, "ProfitBooker.should_close_trade_multi", f"volume_increasing={volume_increasing}, rsi_condition={rsi_condition}, volume_above_ma={volume_above_ma}, count={count}", 0)

            except Exception as e:
                log_error(e, "ProfitBooker.should_close_trade_multi", symbol)
        return total_true_conditions >= 2

    def confirm_and_close(self, symbol, action):
        """
        Step 1: Run multi-interval signal check.
        Step 2: If triggered, check 3m and 1m confirmation.
        Return True if both confirm closing trade.
        """
        try:
            if not self.should_close_trade_multi(symbol, action):
                return False  # Not even eligible for confirmation

            final_confirmed = False

            try:
                df_3m = self.CalculateSignals(symbol, '3m', 'heiken')
                if df_3m is not None and len(df_3m) >= 2:
                  
                    rsi_3m_over_sold = df_3m['RSI_9'].iloc[-1] < 30 or df_3m['RSI_9'].iloc[-2] < 30 
                    rsi_3m_over_bought = df_3m['RSI_9'].iloc[-1] > 70 or df_3m['RSI_9'].iloc[-2] > 70
                    vol_dec_3m = df_3m['volume'].iloc[-1] < df_3m['volume'].iloc[-2]
                    trend_3m = df_3m['price_trend_direction'].iloc[-1]
                    macd_color_signal_3m = df_3m['macd_color_signal'].iloc[-1]

                    if (macd_color_signal_3m == 'SELL' and trend_3m == 'DOWNTREND') and action == 'BUY' and rsi_3m_over_bought:
                        final_confirmed = True
                        log_event(symbol, 'ProfitBooker.confirm_and_close', f"BUY-> [3m CONFIRM] RSI={rsi_3m_over_bought}, Volume ↓={vol_dec_3m} ", 0)

                    elif (macd_color_signal_3m == 'BUY' and trend_3m == 'UPTREND') and action == 'SELL' and rsi_3m_over_sold:
                        final_confirmed = True
                        log_event(symbol, 'ProfitBooker.confirm_and_close', f"SELL->[3m CONFIRM] RSI={rsi_3m_over_sold}, Volume ↓={vol_dec_3m} ", 0)
            except Exception as e:
                log_error(e, 'ProfitBooker.confirm_and_close.3m', symbol)

            try:
                df_1m = self.CalculateSignals(symbol, '1m', 'heiken')
                if df_1m is not None and len(df_1m) >= 2:
                 
                    rsi_1m_over_sold = df_1m['RSI_9'].iloc[-1] < 30 or df_1m['RSI_9'].iloc[-2] < 30 
                    rsi_1m_over_bought = df_1m['RSI_9'].iloc[-1] > 70 or df_1m['RSI_9'].iloc[-2] > 70 
                    volume_increasing_1m = df_1m['volume_increasing'].iloc[-1] 
                    trend_1m = df_1m['price_trend_direction'].iloc[-1]
                    macd_color_signal_1m = df_1m['macd_color_signal'].iloc[-1]

                    if (macd_color_signal_1m == 'SELL' and trend_1m == 'DOWNTREND' and  volume_increasing_1m) and action == 'BUY' and rsi_1m_over_bought:
                        final_confirmed = True
                        log_event(symbol, 'ProfitBooker.confirm_and_close', f"BUY->[1m CONFIRM] RSI={rsi_1m_over_bought}, Volume ↓={volume_increasing_1m}  ", 0)

                    elif (macd_color_signal_1m == 'BUY' and trend_1m == 'UPTREND' and  volume_increasing_1m) and action == 'SELL' and rsi_1m_over_sold:
                        final_confirmed = True
                        log_event(symbol, 'ProfitBooker.confirm_and_close', f"SELL->[1m CONFIRM] RSI={rsi_1m_over_sold}, Volume ↓={volume_increasing_1m}  ", 0)
            except Exception as e:
                log_error(e, 'ProfitBooker.confirm_and_close.1m', symbol)

            if final_confirmed:
                log_event(symbol, 'ProfitBooker.confirm_and_close', f"FINAL DECISION: CLOSE TRADE for {symbol} ", 0)
            else:
                log_event(symbol, 'ProfitBooker.confirm_and_close', f"FINAL DECISION: HOLD (No confirmation) {symbol} ", 0)

            return final_confirmed
        except Exception as e:
            log_error(e, 'ProfitBooker.confirm_and_close', symbol)
            return False 
    
    def BBCloseTrade(self,symbol,action,interval,current_price):
        try:
            df_15m = CalculateSignals(symbol, interval, 'heiken')
            if df_15m is not None and (isinstance(df_15m, np.ndarray) or not hasattr(df_15m, 'iloc')):
                df_15m = pd.DataFrame(df_15m)
            
            required_15m_cols = {'BOLL_upper_band', 'BOLL_lower_band', 'RSI_9', 'ha_open'}
            if df_15m is None or not hasattr(df_15m, 'iloc') or df_15m.empty or not required_15m_cols.issubset(df_15m.columns):
                return None, None
            df_15m = pd.DataFrame(df_15m)  # Explicit cast for linter
            last_bb_upper_band_price_15m = df_15m['BOLL_upper_band'].iloc[-1]
            last_bb_lower_band_price_15m = df_15m['BOLL_lower_band'].iloc[-1]

            df_1m = CalculateSignals(symbol, '1m', 'heiken')
            if df_1m is not None and (isinstance(df_1m, np.ndarray) or not hasattr(df_1m, 'iloc')):
                df_1m = pd.DataFrame(df_1m)
         
            required_1m_cols = {'ha_high', 'ha_low'}
            if df_1m is None or not hasattr(df_1m, 'iloc') or df_1m.empty or not required_1m_cols.issubset(df_1m.columns):
                return None, None
            df_1m = pd.DataFrame(df_1m)  # Explicit cast for linter
            last_high_1m = df_1m['ha_high'].iloc[-1]
            last_low_1m = df_1m['ha_low'].iloc[-1]
            rsi_15m = df_15m['RSI_9'].iloc[-1]
            last_open_15m= df_15m['ha_open'].iloc[-1]
            
            
            if action == 'BUY' and (current_price > last_bb_upper_band_price_15m or rsi_15m > 70 ):
                log_event(symbol, 'ProfitBooker.BBCloseTrade', f'BUY --CLOSE-Signal at Last_Low_1m = {last_low_1m} | Last_High_1m = {last_high_1m} | last_bb_upper_band_price_15m = {last_bb_upper_band_price_15m} - All Condtion Meet Bollinger Band Logic for Close ', 0)  
                return last_open_15m, 'REACTNOW'
            
            elif action == 'SELL' and (current_price < last_bb_lower_band_price_15m or rsi_15m < 30):
                log_event(symbol, 'ProfitBooker.BBCloseTrade', f'SELL --CLOSE-Signal at Last_Low_1m = {last_low_1m} | Last_High_1m = {last_high_1m} | last_bb_lower_band_price_15m = {last_bb_lower_band_price_15m} - All Condtion Meet Bollinger Band Logic for Close ', 0)
                return last_open_15m, 'REACTNOW'
            
            return None, None
        
        except Exception as e:
            log_error(e, 'BBCloseTrade Error', symbol)
            return None, None  # also safe on error

    def CheckTrendClose(self,symbol,action,interval,save_price):
        try:
            df = CalculateSignals(symbol, interval, 'heiken')
            if df is not None and (isinstance(df, np.ndarray) or not hasattr(df, 'iloc')):
                df = pd.DataFrame(df)


            required_cols = {'ha_high', 'ha_low'}
            if df is None or not hasattr(df, 'iloc') or df.empty or not required_cols.issubset(df.columns):
                return None, None
            df = pd.DataFrame(df)  # Explicit cast for linter
            rsi_9 = df['RSI_9'].iloc[-1]

            
            if action == 'BUY' and rsi_9 > 70:             
                return df['ha_low'].iloc[-1], 'Update_Stop_Price'
            elif action == 'SELL' and rsi_9 < 30:    
               return df['ha_high'].iloc[-1], 'Update_Stop_Price'
            
            return None, None
        except Exception as e:
            log_error(e, 'CheckTrendClose Error', symbol)
            return None, None
        
    def CheckZeroLagExit(self, symbol, action, interval,save_price,current_price):
        """
        Check Zero Lag Trend Strategy exit conditions based on Heiken Ashi and current price
        
        Args:
            symbol: Trading symbol
            action: 'BUY' (for LONG position) or 'SELL' (for SHORT position)
            interval: Timeframe to check
            current_price: Current market price from websocket
            
        Returns:
            tuple: (exit_price, exit_action) or (None, None) if no exit
        """
        try:
            df = CalculateSignals(symbol, interval, 'regular')
            if df is not None and (isinstance(df, np.ndarray) or not hasattr(df, 'iloc')):
                df = pd.DataFrame(df)


            required_cols = {'ha_trend_up', 'ha_trend_down', 'price_vs_ha_open', 'ha_open'}
            if df is None or not hasattr(df, 'iloc') or df.empty or not required_cols.issubset(df.columns):
                return None, None
                
            df = pd.DataFrame(df)  # Explicit cast for linter
            
            # Get latest Heiken Ashi indicators
            ha_trend_up = df['ha_trend_up'].iloc[-1]
            ha_trend_down = df['ha_trend_down'].iloc[-1]
            previous_ha_open = df['ha_open'].iloc[-2] if len(df) > 1 else df['ha_open'].iloc[-1]  # Previous HA open
            last_high = df['ha_high'].iloc[-1]
            last_low = df['ha_low'].iloc[-1]
            
            # Calculate current price vs previous HA open using real-time price
            current_price_vs_ha_open = current_price > previous_ha_open
            
            if action == 'BUY':  # LONG position
                # Exit LONG: ha_trend_down OR current_price < previous_ha_open
                exit_condition = ha_trend_down or not current_price_vs_ha_open
                if exit_condition:
                    log_event(symbol, "CheckZeroLagExit", f"LONG Exit Signal - HA Down: {ha_trend_down}, Current Price < HA Open: {not current_price_vs_ha_open}", 0)
                    return current_price, 'Trend_To_Exit'  # Close long position
                elif last_low > save_price:
                    return last_low, 'Update_Stop_Price'

            elif action == 'SELL':  # SHORT position
                # Exit SHORT: ha_trend_up OR current_price > previous_ha_open
                exit_condition = ha_trend_up or current_price_vs_ha_open
                if exit_condition:
                    log_event(symbol, "CheckZeroLagExit", f"SHORT Exit Signal - HA Up: {ha_trend_up}, Current Price > HA Open: {current_price_vs_ha_open}", 0)
                    return current_price, 'Trend_To_Exit'  # Close short position
                elif last_high < save_price:
                    return last_high, 'Update_Stop_Price'
                    
            return None, None
            
        except Exception as e:
            log_error(e, 'CheckZeroLagExit Error', symbol)
            return None, None

    def TradingViewExit(self, symbol, action, interval,save_price,current_price):
            """
            Check Zero Lag Trend Strategy exit conditions based on Heiken Ashi and current price
            
            Args:
                symbol: Trading symbol
                action: 'BUY' (for LONG position) or 'SELL' (for SHORT position)
                interval: Timeframe to check
                current_price: Current market price from websocket
                
            Returns:
                tuple: (exit_price, exit_action) or (None, None) if no exit
            """
            try:
                df = CalculateSignals(symbol, interval, 'heiken')
                if df is not None and (isinstance(df, np.ndarray) or not hasattr(df, 'iloc')):
                    df = pd.DataFrame(df)


                required_cols = {'ha_trend_up', 'ha_trend_down', 'price_vs_ha_open', 'ha_open'}
                if df is None or not hasattr(df, 'iloc') or df.empty or not required_cols.issubset(df.columns):
                    return None, None
                    
                # ---- LIVE EXIT SIGNALS (latest bar) -----------------------------------------
                latest = df.iloc[-1]
                exit_long_raw  = bool(latest['exit_long_raw'])
                exit_short_raw = bool(latest['exit_short_raw'])
                last_open = df['ha_open'].iloc[-1]
                
                last_candle_time = df.index[-1]
                            
                # Calculate current price vs previous HA open using real-time price

                
                if action == 'BUY':  # LONG position
                    # Exit LONG: ha_trend_down OR current_price < previous_ha_open
                    if exit_long_raw:
                        log_event(symbol, "TradingViewExit", f"LONG Exit Signal - HA Down: {exit_long_raw}, Current Price : {current_price} at Candle Time : {last_candle_time}", 0)
                        return current_price, 'Update_Stop_Price'  # Close long position
                    elif last_open > save_price:
                        return last_open, 'Update_Stop_Price'

                elif action == 'SELL':  # SHORT position
                    # Exit SHORT: ha_trend_up OR current_price > previous_ha_open
                    if exit_short_raw:
                        log_event(symbol, "TradingViewExit", f"SHORT Exit Signal - HA Up: {exit_short_raw}, Current Price : {current_price} at Candle Time : {last_candle_time}", 0)
                        return current_price, 'Update_Stop_Price'  # Close short position
                    elif last_open < save_price:
                        return last_open, 'Update_Stop_Price'
                        
                return None, None
                
            except Exception as e:
                log_error(e, 'TradingViewExit Error', symbol)
                return None, None                    
                        
    def SuperTrendStopPrice(self, symbol, action):
            """
            Check Zero Lag Trend Strategy exit conditions based on Heiken Ashi and current price
            
            Args:
                symbol: Trading symbol
                action: 'BUY' (for LONG position) or 'SELL' (for SHORT position)
                interval: Timeframe to check
                current_price: Current market price from websocket
                
            Returns:
                tuple: (exit_price, exit_action) or (None, None) if no exit
            """
            try:
                df = CalculateSignals(symbol, '1h', 'heiken')
                if df is not None and (isinstance(df, np.ndarray) or not hasattr(df, 'iloc')):
                    df = pd.DataFrame(df)


                if df is None or not hasattr(df, 'iloc') or df.empty:
                    return None, None
                    
                # ---- LIVE EXIT SIGNALS (latest bar) -----------------------------------------
                latest = df.iloc[-1]
                previous_low = latest['ha_low']
                previous_high = latest['ha_high']

                            
                # Calculate current price vs previous HA open using real-time price                
                if action == 'BUY':  # LONG position
                    return previous_low
                elif action == 'SELL':  # SHORT position
                    return previous_high
                        
                return None, None
                
            except Exception as e:
                log_error(e, 'TradingViewExit Error', symbol)
                return None, None          


    # def FollowTrend(self, symbol, action, interval):
    #     try:
    #         def last(df, col):
    #             return df[col].iloc[-1] if (df is not None and hasattr(df, "columns") and col in df.columns and len(df) > 0) else None

    #         def last2(df, col):
    #             if df is None or not hasattr(df, "columns") or col not in df.columns or len(df) < 2:
    #                 return None, None
    #             return df[col].iloc[-1], df[col].iloc[-2]

    #         # --- normalize interval key ---
    #         key = str(interval).strip().lower()

    #         # --- explicit mapping to next-higher TF ---

    #         trend_mapping = {
    #             '2h': '4h',
    #             '1h': '2h',
    #             '30m': '1h',
    #             '15m': '30m',
    #         }

    #         trend_detect_interval = trend_mapping.get(key, key)

    #         # (A) Higher timeframe alignment
    #         if key != trend_detect_interval:
    #             df_trend = CalculateSignals(symbol, trend_detect_interval, 'heiken')
    #             if df_trend is not None and len(df_trend) > 0:
    #                 prev_tdfi     = last(df_trend, 'tdfi_state')
    #                 cci_sma_trend = last(df_trend, 'cci_sma_9')
    #                 if prev_tdfi == 'BULL' and action == 'BUY' and cci_sma_trend == 'INCREASING':
    #                     return 'update_interval', trend_detect_interval
    #                 elif prev_tdfi == 'BEAR' and action == 'SELL' and cci_sma_trend == 'INCREASING':
    #                     return 'update_interval', trend_detect_interval

    #         # (B) Base timeframe checks
    #         df = CalculateSignals(symbol, key, 'heiken')
    #         if df is None or len(df) == 0:
    #             return None, None

    #         cci_sma         = last(df, 'cci_sma_9')
    #         cci_exit_cross  = last(df, 'cci_exit_cross_9')
    #         cci_entry_state = last(df, 'cci_entry_state_9')
    #         rsi_9 = last(df, 'RSI_9')
    #         ha_high_last, ha_high_prev = last2(df, 'ha_high')
    #         ha_low_last,  ha_low_prev  = last2(df, 'ha_low')

    #         print(cci_entry_state,rsi_9,cci_sma,'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')

    #         # (B1) Reverse ladder when weakening
    #         if (cci_sma == 'DECREASING' 
    #             or (action == 'BUY' and cci_entry_state=='BEAR')
    #             or (action == 'SELL' and cci_entry_state=='BULL')):
               
    #             reverse_trend_mapping = {
    #                 '4h': ['2h','1h'],
    #                 '2h': ['1h','30m'],
    #                 '1h': ['30m'],
    #                 '30m': ['15m'],
    #                 '15m': ['5m'],                  
    #             }
    #             for tf in reverse_trend_mapping.get(key, []):
    #                 if tf == key:
    #                     continue
    #                 try:
    #                     df_rev = CalculateSignals(symbol, tf, 'heiken')

    #                     if df_rev is None or len(df_rev) == 0:
    #                         continue

                        
    #                     cci_sma_reverse = last(df_rev, 'cci_sma_9')
    #                     cci_entry_state_reverse = last(df, 'cci_entry_state_9')

    #                     print(f'CCI is {cci_sma_reverse} for interval {tf}')

    #                     if (cci_sma_reverse == 'DECREASING' 
    #                         or (action == 'BUY' and cci_entry_state_reverse=='BEAR')
    #                         or (action == 'SELL' and cci_entry_state_reverse=='BULL')):

    #                         return 'update_interval', tf
                        
    #                 except Exception as e:
    #                     log_error(e, 'FollowTrend reverse check', symbol)
    #                     return None, None

    #         # (B2) Exit conditions — independent checks (no elif)
    #         exit_sell = (
    #             action == 'SELL'
    #             and (cci_exit_cross == 'BUY' or cci_entry_state == 'BULL')
    #             and ha_low_last is not None and ha_low_prev is not None
    #             and (ha_low_last < ha_low_prev)
    #         )
    #         if exit_sell:
    #             return 'exit_trade', None

    #         exit_buy = (
    #             action == 'BUY'
    #             and (cci_exit_cross == 'SELL' or cci_entry_state == 'BEAR')
    #             and ha_high_last is not None and ha_high_prev is not None
    #             and (ha_high_last > ha_high_prev)
    #         )
    #         if exit_buy:
    #             return 'exit_trade', None


            
    #         if action == 'BUY' and rsi_9 > 80 and rsi_9 < 90:
    #             return 'update_stop_price', ha_low_last
    #         if action == 'SELL' and  rsi_9 < 20 and rsi_9 > 10:
    #             return 'update_stop_price', ha_high_last
            
    #         if action == 'BUY' and rsi_9 > 90:
    #             return 'update_stop_price_rsi', ha_low_last
    #         if action == 'SELL' and  rsi_9 < 10:
    #             return 'update_stop_price_rsi', ha_high_last

    #         # Fallback: update stop only if we have the prior HA level
    #         if action == 'BUY' and ha_low_prev is not None:
    #             return 'update_stop_price', ha_low_prev
    #         if action == 'SELL' and ha_high_prev is not None:
    #             return 'update_stop_price', ha_high_prev

    #         # No action
    #         return None, None

    #     except Exception as e:
    #         log_error(e, 'FollowTrend', symbol)
    #         return None, None

    def FollowTrend(self, symbol, action, interval,current_price,Pl_after_comm):
        try:
            def last(df, col):
                return df[col].iloc[-1] if (df is not None and hasattr(df, "columns") and col in df.columns and len(df) > 0) else None

            def last2(df, col):
                if df is None or not hasattr(df, "columns") or col not in df.columns or len(df) < 2:
                    return None, None
                return df[col].iloc[-1], df[col].iloc[-2]

            # --- normalize interval key ---
            key = str(interval).strip().lower()

            # --- explicit mapping to next-higher TF ---

            

            trend_mapping = {
               # '1h': '2h',
                '30m': '1h',
                '15m': '30m',
                '5m': '15m',
            }

            trend_detect_interval = trend_mapping.get(key, key)

            # (A) Higher timeframe alignment
            if key != trend_detect_interval:
                df_trend = CalculateSignals(symbol, trend_detect_interval, 'regular')
                if df_trend is not None and len(df_trend) > 0:
                    # prev_tdfi     = last(df_trend, 'tdfi_state')
                    cci_sma_trend = last(df_trend, 'cci_sma_100')
                    cci_entry_trend = last(df_trend, 'cci_entry_state_100')
                    cci_exit_cross = last(df_trend, 'cci_exit_cross_100')
                    cci_value = last(df_trend, 'cci_value_100')

                    # if (
                    #     (cci_entry_trend == 'BULL' and action == 'BUY' and cci_sma_trend == 'INCREASING')
                    #     or
                    #     (cci_entry_trend == 'BEAR' and action == 'BUY' and cci_sma_trend == 'DECREASING')                        
                    #     ) :
                    #     return 'update_interval', trend_detect_interval
                    
                    # elif (
                    #     (cci_entry_trend == 'BEAR' and action == 'SELL' and cci_sma_trend == 'INCREASING')
                    #     or
                    #     (cci_entry_trend == 'BULL' and action == 'SELL' and cci_sma_trend == 'DECREASING')
                    #     ):
                    #     return 'update_interval', trend_detect_interval

                    if cci_entry_trend == 'BULL' and action == 'BUY' and cci_sma_trend == 'INCREASING' and cci_value < 100:
                        return 'update_interval', trend_detect_interval
                    elif cci_entry_trend == 'BEAR' and action == 'SELL' and cci_sma_trend == 'INCREASING' and cci_value > -100: 
                        return 'update_interval', trend_detect_interval


            # (B) Base timeframe checks
            df = CalculateSignals(symbol, key, 'regular')
            if df is None or len(df) == 0:
                return None, None

            cci_sma         = last(df, 'cci_sma_100')
            cci_exit_cross  = last(df, 'cci_exit_cross_100')
            cci_entry_state = last(df, 'cci_entry_state_100')
            rsi_9 = last(df, 'RSI_9')
            ha_high_last, ha_high_prev = last2(df, 'ha_high')
            ha_low_last,  ha_low_prev  = last2(df, 'ha_low')

            last_total_change = last(df, 'Total_Change_Regular')

            cci_value = last(df, 'cci_value_100')

            print(cci_entry_state,rsi_9,cci_sma,symbol,cci_value,'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',action,df.index[-1])

            # (B1) Reverse ladder when weakening
            # if (cci_sma == 'DECREASING' 
            #     or (action == 'BUY' and cci_entry_state=='BEAR')
            #     or (action == 'SELL' and cci_entry_state=='BULL')):
            # if (
            #     # ??????????????????????????????????????????????????????????????????????????????????????
            #     # BE CAREFUL IT MIGHT REACT OPPSITORE. NED TO CHECK

            #         # Don't long if bulls are tired
            #     (cci_sma == 'DECREASING' and action == 'BUY' and cci_entry_state == 'BULL')
            #         # Don't short if bears are tired
            #     or  (cci_sma == 'DECREASING' and action == 'SELL' and cci_entry_state == 'BEAR')
            #         # Don't countertrend long into growing bearish momentum
            #     or (cci_sma == 'INCREASING' and action == 'BUY' and cci_entry_state=='BEAR')
            #         # Don't countertrend short into growing bullish momentum
            #     or (cci_sma == 'INCREASING' and action == 'SELL' and cci_entry_state=='BULL')
            #         # Don't go opposite of a fresh cross
            #     or (action=='BUY' and cci_exit_cross=='SELL')
            #     or (action=='SELL' and cci_exit_cross=='BUY')):   
            # 
         # (B1) Reverse ladder when weakening
            # if ( (Pl_after_comm > 0 and
            #     (cci_sma == 'DECREASING' 
            #     and (action == 'BUY' ) or 
            #          (action == 'SELL' )
            #     ))
            #     or (((action == 'BUY' and cci_entry_state=='BEAR') or (cci_value > 100)) and current_price < ha_low_last )
            #     or (action == 'SELL' and cci_entry_state=='BULL' and current_price > ha_high_last)):

            exit_on_cci_ha = (
                            # Pl_after_comm > 0 and # we need to enable later
                            (
                                # BUY exit: CCI turns bearish or overbought, and price breaks below last HA low
                                (
                                    action == "BUY"
                                    and (
                                        (cci_entry_state == "BULL" and cci_sma == "DECREASING")
                                        or
                                        (cci_entry_state == "BEAR" and cci_sma == "INCREASING")
                                        or (cci_exit_cross) == 'SELL'
                                        or (cci_value > 100)
                                    )
                                    #and current_price < ha_low_last
                                )
                                or
                                # SELL exit: CCI turns bullish or oversold, and price breaks above last HA high
                                (
                                    action == "SELL"
                                    and (
                                        (cci_entry_state == "BEAR" and cci_sma == "DECREASING")
                                        or
                                        (cci_entry_state == "BULL" and cci_sma == "INCREASING")
                                        or (cci_exit_cross) == 'BUY'
                                        or
                                        (cci_value < -100)
                                    )
                                    #and current_price > ha_high_last
                                )
                            )
                         )

            if exit_on_cci_ha:
          
                reverse_trend_mapping = {                  
                    '2h': ['1h','30m'],
                    '1h': ['30m'],
                    '30m': ['15m'],
                    '15m': ['5m'],                  
                }
                for tf in reverse_trend_mapping.get(key, []):
                    if tf == key:
                        continue
                    try:
                        df_rev = CalculateSignals(symbol, tf, 'regular')

                        if df_rev is None or len(df_rev) == 0:
                            continue
                        
                        cci_sma_reverse = last(df_rev, 'cci_sma_100')
                        cci_entry_state_reverse = last(df_rev, 'cci_entry_state_100')
                        last_cci_value_100 = last(df_rev, 'cci_value_100')

                        print('yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy')
                        print(f'CCI is {cci_sma_reverse} for interval {tf} - {symbol} - {df_rev.index[-1]}')
                        print(f'{action}--- {cci_entry_state_reverse}- {last_cci_value_100} -{symbol}')
                        print('cccccccccccccccccccccccccccccccccccccc')


                        if (
                            (cci_sma_reverse == 'DECREASING' 
                            and (
                            (action == 'BUY' and cci_entry_state_reverse=='BULL')
                            or 
                            (action == 'SELL' and cci_entry_state_reverse=='BEAR')
                            )
                            )
                        or (action == 'BUY' and last_cci_value_100 > 100)
                        or (action == 'SELL' and last_cci_value_100 < -100)
                        ):

                            print(f'Need to update interval from {key} to {tf} -- {symbol}')
                            return 'update_interval', tf
                        
                    except Exception as e:
                        log_error(e, 'FollowTrend reverse check', symbol)
                        return None, None

            # (B2) Exit conditions — independent checks (no elif)
            exit_sell = (
                action == 'SELL'
                and (cci_exit_cross == 'BUY' or cci_entry_state == 'BULL')
                and ha_low_last is not None and ha_low_prev is not None
                and (ha_high_last > ha_high_prev)
                
            )
            if exit_sell:
                return 'exit_trade', None

            exit_buy = (
                action == 'BUY'
                and (cci_exit_cross == 'SELL' or cci_entry_state == 'BEAR')
                and ha_high_last is not None and ha_high_prev is not None
                and (ha_low_last < ha_low_prev)
                
            )
            #volatine need to check early not at the end
            if exit_buy:
                return 'exit_trade', None
            
            if last_total_change > 4 :
                return 'volatility_detected',None


            
            # if action == 'BUY' and rsi_9 > 70 and rsi_9 < 90:
            #     return 'update_stop_price', ha_low_last
            # if action == 'SELL' and  rsi_9 < 30 and rsi_9 > 10:
            #     return 'update_stop_price', ha_high_last
            
            # if action == 'BUY' and rsi_9 > 90:
            #     return 'update_stop_price_rsi', ha_low_last
            # if action == 'SELL' and  rsi_9 < 10:
            #     return 'update_stop_price_rsi', ha_high_last

            # Fallback: update stop only if we have the prior HA level
            # if action == 'BUY' and ha_low_prev is not None:
            #     return 'update_stop_price', ha_low_prev
            # if action == 'SELL' and ha_high_prev is not None:
            #     return 'update_stop_price', ha_high_prev

            # No action
            return None, None

        except Exception as e:
            log_error(e, 'FollowTrend', symbol)
            return None, None

    def exit_2h_tdi(self, symbol, action):
        try:
            
            # (B) Base timeframe checks
            df = CalculateSignals(symbol, '2h', 'regular')
            if df is None or len(df) == 0:
                return None, None    

                        # Add 2h TDFI state
            last_2h_tdfi = df['tdfi_state_2_ema'].iloc[-1]
            last_2h_tdfi_3_ema = df['tdfi_state_3_ema'].iloc[-1]


            prior_2h_tdfi = df['tdfi_state_2_ema'].iloc[-2]
            prior_2h_tdfi_3_ema = df['tdfi_state_3_ema'].iloc[-2]



            last_buy_signal =  ( last_2h_tdfi == 'BULL' and last_2h_tdfi_3_ema == 'BULL')
            prior_buy_signal = (prior_2h_tdfi=='BULL' and prior_2h_tdfi_3_ema=='BULL')  

            

            last_sell_signal =  ( last_2h_tdfi == 'BEAR' and last_2h_tdfi_3_ema == 'BEAR')
            prior_sell_signal = (prior_2h_tdfi=='BEAR' and prior_2h_tdfi_3_ema=='BEAR')



            buy_exit = not last_buy_signal and prior_buy_signal
            sell_exit = not last_sell_signal and prior_sell_signal


            # buy_exit = (
            #     ( last_2h_tdfi != 'BULL' and last_2h_tdfi_3_ema != 'BULL')
            #     and
            #         (prior_2h_tdfi=='BULL' and prior_2h_tdfi_3_ema=='BULL')
            #      )

            # sell_exit = (
            #     ( last_2h_tdfi != 'BEAR' and last_2h_tdfi_3_ema != 'BEAR')
            #     and
            #         (prior_2h_tdfi=='BEAR' and prior_2h_tdfi_3_ema=='BEAR')
            #      )

            if sell_exit and action == 'SELL':
                return 'exit_trade', None

           
            if buy_exit and action == 'BUY':
                return 'exit_trade', None



            # No action
            return None, None

        except Exception as e:
            log_error(e, 'FollowTrend', symbol)
            return None, None

    def check_for_add_investment(self, symbol, action) :

        try:
            
            # (B) Base timeframe checks
            df = CalculateSignals(symbol, '15m', 'regular')
            if df is None or len(df) == 0:
                return False    

                        # Add 2h TDFI state
            last_cci_exit_cross_9_15m = df['cci_exit_cross_9'].iloc[-1]
            last_RSI_9_15m = df['RSI_9'].iloc[-1]
            last_price_range_flat_market_15m = df['price_range_flat_market'].iloc[-1]
            last_Volume_Ratio_15m =  df['Volume_Ratio'].iloc[-1]

            vol_ok = (last_Volume_Ratio_15m >= 1.5)  # tune 1.3–2.0 depending on pair

            
            
            if last_cci_exit_cross_9_15m == 'BUY' and  last_RSI_9_15m < 70 and not last_price_range_flat_market_15m and action == 'BUY' :
                return True

            elif last_cci_exit_cross_9_15m == 'SELL' and last_RSI_9_15m > 30 and not last_price_range_flat_market_15m and action == 'SELL' :
                return True
            
            return False

        except Exception as e:
            log_error(e, 'FollowTrend', symbol)
            return False
        

    def CheckForNewTrade(self, symbol, action,pl_after_comm,invest,buy_price,sell_price,close_price,current_price,trade_type) :

            try:
                df_4h = CalculateSignals(symbol, '4h', 'regular')
                if df_4h is None or len(df_4h) == 0:
                    return None, None   
                
                previous_row_4h = df_4h.iloc[-1]
                prior_row_4h = df_4h.iloc[-2]
                
                last_OB_SIGNAL_4h = previous_row_4h['OB_SIGNAL'] 
                last_henkin_candle_color_4h = previous_row_4h['ha_color']
                prior_henkin_candle_color_4h = prior_row_4h['ha_color']
                last_RSI_9_4h = previous_row_4h['RSI_9']

                if action == 'BUY' and (last_OB_SIGNAL_4h == 'SELL' or (last_henkin_candle_color_4h == 'RED' and prior_henkin_candle_color_4h == 'RED')):
                    return 'close_now','OB Opposite SELL Signal 4h'
                if action == 'SELL' and (last_OB_SIGNAL_4h == 'BUY' or (last_henkin_candle_color_4h == 'GREEN' and prior_henkin_candle_color_4h == 'GREEN')):
                    return 'close_now','OB Opposite Signal 4h'
                
                # (B) Base timeframe checks
                df_15m = CalculateSignals(symbol, '15m', 'regular')
                if df_15m is None or len(df_15m) == 0:
                    return None, None    

                
                previous_row_15m = df_15m.iloc[-1]
                            
                last_take_action_15m = previous_row_15m['TAKEACTION']
                last_cci_exit_cross_9_15m = previous_row_15m['cci_exit_cross_9']
                last_cci_exit_cross_100_15m = previous_row_15m['cci_exit_cross_100']

                last_cci_entry_state_100_15m = previous_row_15m['cci_entry_state_100']
                last_cci_sma_100_15m = previous_row_15m['cci_sma_100']

                last_henkin_candle_color = previous_row_15m['ha_color']
                last_regular_candle_color = previous_row_15m['color']



                last_RSI_9_15m = previous_row_15m['RSI_9']
                last_Volume_Ratio_15m =  previous_row_15m['Volume_Ratio']

                vol_ok = (last_Volume_Ratio_15m >= 1.5)  # tune 1.3–2.0 depending on pair


                if (action == 'BUY' and last_take_action_15m == 'BUY' and last_henkin_candle_color == 'GREEN' and  last_henkin_candle_color_4h == 'GREEN' and
                    last_RSI_9_4h < 70 ):
                    min_profit = 100
                    remaining_profit = abs(min_profit - pl_after_comm)

                    if remaining_profit > 100 :
                        remaining_profit = 100

                    
                    invest = invest + 2000
                    signal_data = {                      
                        'previous_row_15m': previous_row_15m.to_dict(),                              
                        'previous_row_4h': previous_row_4h.to_dict()
                        }

                    placeOrder(symbol, '15m', 'BUY', 'Kicker', df_4h, signal_data,remaining_profit,invest, 'heiken') 
                    return 'close_now_new_trade','New Trade Executed BUY with Last Take Action 15m BUY'

                if (action == 'SELL' and last_take_action_15m == 'SELL' and last_henkin_candle_color == 'RED' and  last_henkin_candle_color_4h == 'RED' and
                    last_RSI_9_4h > 30 ):
                    min_profit = 100
                    remaining_profit = abs(min_profit - pl_after_comm)

                    if remaining_profit > 100 :
                        remaining_profit = 100

                    invest = invest + 2000
                    signal_data = {                      
                        'previous_row_15m': previous_row_15m.to_dict(),                              
                        'previous_row_4h': previous_row_4h.to_dict()
                        }

                    placeOrder(symbol, '15m', 'SELL', 'Kicker', df_4h, signal_data,remaining_profit,invest, 'heiken') 
                    return 'close_now_new_trade','New Trade Executed SELL with Last Take Action 15m SELL'
                


                # if (
                #     action == 'BUY' and 
                #     last_henkin_candle_color_4h == 'GREEN' and
                #     last_RSI_9_4h < 70 and
                #     (
                #         current_price > close_price and 
                #         trade_type == 'hedge_close'
                #     ) 
                #     or
                #     (
                #         current_price > sell_price and 
                #         trade_type == 'hedge_hold'
                #     ) 
                #     and
                #     last_henkin_candle_color == 'GREEN' and
                #     (
                #         (
                #             last_cci_exit_cross_9_15m == 'BUY' 
                #             or
                #             last_cci_exit_cross_100_15m == 'BUY' 
                #         )
                #         or
                #         (
                #             last_cci_entry_state_100_15m == 'BULL' 
                #             and
                #             last_cci_sma_100_15m == 'INCREASING'
                #         )
                #     )
                # ): 
                #     min_profit = 100
                #     remaining_profit = abs(min_profit - pl_after_comm)

                #     if remaining_profit > 100 :
                #         remaining_profit = 100

                #     signal_data = {                      
                #         'previous_row_15m': previous_row_15m.to_dict(),                              
                #         'previous_row_4h': previous_row_4h.to_dict()
                #         }

                #     placeOrder(symbol, '15m', 'BUY', 'Spike', df_4h, signal_data,remaining_profit,invest, 'heiken') 
                #     return 'close_now_new_trade','New Trade Executed Cross last Close Price BUY with Hedge Close Condition'   




                # if (
                #     action == 'SELL' and 
                #     last_henkin_candle_color_4h == 'RED' and
                #     last_RSI_9_4h > 30 and
                #     (
                #         current_price < close_price and 
                #         trade_type == 'hedge_close' 
                #     ) 
                #     or
                #     (
                #         current_price < buy_price and 
                #         trade_type == 'hedge_hold'
                #     ) 
                #     and
                    
                #     last_henkin_candle_color == 'RED' and
                #     (
                #         (
                #             last_cci_exit_cross_9_15m == 'SELL' 
                #             or
                #             last_cci_exit_cross_100_15m == 'SELL' 
                #         )
                #         or
                #         (
                #             last_cci_entry_state_100_15m == 'BEAR' 
                #             and
                #             last_cci_sma_100_15m == 'INCREASING'
                #         )
                #     )
                # ): 
                #     min_profit = 100
                #     remaining_profit = abs(min_profit - pl_after_comm)

                #     if remaining_profit > 100 :
                #         remaining_profit = 100

                #     signal_data = {                      
                #         'previous_row_15m': previous_row_15m.to_dict(),                              
                #         'previous_row_4h': previous_row_4h.to_dict()
                #         }

                #     placeOrder(symbol, '15m', 'SELL', 'Spike', df_4h, signal_data,remaining_profit,invest, 'heiken') 
                #     return 'close_now_new_trade','New Trade Executed Cross last Close Price SELL with Hedge Close Condition'     



                # if (action == 'BUY' and last_cci_exit_cross_9_15m == 'BUY' and  
                #     last_RSI_9_15m < 70  and last_regular_candle_color == 'GREEN' and
                #      last_henkin_candle_color_4h == 'GREEN' and
                #     last_RSI_9_4h < 70 ):
                #     min_profit = 100
                #     remaining_profit = abs(min_profit - pl_after_comm)

                #     if remaining_profit > 100 :
                #         remaining_profit = 100

                #     invest = invest + 2000
                #     signal_data = {                      
                #         'previous_row_15m': previous_row_15m.to_dict(),                              
                #         'previous_row_4h': previous_row_4h.to_dict()
                #         }

                #     placeOrder(symbol, '15m', 'BUY', 'ProGap', df_4h, signal_data,remaining_profit,invest, 'heiken') 
                #     return 'close_now_new_trade','New Trade Executed BUY with CCI EXIT 15m BUY'
                
                # if (action == 'SELL' and last_cci_exit_cross_9_15m == 'SELL' and  
                #     last_RSI_9_15m > 30 and last_regular_candle_color == 'RED' and
                #     last_henkin_candle_color_4h == 'RED' and
                #     last_RSI_9_4h > 30 ):
                #     min_profit = 100
                #     remaining_profit = abs(min_profit - pl_after_comm)

                #     if remaining_profit > 100 :
                #         remaining_profit = 100

                #     invest = invest + 2000
                #     signal_data = {                      
                #         'previous_row_15m': previous_row_15m.to_dict(),                              
                #         'previous_row_4h': previous_row_4h.to_dict()
                #         }

                #     placeOrder(symbol, '15m', 'SELL', 'ProGap', df_4h, signal_data,remaining_profit,invest, 'heiken') 
                #     return 'close_now_new_trade','New Trade Executed SELL with CCI EXIT 15m SELL'

                return None, None 

            except Exception as e:
                log_error(e, 'FollowTrend', symbol)
                return None, None  



                                           