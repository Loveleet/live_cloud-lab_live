import pandas as pd
import numpy as np
import talib
from talib._ta_lib import MA_Type
import time
import threading
import concurrent.futures
import json
import os
import sys
from datetime import datetime, timezone, timedelta
import warnings
import signal
import multiprocessing
import psutil
warnings.filterwarnings('ignore')

from utils.FinalVersionTradingDB_PostgreSQL import (
    fetch_squeezed_pairs_from_db, 
    fetch_non_squeezed_pairs_from_db,
    update_squeeze_status,
    fetch_price_precision_from_db,
    fetch_data_safe,
    fetch_data_safe_for_machines,
    check_signal_processing_log_exists,
    insert_signal_processing_log,
    AssignTradeToMachineLAB,
    fetch_single_pair_from_db,
    check_running_trade_exists,
    fetch_squeezed_pairs_from_db_paginated,
    fetch_non_squeezed_pairs_from_db_paginated
)

# Import logging functions for main signal detection
from utils.logger import (
    log_error,
    log_signal_processing,
    log_signal_validation,
    log_performance_metric,
    log_batch_processing,
    log_system_health,
    log_cache_performance,
    performance_monitor
)

# Machine ID for main signal detection system
MAIN_SIGNAL_DETECTOR_ID = "MAIN_SIGNAL_DETECTOR"

BBW_SQUEEZE_THRESHOLD = 0.05
MAX_WORKERS = 8
MIN_WORKERS = 2
CACHE_TIMEOUT = 300
MAX_CONSECUTIVE_CRASHES = 3
PROCESS_TIMEOUT = 300
CYCLE_SLEEP_TIME = 60
DB_TIMEOUT = 30
MAX_RETRIES = 3

# Global shutdown flag
shutdown_requested = False

def signal_handler(signum, frame):
    global shutdown_requested
    print("🛑 Shutdown signal received. Gracefully shutting down...")
    shutdown_requested = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_dynamic_workers(pair_count=None):
    """
    Calculate optimal worker count based on CPU and memory resources
    """
    try:
        # Get system resources
        cpu_count = multiprocessing.cpu_count()
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        print(f"🖥️ System Resources - CPU: {cpu_count} cores, {cpu_percent:.1f}% usage, Memory: {memory_percent:.1f}% usage")
        
        # Base calculation on CPU cores
        base_workers = max(MIN_WORKERS, cpu_count - 1)  # Leave 1 core free
        
        # Adjust based on CPU load
        if cpu_percent < 30:
            cpu_multiplier = 1.5  # Can use more workers
        elif cpu_percent < 60:
            cpu_multiplier = 1.0  # Normal usage
        elif cpu_percent < 80:
            cpu_multiplier = 0.7  # High usage, reduce workers
        else:
            cpu_multiplier = 0.5  # Very high usage, significantly reduce
        
        # Adjust based on memory usage
        if memory_percent < 50:
            memory_multiplier = 1.3  # Plenty of memory
        elif memory_percent < 70:
            memory_multiplier = 1.0  # Normal memory usage
        elif memory_percent < 85:
            memory_multiplier = 0.8  # High memory usage
        else:
            memory_multiplier = 0.6  # Very high memory usage
        
        # Calculate optimal workers
        optimal_workers = int(base_workers * cpu_multiplier * memory_multiplier)
        
        # Apply limits
        optimal_workers = max(MIN_WORKERS, min(MAX_WORKERS, optimal_workers))
        
        # If pair_count is provided, don't exceed it
        if pair_count is not None:
            optimal_workers = min(optimal_workers, pair_count)
        
        print(f"🔧 Dynamic Workers: {optimal_workers} (Base: {base_workers}, CPU: {cpu_multiplier:.1f}x, Memory: {memory_multiplier:.1f}x)")
        
        return optimal_workers
        
    except Exception as e:
        print(f"⚠️ Error calculating dynamic workers: {e}, using fallback")
        log_error(e, "get_dynamic_workers", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return 4  # Fallback to safe default

def safe_db_call(func, *args, **kwargs):
    """Execute database calls with timeout protection"""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=DB_TIMEOUT)
    except concurrent.futures.TimeoutError:
        print(f"⏰ Database call timeout: {func.__name__}")
        return None
    except Exception as e:
        print(f"❌ Database call error: {func.__name__} - {e}")
        log_error(e, "safe_db_call", func.__name__, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None

def cleanup_cache():
    try:
        import gc
        gc.collect()
    except Exception as e:
        print(f"Error in cleanup_cache: {e}")
        log_error(e, "cleanup_cache", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)


def calculate_heiken_ashi_optimized(df):
    """
    Calculate Heiken Ashi candles efficiently
    """
    try:
        if df is None or df.empty:
            return df
        
        # Ensure ascending time
        df = df.sort_values("time").copy()

        # Pine: ha_close = (o + h + l + c) / 4
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0

        # Pine: ha_open[0] = (open[0] + close[0]) / 2
        ha_open = ha_close.copy()
        ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0

        # Pine: ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2.0

        # Pine: ha_high = max(high, ha_open, ha_close); ha_low = min(low, ha_open, ha_close)
        ha_high = np.maximum(df["high"].values, np.maximum(ha_open.values, ha_close.values))
        ha_low  = np.minimum(df["low"].values,  np.minimum(ha_open.values, ha_close.values))

        df["ha_open"]  = ha_open
        df["ha_close"] = ha_close
        df["ha_high"]  = ha_high
        df["ha_low"]   = ha_low
        df["ha_color"] = np.where(df["ha_close"] >= df["ha_open"], "GREEN", "RED")
        return df
        
    except Exception as e:
        print(f"Error in calculate_heiken_ashi_optimized: {e}")
        log_error(e, "calculate_heiken_ashi_optimized", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return df



def candle_strength(row):
    try:
        body_size = abs(row['ha_close'] - row['ha_open'])
        total_range = row['ha_high'] - row['ha_low']
        
        if total_range == 0:
            return 0
        
        return round(body_size / total_range, 2)
        
    except Exception as e:
        log_error(e, "candle_strength", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return 0

def is_strong_ha_candle_body(row, min_ratio=0.6):
    try:
        body_size = abs(row['ha_close'] - row['ha_open'])
        total_range = row['ha_high'] - row['ha_low']
        
        if total_range == 0:
            return False
        
        return (body_size / total_range) >= min_ratio
        
    except Exception as e:
        log_error(e, "is_strong_ha_candle_body", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return False

def check_trend(df, timeframe):
    try:
        if df is None or df.empty:
            return 'NEUTRAL'
        
        last_close = df['ha_close'].iloc[-1] if 'ha_close' in df.columns else df['close'].iloc[-1]
        ma_20 = df['MA_20'].iloc[-1]
        ma_50 = df['MA_50'].iloc[-1]
        
        if last_close > ma_20 and ma_20 > ma_50:
            return 'UPTREND'
        elif last_close < ma_20 and ma_20 < ma_50:
            return 'DOWNTREND'
        else:
            return 'NEUTRAL'
            
    except Exception as e:
        log_error(e, "check_trend", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return 'NEUTRAL'

def get_cached_signals(symbol, interval):
    try:
        return CalculateSignalsForConfirmation(symbol, interval)
    except Exception as e:
        log_error(e, "get_cached_signals", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None

def is_cache_outdated(last_timestamp, interval, current_utc):
    try:
        if last_timestamp is None:
            return True
        
        time_diff = current_utc - last_timestamp
        
        if interval == '1m':
            return time_diff.total_seconds() > 60
        elif interval == '3m':
            return time_diff.total_seconds() > 180
        elif interval == '5m':
            return time_diff.total_seconds() > 300
        elif interval == '15m':
            return time_diff.total_seconds() > 900
        elif interval == '30m':
            return time_diff.total_seconds() > 1800
        elif interval == '1h':
            return time_diff.total_seconds() > 3600
        elif interval == '2h':
            return time_diff.total_seconds() > 7200
        elif interval == '4h':
            return time_diff.total_seconds() > 14400
        elif interval == '1d':
            return time_diff.total_seconds() > 86400
        else:
            return True
            
    except Exception as e:
        log_error(e, "is_cache_outdated", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return True

def ma_strategy(day_signal, df_4h, last_min_close_price, last_4h_close_price, symbol, NC_checkprice):
    try:
        if df_4h is None or df_4h.empty:
            return None, None, None, None
        
        trend = check_trend(df_4h, 'normal')
        
        if day_signal == 'BUY' and trend == 'UPTREND' and last_min_close_price > last_4h_close_price:
            return 'BUY', df_4h, '4h', 'MA_Strategy'
        elif day_signal == 'SELL' and trend == 'DOWNTREND' and last_min_close_price < last_4h_close_price:
            return 'SELL', df_4h, '4h', 'MA_Strategy'
        
        return None, None, None, None
        
    except Exception as e:
        log_error(e, "ma_strategy", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None, None, None, None

def ma_strategy_no_bb_check(day_signal, df_4h, last_min_close_price, last_4h_close_price, symbol, NC_checkprice):
    try:
        if df_4h is None or df_4h.empty:
            return None, None, None, None
        
        trend = check_trend(df_4h, 'normal')
        
        if day_signal == 'BUY' and trend == 'UPTREND':
            return 'BUY', df_4h, '4h', 'MA_Strategy_No_BB'
        elif day_signal == 'SELL' and trend == 'DOWNTREND':
            return 'SELL', df_4h, '4h', 'MA_Strategy_No_BB'
        
        return None, None, None, None
        
    except Exception as e:
        log_error(e, "ma_strategy_no_bb_check", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None, None, None, None

def check_BB_Status(df_main_interval, action, main_interval, symbol):
    try:
        if df_main_interval is None or df_main_interval.empty:
            return False
        
        last_close = df_main_interval['close'].iloc[-1]
        bb_upper = df_main_interval['BOLL_upper_band'].iloc[-1]
        bb_lower = df_main_interval['BOLL_lower_band'].iloc[-1]
        
        if action == 'BUY':
            return last_close < bb_lower
        elif action == 'SELL':
            return last_close > bb_upper
        
        return False
        
    except Exception as e:
        log_error(e, "check_BB_Status", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return False

def is_tight_consolidation_from_bbands(df, lookback=20, threshold_pct=0.009):
    try:
        if df is None or df.empty or len(df) < lookback:
            return False
        
        bb_width = df['BOLL_upper_band'] - df['BOLL_lower_band']
        avg_bb_width = bb_width.rolling(window=lookback).mean()
        
        current_bb_width = bb_width.iloc[-1]
        avg_width = avg_bb_width.iloc[-1]
        
        if pd.isna(avg_width) or avg_width == 0:
            return False
        
        return (current_bb_width / avg_width) < threshold_pct
        
    except Exception as e:
        log_error(e, "is_tight_consolidation_from_bbands", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return False

def higher_timeframe_macd_median_confirmation(main_df, df_day, df_4h, action, symbol, interval):
    try:
        if main_df is None or main_df.empty:
            return None, None, None, None
        
        if action == 'BUY':
            return 'BUY', main_df, interval, 'Higher_Timeframe_MACD'
        elif action == 'SELL':
            return 'SELL', main_df, interval, 'Higher_Timeframe_MACD'
        
        return None, None, None, None
        
    except Exception as e:
        log_error(e, "higher_timeframe_macd_median_confirmation", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None, None, None, None


def calculate_all_indicators_optimized(df, candle='heiken'):
    """
    Calculate all technical indicators in one optimized pass through the dataframe
    Supports both regular and Heiken Ashi candles
    """
    try:
        if df is None or df.empty:
            return df
        
        # 1. Heiken Ashi calculations (always needed for HA candles)
        if candle == 'heiken':
            df = calculate_heiken_ashi_optimized(df)
        
        # 2. Dynamic OHLC column selection
        if candle == 'heiken':
            open_col = 'ha_open'
            low_col = 'ha_low'
            high_col = 'ha_high'
            close_col = 'ha_close'
        else:
            open_col = 'open'
            low_col = 'low'
            high_col = 'high'
            close_col = 'close'
            df['color'] = np.where(df['close'] >= df['open'], 'GREEN', 'RED')
        
        # 3. Basic indicators (RSI, MACD, Bollinger Bands, Moving Averages)
        df['RSI_9'] = talib.RSI(df[close_col], timeperiod=9)
        df['RSI_14'] = talib.RSI(df[close_col], timeperiod=14)

        df['ema_9'] = talib.EMA(df[close_col], timeperiod=9)
        df['ema_14'] = talib.EMA(df[close_col], timeperiod=14)
        df['ema_100'] = talib.EMA(df[close_col], timeperiod=100)

        
        df['MACD'], df['MACD_Signal'], df['MACD_Histogram'] = talib.MACD(
            df[close_col], fastperiod=12, slowperiod=26, signalperiod=9
        )
        
        df['BOLL_upper_band'], df['BOLL_middle_band'], df['BOLL_lower_band'] = talib.BBANDS(
            df[close_col], timeperiod=20, nbdevup=2, nbdevdn=2, matype=MA_Type.SMA
        )
        df["ha_bb_width"]  = df["BOLL_upper_band"] - df["BOLL_lower_band"]

        # ➕ Calculate BBW (Bollinger Band Width)
        df['BBW'] = (df['BOLL_upper_band'] - df['BOLL_lower_band']) / df['BOLL_middle_band']
        df['BBW_Increasing'] =  df['BBW'] > df['BBW'].shift(1)
        # Compute relative percentile
        df['BBW_PERCENTILE'] = df['BBW'].rolling(100).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1]
        )
                
        df['Volume_MA'] = talib.SMA(df['volume'], timeperiod=20)
        df['Volume_Ratio'] = df['volume'] / df['Volume_MA']
        df['volume_increasing'] = df['volume'].iloc[-1] > df['volume'].iloc[-2]
        

        df['two_pole_macd'], df['two_pole_Signal_Line'], df['two_pole_macdhist'] = talib.MACD(
            df[close_col], fastperiod=12, slowperiod=26, signalperiod=9
        )

        df['lower_two_pole_macd'], df['lower_two_pole_Signal_Line'], df['lower_two_pole_macdhist'] = talib.MACD(
            df[close_col], fastperiod=6, slowperiod=10, signalperiod=16
        )
        df['lower_two_pole_MACD_Cross_Up'] = (df['lower_two_pole_macd'] > df['lower_two_pole_Signal_Line']) & (df['lower_two_pole_macd'].shift(1) <= df['lower_two_pole_Signal_Line'].shift(1))
        df['lower_two_pole_MACD_Cross_Down'] = (df['lower_two_pole_macd'] < df['lower_two_pole_Signal_Line']) & (df['lower_two_pole_macd'].shift(1) >= df['lower_two_pole_Signal_Line'].shift(1))

        df['lower_MACD_CrossOver'] = np.where(
            df['lower_two_pole_MACD_Cross_Up'], 'BUY',
            np.where(
                df['lower_two_pole_MACD_Cross_Down'], 'SELL',
                np.nan
            )
        )

     

        df['two_pole_MACD_Cross_Up'] = (df['two_pole_macd'] > df['two_pole_Signal_Line']) & (df['two_pole_macd'].shift(1) <= df['two_pole_Signal_Line'].shift(1))
        df['two_pole_MACD_Cross_Down'] = (df['two_pole_macd'] < df['two_pole_Signal_Line']) & (df['two_pole_macd'].shift(1) >= df['two_pole_Signal_Line'].shift(1))

        # Detect same-side weakening
        same_side_decreasing = (
            ((df["two_pole_macdhist"] > 0) & (df["two_pole_macdhist"] < df["two_pole_macdhist"].shift(1))) |  # dark green from light green
            ((df["two_pole_macdhist"] < 0) & (df["two_pole_macdhist"] > df["two_pole_macdhist"].shift(1)))    # dark red from light red
        )

        # Combine both conditions
        df["Histogram_Decreasing"] = same_side_decreasing 

        # Assign MACD_COLOR based on two_pole MACD cross and histogram decreasing
        df['MACD_COLOR'] = np.select(
            [
                (df['two_pole_macd'] > df['two_pole_Signal_Line']) & ~df["Histogram_Decreasing"],  # Dark green
                (df['two_pole_macd'] > df['two_pole_Signal_Line']) & df["Histogram_Decreasing"],   # Light green
                (df['two_pole_macd'] < df['two_pole_Signal_Line']) & ~df["Histogram_Decreasing"],  # Dark red
                (df['two_pole_macd'] < df['two_pole_Signal_Line']) & df["Histogram_Decreasing"],   # Light red
            ],
            [
                'DARK_GREEN',
                'LIGHT_GREEN',
                'DARK_RED',
                'LIGHT_RED'
            ],
            default='NONE'
        )


        # Assign BUY/SELL to macd_color_signal based on MACD_COLOR
        # Fix: Use .astype(str) to ensure correct string comparison, and default to 'NONE'
        df['macd_color_signal'] = np.select(
            [
                (df['MACD_COLOR'] == 'DARK_GREEN') | (df['MACD_COLOR'] == 'LIGHT_RED'),
                (df['MACD_COLOR'] == 'LIGHT_GREEN') | (df['MACD_COLOR'] == 'DARK_RED')
            ],
            [
                'BUY',
                'SELL'
            ],
            default='NONE'
        )
        

        # Detect crossovers
        df["bullish_crossover"] = (df["two_pole_macd"].shift(1) < df["two_pole_Signal_Line"].shift(1)) & \
                                (df["two_pole_macd"] > df["two_pole_Signal_Line"])

        df["bearish_crossover"] = (df["two_pole_macd"].shift(1) > df["two_pole_Signal_Line"].shift(1)) & \
                                (df["two_pole_macd"] < df["two_pole_Signal_Line"])

        # Rolling std for volatility-adaptive band
        window = 50
        macd_std = df["two_pole_macd"].rolling(window).std()

        # Thresholds
        k_near = 0.7   # near zero band
        k_far  = 1.7   # opposite side band

        # Buy rules
        # buy_near = (
        #     df["bullish_crossover"]
        #     & (df["two_pole_macd"] > 0)
        #     & (df["two_pole_macd"].abs() <= k_near * macd_std)    # inside 0.5σ
        # )
        df["macd_inside_upper_line"] = (	(df["two_pole_macd"] > 0)
            & (df["two_pole_macd"].abs() <= k_near * macd_std))	# inside 0.5σ
			
        buy_near = (
            df["bullish_crossover"]
            & df["macd_inside_upper_line"]
        )
        
        # buy_far = (
        #     df["bullish_crossover"]
        #     & (df["two_pole_macd"] < 0)
        #     & (df["two_pole_macd"].abs() >= k_far * macd_std)     # beyond 1σ
        # )
        df["macd_below_Last_line"] = 	((df["two_pole_macd"] < 0)
                    & (df["two_pole_macd"].abs() >= k_far * macd_std)  )

        buy_far = ( df["bullish_crossover"] &  df["macd_below_Last_line"] )

        # Sell rules
        # sell_near = (
        #     df["bearish_crossover"]
        #     & (df["two_pole_macd"] < 0)
        #     & (df["two_pole_macd"].abs() <= k_near * macd_std)    # inside 0.5σ
        # )

        df["macd_inside_lower_line"] = 	((df["two_pole_macd"] < 0)
                    & (df["two_pole_macd"].abs() <= k_near * macd_std)  )	
                    
        sell_near = (df["bearish_crossover"] &  df["macd_inside_lower_line"] )
        

        # sell_far = (
        #     df["bearish_crossover"]
        #     & (df["two_pole_macd"] > 0)
        #     & (df["two_pole_macd"].abs() >= k_far * macd_std)     # beyond 1σ
        # )
        df["macd_above_last_line"] = ((df["two_pole_macd"] > 0)
                    & (df["two_pole_macd"].abs() >= k_far * macd_std) )	
                    
        sell_far = ( df["bearish_crossover"] &  df["macd_above_last_line"])        


        # Final signals
        df["accepted_buy"] = buy_near | buy_far
        df["accepted_sell"] = sell_near | sell_far

        # Label as BUY / SELL
        df["MACD_CrossOver"] = np.where(
            df["accepted_buy"], 'BUY',
            np.where(df["accepted_sell"], 'SELL', np.nan)
        )


    # Label EMA trend as 'bullish' or 'bearish'
        df['ema_trend_100_14'] = np.where(
            df['ema_14'] > df['ema_100'],
            'bullish',
            np.where(
                df['ema_14'] < df['ema_100'],
                'bearish',
                'neutral'
            )
        )

        # Signal: bullish if price above ema_14 and trend bullish, bearish if price below ema_14 and trend bearish, else neutral
        df['ema_price_trend_signal'] = np.where(
            (df[close_col] > df['ema_14']) & (df['ema_trend_100_14'] == 'bullish'),
            'bullish',
            np.where(
                (df[close_col] < df['ema_14']) & (df['ema_trend_100_14'] == 'bearish'),
                'bearish',
                'neutral'
            )
        )

        # Fix: Assign trend_direction for each row based on close price vs previous close
        df['price_trend_direction'] = 'SIDEWAYS'
        df.loc[df[close_col] > df[close_col].shift(1), 'price_trend_direction'] = 'UPTREND'
        df.loc[df[close_col] < df[close_col].shift(1), 'price_trend_direction'] = 'DOWNTREND'


        # Zero Lag EMA calculation 
        length = 70
        lag = int((length - 1) / 2)
        zlema_input = df[close_col] + (df[close_col] - df[close_col].shift(lag))
        df['zlema'] = talib.EMA(zlema_input, timeperiod=length)

        # Calculate volatility for Zero Lag bands
        tr1 = df[high_col] - df[low_col]
        tr2 = abs(df[high_col] - df[close_col].shift(1))
        tr3 = abs(df[low_col] - df[close_col].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=length).mean()
        volatility = atr.rolling(window=length * 3).max() * 1.2  # mult = 1.2

        # Calculate trend based on Zero Lag bands (corrected forward fill logic)
        crossover_up = (df[close_col] > df['zlema'] + volatility) & (df[close_col].shift(1) <= df['zlema'].shift(1) + volatility.shift(1))
        crossunder_down = (df[close_col] < df['zlema'] - volatility) & (df[close_col].shift(1) >= df['zlema'].shift(1) - volatility.shift(1))

        df['zlema_trend'] = np.nan  # use NaN so forward fill actually works
        df.loc[crossover_up, 'zlema_trend'] = 1
        df.loc[crossunder_down, 'zlema_trend'] = -1
        df['zlema_trend'] = df['zlema_trend'].ffill().fillna(0)  # fill missing values


        # Zero Lag entry signals
        df['zlema_bullish_entry'] = (
            (df[close_col] > df['zlema']) & (df[close_col].shift(1) <= df['zlema'].shift(1)) &  # crossover
            (df['zlema_trend'] == 1) & (df['zlema_trend'].shift(1) == 1)  # trend continuity
        )

        df['zlema_bearish_entry'] = (
            (df[close_col] < df['zlema']) & (df[close_col].shift(1) >= df['zlema'].shift(1)) &  # crossunder
            (df['zlema_trend'] == -1) & (df['zlema_trend'].shift(1) == -1)  # trend continuity
        )

        # Zero Lag trend change signals
        df['zlema_bullish_trend_signal'] = (df['zlema_trend'] == 1) & (df['zlema_trend'].shift(1) == -1)
        df['zlema_bearish_trend_signal'] = (df['zlema_trend'] == -1) & (df['zlema_trend'].shift(1) == 1)
        
                # Heiken Ashi exit indicators (for Zero Lag strategy)

            
        # Trend + prev HA open
        df['ha_trend_up']   = df[close_col] > df[open_col]
        df['ha_trend_down'] = df[close_col] < df[open_col]
        prev_ha_open = df['ha_open'].shift(1)
        df['price_vs_ha_open'] = df[close_col] > prev_ha_open

        # LL/HH terms
        ll = df['ha_low']  < df['ha_low'].shift(1)   # lower low vs prev HA bar
        hh = df['ha_high'] > df['ha_high'].shift(1)  # higher high vs prev HA bar

        # Raw exits (HA Trend/PrevOpen OR LL/HH)
        df['exit_long_raw']  = df['ha_trend_down'] | (~df['price_vs_ha_open'].fillna(False)) | ll.fillna(False)
        df['exit_short_raw'] = df['ha_trend_up']   | ( df['price_vs_ha_open'].fillna(False)) | hh.fillna(False)

  
        # 6. Consolidation detection
        bb_upper, bb_middle, bb_lower = talib.BBANDS(
            df[close_col],
            timeperiod=3,
            nbdevup=2,
            nbdevdn=2,
            matype=MA_Type.SMA
        )
        
        df['BB_Width'] = bb_upper - bb_lower
        df['bb_flat_market'] = df['BB_Width'] < df['BB_Width'].rolling(window=50).mean()
        
        df['price_range'] = (
            (df[high_col].rolling(window=20).max() - df[low_col].rolling(window=20).min())
            / df[low_col].rolling(window=20).min()
        )
        df['price_range_flat_market'] = df['price_range'] < 0.1
        df['consolidating'] = df['bb_flat_market'] & df['price_range_flat_market']

        # For Breakout 
        # --- ATR calculation ---
        buf_atr = talib.ATR(df["ha_high"], df["ha_low"], df["ha_close"], timeperiod=14)
        # --- Percent buffer (on raw close) ---
        buf_pct = df["ha_close"].values.astype(float) * (0.30 / 100.0)

        # --- BBWidth buffer (on HA bands) ---
        buf_bb = df["ha_bb_width"].values.astype(float) * 0.25

        # Previous HA values
        ha_high_prev = df["ha_high"].shift(1)
        ha_low_prev  = df["ha_low"].shift(1)

        # Per-method triggers
        long_by_atr  = df["ha_high"] > (ha_high_prev + buf_atr)
        long_by_pct  = df["ha_high"] > (ha_high_prev + buf_pct)
        long_by_bb   = df["ha_high"] > (ha_high_prev + buf_bb)

        short_by_atr = df["ha_low"]  < (ha_low_prev - buf_atr)
        short_by_pct = df["ha_low"]  < (ha_low_prev - buf_pct)
        short_by_bb  = df["ha_low"]  < (ha_low_prev - buf_bb)

        # Any method conditions
        df["breakout_long_condition"]  = long_by_atr |  long_by_bb
        df["breakout_short_condition"] = short_by_atr  | short_by_bb

        # --- Unified breakout source (for whichever fired) ---
        df["breakout_source"] = [
            ",".join([src for src, ok in zip(["ATR","BBW"],
                                            [la or sa, lp or sp, lb or sb]) if ok])
            for la, lp, lb, sa, sp, sb in zip(long_by_atr, long_by_pct, long_by_bb,
                                            short_by_atr, short_by_pct, short_by_bb)
        ]
        # 7. Swing highs/lows detection (Optimized)
        window = 5
        
        # Boolean mask for swings
        is_swing_high = df[high_col] == df[high_col].rolling(window*2+1, center=True).max()
        is_swing_low = df[low_col] == df[low_col].rolling(window*2+1, center=True).min()

        df['swing_high'] = is_swing_high
        df['swing_low'] = is_swing_low

        # Store price at swing points for zone calculations, NaN otherwise
        df['swing_high_zone'] = np.where(is_swing_high, df[high_col], np.nan)
        df['swing_low_zone'] = np.where(is_swing_low, df[low_col], np.nan)
        
        # 8. Candle strength calculations (always use Heiken Ashi for strength)
        if candle == 'heiken':
            df['candle_strength'] = df.apply(lambda row: abs(row['ha_close'] - row['ha_open']) / (row['ha_high'] - row['ha_low']) if (row['ha_high'] - row['ha_low']) > 0 else 0, axis=1)
            df['candle_strength'] = df['candle_strength'].round(2)
            
            df['candle_strength_bool'] = df.apply(lambda row: abs(row['ha_close'] - row['ha_open']) / (row['ha_high'] - row['ha_low']) >= 0.6 if (row['ha_high'] - row['ha_low']) > 0 else False, axis=1)
        else:
            # For regular candles, calculate strength using regular OHLC
            df['candle_strength'] = df.apply(lambda row: abs(row['close'] - row['open']) / (row['high'] - row['low']) if (row['high'] - row['low']) > 0 else 0, axis=1)
            df['candle_strength'] = df['candle_strength'].round(2)
            
            df['candle_strength_bool'] = df.apply(lambda row: abs(row['close'] - row['open']) / (row['high'] - row['low']) >= 0.6 if (row['high'] - row['low']) > 0 else False, axis=1)
        
        # 9. Total Change Added After Analysis
        # Calculate the total percentage change from open to close
        df['Total_Change'] = ((df[close_col] - df[open_col]) / df[open_col]) * 100
        # Round the total percentage change
        df['Total_Change'] = df['Total_Change'].round(2)  

        return df
        
    except Exception as e:
        print(f"Error in calculate_all_indicators_optimized: {e}")
        log_error(e, "calculate_all_indicators_optimized", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return df

@performance_monitor("SIGNAL_PROCESSING", "CalculateSignals", machine_id=MAIN_SIGNAL_DETECTOR_ID)
def CalculateSignals(symbol, interval, candle='heiken'):
    try:
        df_trading = fetch_data_safe_for_machines(symbol, interval, 500)
        if df_trading is None or 'time' not in df_trading.columns:
            log_error("df_trading is None or missing 'time' column", "CalculateSignals", symbol)
            return None
        
        df_trading.set_index('time', inplace=True)
        
        # Single optimized function call with candle parameter
        df_trading = calculate_all_indicators_optimized(df_trading, candle)
        
        return df_trading
        
    except Exception as e:
        log_error(e, 'CalculateSignals Error', symbol)
        return None

def CalculateSignalsForConfirmation(symbol, interval):
    try:
        df_trading = fetch_data_safe(symbol, interval, 500)
        if df_trading is None or 'time' not in df_trading.columns:
            return None
        
        df_trading.set_index('time', inplace=True)
        
        # Single optimized function call with candle parameter
        # df_trading = calculate_all_indicators_optimized(df_trading, candle)
        
        return df_trading
        
    except Exception as e:
        log_error(e, "CalculateSignalsForConfirmation", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None


def placeOrder(symbol, interval, action, signalFrom, df,signal_data,candle_type):
    try:
        start_time = time.time()
        print(f"📊 Placing {action} order for {symbol} on {interval} timeframe")
        print(f"📊 Signal from: {signalFrom}")
        print(f"📊 Candle type: {candle_type}")
      
        

        stopPrice = find_last_high(df, action,candle_type)
        last3Swings = get3Swings(df,action)
        candle_time = df.index[-1]

        # if signalFrom == 'Spike':
        #     stopPrice = signal_data['stopPrice']

        
        u_id, error = AssignTradeToMachineLAB(df, symbol, interval, stopPrice, action, signalFrom,last3Swings,candle_type)
        if u_id is None:
            # log_error(Exception(f"Not insert in database: {error}"), 'placeOrder Function', symbol)
            return False

        action = f"{action}_Order_Placed"
        log_signal_processing(
            candel_time=candle_time,  # Fixed typo: should be 'candel_time' as per function signature
            symbol=symbol,
            interval=interval,
            signal_type=action,
            signal_source=signalFrom,
            signal_data=signal_data,
            processing_time_ms=(time.time() - start_time) * 1000,
            machine_id=MAIN_SIGNAL_DETECTOR_ID,
            uid= u_id
        )
        print(f"Order success from place order -- {u_id}")

        return True
        
    except Exception as e:
        log_error(e, 'placeOrder Error', symbol)
        return False


def get3Swings(df, action):
    if df is None or df.empty:
        return []
    # Prefer Heikin values if present
    close_series = df['ha_close'] if 'ha_close' in df.columns else df['close']
    high_series = df['ha_high'] if 'ha_high' in df.columns else df['high']
    low_series = df['ha_low'] if 'ha_low' in df.columns else df['low']

    filtered_close_price_swing_high = close_series[df['swing_high']].tolist()
    filtered_close_price_swing_low = close_series[df['swing_low']].tolist()
    combined_swings = filtered_close_price_swing_high + filtered_close_price_swing_low

    if action == 'BUY':
        previous_price = high_series.iloc[-1]
        filtered = [p for p in combined_swings if p > previous_price]
        closest_3 = sorted(filtered, key=lambda x: abs(x - previous_price))[:3]
        if len(closest_3) == 3 and all(p > previous_price for p in closest_3):
            return closest_3
        return []

    elif action == 'SELL':
        previous_price = low_series.iloc[-1]
        filtered = [p for p in combined_swings if p < previous_price]
        closest_3 = sorted(filtered, key=lambda x: abs(x - previous_price))[:3]
        if len(closest_3) == 3 and all(p < previous_price for p in closest_3):
            return closest_3
        return []

def find_swing_highs_lows(df, window=10):
    """Identify swing highs and lows based on local max/min."""
    try:
        # Use Heikin close when available
        close_series = df['ha_close'] if 'ha_close' in df.columns else df['close']
        df['swing_high'] = close_series == close_series.rolling(window*2+1, center=True).max()
        df['swing_low'] = close_series == close_series.rolling(window*2+1, center=True).min()
        return df
    except Exception as e:
        log_error(e,'find_swing_highs_lows Error', 'swing issue')  
        return df

def get3SwingsByMachines(symbol, interval, action, latest_price):
    df = fetch_data_safe_for_machines(symbol, interval, 1000)
    if df is None or df.empty:
        return []
    # Ensure Heikin columns exist for HA-based swings
    if 'ha_close' not in df.columns or 'ha_open' not in df.columns:
        df = calculate_heiken_ashi_optimized(df)
    df = find_swing_highs_lows(df)
    close_series = df['ha_close'] if 'ha_close' in df.columns else df['close']
    filtered_close_price_swing_high = close_series[df['swing_high']].tolist()
    filtered_close_price_swing_low = close_series[df['swing_low']].tolist()
    combined_swings = filtered_close_price_swing_high + filtered_close_price_swing_low

    if action == 'BUY':
        filtered = [p for p in combined_swings if p > latest_price]
        closest_3 = sorted(filtered, key=lambda x: abs(x - latest_price))[:3]
        if len(closest_3) == 3 and all(p > latest_price for p in closest_3):
            return closest_3
        return []

    elif action == 'SELL':
        filtered = [p for p in combined_swings if p < latest_price]
        closest_3 = sorted(filtered, key=lambda x: abs(x - latest_price))[:3]
        if len(closest_3) == 3 and all(p < latest_price for p in closest_3):
            return closest_3
        return []


def get_high_swings_zones(df_trading):
    try:
        high_zones = build_zones_from_swings(
        [(ts, val) for ts, val in df_trading['swing_high_zone'].dropna().items()],
        kind='high')

        return  get_last_and_higher_highs_desc(high_zones) # return last swing and higher swings in descending order higher high

    except Exception as e:
        print(f"❌ Error in get_last_and_higher_highs_desc: {e}")
        log_error(e, "get_last_and_higher_highs_desc", 'issue in get_last_and_higher_highs_desc')  

def get_last_and_higher_highs_desc(zones_dict):
    try:
        all_points = []
        for zone_list in zones_dict.values():
            all_points.extend(zone_list)

        if not all_points:
            return None, []

        # Sort all by timestamp descending to find the latest swing
        sorted_by_time = sorted(all_points, key=lambda x: x[0], reverse=True)
        last_swing = sorted_by_time[0]
        last_time, last_price = last_swing

        # Get all other swings with a lower price, and sort them by time descending
        higer_swings = sorted(
            [point for point in all_points if point[1] > last_price and point != last_swing],
            key=lambda x: x[0],
            reverse=True
        )

        return last_swing, higer_swings
    
    except Exception as e:
        print(f"❌ Error in get_last_and_higher_highs_desc: {e}")
        log_error(e, "get_last_and_higher_highs_desc", 'issue in get_last_and_higher_highs_desc')    

  
def build_zones_from_swings(raw_list_with_time, threshold=0.005, kind='high'):
    """
    raw_list_with_time: list of (timestamp, price) tuples
    kind: 'high' or 'low'
    Returns: dict of {label: [(timestamp, price), ...]}
    """
    try:
        if not raw_list_with_time:
            return {}

        # Sort by price (not timestamp), high first if kind='high'
        values = sorted(raw_list_with_time, key=lambda x: x[1], reverse=(kind == 'high'))

        clusters = []
        current = [values[0]]
        for v in values[1:]:
            if abs(v[1] - current[-1][1]) <= threshold:
                current.append(v)
            else:
                clusters.append(current)
                current = [v]
        clusters.append(current)

        labels = ['Most Highest', 'Highest', 'High'] if kind == 'high' else ['Most Lowest', 'Lowest', 'Low']

        zones = {}
        for i, grp in enumerate(clusters):
            label = labels[i] if i < len(labels) else f'Zone_{i}'
            zones[label] = grp

        return zones
    except Exception as e:
        print(f"❌ Error in build_zones_from_swings: {e}")
        log_error(e, "build_zones_from_swings", 'issue in build_zones_from_swings')


def get_low_swings_zones(df_trading):
    try:
        low_zones = build_zones_from_swings(
        [(ts, val) for ts, val in df_trading['swing_low_zone'].dropna().items()],
        kind='low')

        return get_last_and_lower_lows_desc(low_zones) # return last swing and low swings in descending order  lower low

    except Exception as e:
        print(f"❌ Error in get_last_and_higher_highs_desc: {e}")
        log_error(e, "get_last_and_higher_highs_desc", 'issue in get_last_and_higher_highs_desc')          

def get_last_and_lower_lows_desc(zones_dict):
    try:
        all_points = []
        for zone_list in zones_dict.values():
            all_points.extend(zone_list)

        if not all_points:
            return None, []

        # Sort all by timestamp descending to find the latest swing
        sorted_by_time = sorted(all_points, key=lambda x: x[0], reverse=True)
        last_swing = sorted_by_time[0]
        last_time, last_price = last_swing

        # Get all other swings with a lower price, and sort them by time descending
        lower_swings = sorted(
            [point for point in all_points if point[1] < last_price and point != last_swing],
            key=lambda x: x[0],
            reverse=True
        )

        return last_swing, lower_swings
    except Exception as e:
        print(f"❌ Error in get_last_and_lower_lows_desc: {e}")
        log_error(e, "get_last_and_lower_lows_desc", 'issue in get_last_and_lower_lows_desc')


def find_last_high(data, orderType, candle_type):
    if candle_type == 'heiken':
        if 'ha_high' not in data.columns or 'ha_open' not in data.columns or 'ha_close' not in data.columns:
            data = calculate_all_indicators_optimized(data, 'heiken')
        high_col = 'ha_high'
        low_col = 'ha_low'
        open_col = 'ha_open'
        close_col = 'ha_close'
    else:
        high_col = 'high'
        low_col = 'low'
        open_col = 'open'
        close_col = 'close'

    try:
        if orderType == 'BUY':
            # Find last red candle: close < open
            last_red = data[data[close_col] < data[open_col]].iloc[-1]
            last_red_low = last_red[low_col]
            stop_price = last_red_low - (last_red_low * 0.002)  # subtract small buffer
            return stop_price

        elif orderType == 'SELL':
            # Find last green candle: close > open
            last_green = data[data[close_col] > data[open_col]].iloc[-1]
            last_green_high = last_green[high_col]
            stop_price = last_green_high + (last_green_high * 0.002)  # add small buffer
            return stop_price

        else:
            return -1

    except Exception as e:
        log_error(e, "find_last_stop_price", "Stop Price Issue")
        return -1

def process_candle_patterns_and_update_row(symbol, intervals, calculate_indicators_func, update_row_func, tf=None, candle_process="both"):
    """
    Loops over ['regular', 'heiken'] candle patterns, fetches signals, calculates indicators, and updates the last row dict.
    - symbol: trading symbol
    - intervals: list of intervals to fetch (e.g., ['15m', '1m', '30m', '1h', '2h', '4h', '1d'])
    - get_signals_func: function to fetch signals (e.g., get_cached_signals)
    - calculate_indicators_func: function to calculate indicators (e.g., calculate_all_indicators_optimized)
    - update_row_func: function to update the last row dict with all indicator values
    - candle_process: 'both' (default) to process both 'regular' and 'heiken', or 'heiken' to process only 'heiken'
    Returns a dict: {candle_pattern: (indicator_dfs, last_row_dict)}
    """
    # if candle_process == "both":
    #     candle_types = ['regular', 'heiken']
    # else:
    candle_types = ['heiken']

    results = {}
    for candle in candle_types:
        dfs = {}
        for interval in intervals:
            df = get_cached_signals(symbol, interval)
            if df is None or df.empty:
                dfs[interval] = None
            else:
                dfs[interval] = calculate_indicators_func(df, candle)
        # Only proceed if all required dfs are present
        if all(dfs[iv] is not None and not dfs[iv].empty for iv in intervals):
            last_row_dict = update_row_func(dfs, candle, tf)
            results[candle] = (dfs, last_row_dict)
    return results


def update_row_with_indicators(dfs, candle, tf=None):
    """
    Returns a dict with the last row (as a dict) for every interval in dfs.
    Example: {'1m': {...}, '3m': {...}, ...}
    """
    last_rows = {}
    for interval, df in dfs.items():
        if df is not None and not df.empty:
            last_rows[interval] = df.iloc[-1].to_dict()
            if tf is not None and interval == tf:
                last_rows['df'] = df
        else:
            last_rows[interval] = None
    # Optionally, you can add a 'candle_type' field for clarity
    last_rows['candle_type'] = candle
    return last_rows

def process_candle_patterns_for_symbol(symbol, interval=None, candle_process="both"):
    """
    Wrapper for process_candle_patterns_and_update_row with default intervals and functions.
    Usage: results = process_candle_patterns_for_symbol(symbol)
    """
    return process_candle_patterns_and_update_row(
        symbol,
        ['1m','3m','5m','15m', '30m', '1h', '2h', '4h', '1d'],      
        calculate_all_indicators_optimized,
        update_row_with_indicators,
        tf=interval,
        candle_process=candle_process
    )

def check_active_squeeze_trend(df, active_squeeze_trend):
    if active_squeeze_trend == 'UPTREND':
        low_series = df['ha_low'] if 'ha_low' in df.columns else df['low']
        if low_series.iloc[-1] < df['BOLL_lower_band'].iloc[-1]:
            return False

    elif active_squeeze_trend == 'DOWNTREND':
        high_series = df['ha_high'] if 'ha_high' in df.columns else df['high']
        if high_series.iloc[-1] > df['BOLL_upper_band'].iloc[-1]:
            return False
    return True

def check_if_record_exists(symbol: str, timeframe: str = '3m', strategy: str = 'ProGap'):
    """
    Checks which candle type ('heiken' or 'regular') is available for a given symbol and strategy.
    Returns one of: 'both', 'heiken', 'regular', or 'None' if both types are already running.
    """
    try:
        check_both = 'both'

        if check_running_trade_exists(symbol, timeframe, strategy, 'heiken'):
            print(f"⏭️ Skipping {symbol} on {timeframe} - Running trade exists for {strategy} (heiken)")
            check_both = 'regular'  # Only 'regular' is available

        if check_running_trade_exists(symbol, timeframe, strategy, 'regular'):
            print(f"⏭️ Skipping {symbol} on {timeframe} - Running trade exists for {strategy} (regular)")
            if check_both == 'regular':
                check_both = 'None'  # Both are running
            else:
                check_both = 'heiken'  # Only 'heiken' is available

        if check_both == 'None':
            print(f"⏭️ Skipping {symbol} on {timeframe} - Running trade exists for {strategy} (both types)")

        return check_both

    except Exception as e:
        print(f"❌ Error checking candle availability for {symbol} on {timeframe}: {e}")
        return 'error'

def BBUpLowBand(pair_info,check_exists = False):
    # Add null checks for all required fields
    if not pair_info or not isinstance(pair_info, dict):
        print(f"❌ Invalid pair_info provided to BBUpLowBand")
        return None, None, None, None, None, None
    
    symbol = pair_info.get('pair')

    
    # Check if essential fields are missing
    if not symbol:
        print(f"❌ Missing symbol in pair_info for BBUpLowBand")
        return None, None, None, None, None, None
    try:

        if check_exists:
            result = check_if_record_exists(symbol, '3m', 'ProGap')

            if result in ['None', None, 'error']:
                # Both candle types are already running — skip or return
                print(f"⏭️ Skipping {symbol} on 3m - Both candle types are running or an error occurred.")
                return None, None, None, None, None, None

           
        start_time = time.time()
        results = process_candle_patterns_for_symbol(symbol, '3m') 
        for candle, (dfs, all_last_rows) in results.items():
            row_1m = all_last_rows.get('1m')
            row_3m = all_last_rows.get('3m')
            row_5m = all_last_rows.get('5m')
            row_15m = all_last_rows.get('15m')
            row_30m = all_last_rows.get('30m')
            row_1h = all_last_rows.get('1h')
            row_2h = all_last_rows.get('2h')
            row_4h = all_last_rows.get('4h')
            row_1d = all_last_rows.get('1d')
            candle_type = all_last_rows.get('candle_type')

            print(f"Processing {symbol} - 3m for BBUpLowBand : {candle_type}")

            if check_exists and candle_type != result and result != 'both':
                 return None, None, None, None, None, None

            # Access the full dataframe for the requested interval ('3m')
            df_3m = all_last_rows.get('df')

            if not row_3m or not row_1m or not row_30m or not row_1h or not row_2h or not row_4h or not row_1d:
                continue

            current_candle_time = row_3m.get('time', datetime.now(timezone.utc))
            record_exists = check_signal_processing_log_exists(symbol, '3m', candle_type, current_candle_time)

            # If record exists, skip processing and return
            if record_exists:
                return None, None, None, None, None, None

            signal_data = {
                   
                   'pair_info': pair_info,
                    'all_last_rows': {k: v for k, v in all_last_rows.items() if k != 'df'}
                }

            log_signal_processing(
                candel_time=current_candle_time,
                symbol=symbol,
                interval='3m',
                signal_type='CHECKING',
                signal_source='BBUpLowBand',
                signal_data=signal_data,
                processing_time_ms=(time.time() - start_time) * 1000,
                machine_id=MAIN_SIGNAL_DETECTOR_ID
            )

            def all_not_none(*args):
                return all(x is not None for x in args)

            # Extract needed variables for buy/sell logic
            # Use the full dataframe (df_3m) to get previous and prior candle values instead of None
            last_low_price_3m = row_3m.get('ha_low', row_3m.get('low'))
            last_high_price_3m = row_3m.get('ha_high', row_3m.get('high'))

            # Get previous and prior rows from df_3m if available
            previous_row_3m = None
            prior_row_3m = None
            if df_3m is not None and len(df_3m) >= 2:
                previous_row_3m = df_3m.iloc[-2]
            if df_3m is not None and len(df_3m) >= 3:
                prior_row_3m = df_3m.iloc[-3]

            previous_low_price_3m = (
                previous_row_3m['ha_low'] if previous_row_3m is not None and 'ha_low' in previous_row_3m else
                previous_row_3m['low'] if previous_row_3m is not None and 'low' in previous_row_3m else
                None
            )
            prior_low_price_3m = (
                prior_row_3m['ha_low'] if prior_row_3m is not None and 'ha_low' in prior_row_3m else
                prior_row_3m['low'] if prior_row_3m is not None and 'low' in prior_row_3m else
                None
            )
            previous_high_price_3m = (
                previous_row_3m['ha_high'] if previous_row_3m is not None and 'ha_high' in previous_row_3m else
                previous_row_3m['high'] if previous_row_3m is not None and 'high' in previous_row_3m else
                None
            )
            prior_high_price_3m = (
                prior_row_3m['ha_high'] if prior_row_3m is not None and 'ha_high' in prior_row_3m else
                prior_row_3m['high'] if prior_row_3m is not None and 'high' in prior_row_3m else
                None
            )
            previous_candle_color_3m = (
                previous_row_3m['ha_color'] if previous_row_3m is not None and 'ha_color' in previous_row_3m else
                previous_row_3m['color'] if previous_row_3m is not None and 'color' in previous_row_3m else
                None
            )
            prior_candle_color_3m = (
                prior_row_3m['ha_color'] if prior_row_3m is not None and 'ha_color' in prior_row_3m else
                prior_row_3m['color'] if prior_row_3m is not None and 'color' in prior_row_3m else
                None
            )
            bb_lower_band_3m = row_3m.get('BOLL_lower_band')
            bb_upper_band_3m = row_3m.get('BOLL_upper_band')
            bb_middle_band_3m = row_3m.get('BOLL_middle_band')
            ema_9_3m = row_3m.get('ema_9')
            ema_14_3m = row_3m.get('ema_14')
            last_close_price_3m = row_3m.get('ha_close', row_3m.get('close'))
            bb_lower_band_3m = row_3m.get('BOLL_lower_band')
            last_candle_color_3m = row_3m.get('ha_color', row_3m.get('color'))
            macd_color_signal_3m = row_3m.get('macd_color_signal')
            macd_cross_over_3m = row_3m.get('MACD_CrossOver')
            macd_color_signal_1m = row_1m.get('macd_color_signal')
            macd_cross_over_1m = row_1m.get('MACD_CrossOver')
            macd_color_signal_30m = row_30m.get('macd_color_signal')
            macd_cross_over_30m = row_30m.get('MACD_CrossOver')
            price_trend_direction_5m = row_5m.get('price_trend_direction')
            last_close_price_1m = row_1m.get('ha_close', row_1m.get('close'))
            is_volume_increasing = all(tf.get('volume_increasing') for tf in [row_5m, row_15m])


            if (
                all_not_none(
                    last_low_price_3m, previous_low_price_3m,
                    bb_lower_band_3m, bb_middle_band_3m, bb_upper_band_3m,
                    ema_9_3m, ema_14_3m, last_close_price_3m,
                    last_candle_color_3m, macd_color_signal_3m,
                    previous_candle_color_3m, prior_candle_color_3m
                ) 
                     and (
                    last_low_price_3m < bb_lower_band_3m
                    or previous_low_price_3m < bb_lower_band_3m
                    or prior_low_price_3m < bb_lower_band_3m

                )
                and last_close_price_3m < bb_middle_band_3m
                and last_candle_color_3m == 'GREEN'
                and (
                    previous_candle_color_3m == 'RED'
                    or prior_candle_color_3m == 'RED'
                )
                and (
                    macd_color_signal_3m == 'BUY'
                    or macd_cross_over_3m == 'BUY'
                )

                and (
                    macd_color_signal_1m == 'BUY'
                    or macd_cross_over_1m == 'BUY'
                )
                and (
                    macd_color_signal_30m == 'BUY'
                    or macd_cross_over_30m == 'BUY'
                )
                and (
                    price_trend_direction_5m == 'UPTREND'
                ) and (
                    is_volume_increasing)
            ):
                print(f"🟢 {symbol} Buy Signal")
                
                # Update status and log buy signal
                if 'status' in df_3m.columns:
                    df_3m['status'] = 'Buy Signal Found'
                
                # Calculate stop loss and take profit
                current_price = last_close_price_1m 

                # Update signal data with current price for buy signal
                signal_data['price'] = current_price
                
                
                log_signal_processing(
                    candel_time=current_candle_time,
                    symbol=symbol,
                    interval='3m',
                    signal_type='BUY',
                    signal_source='BBUpLowBand',
                    signal_data=signal_data,
                    processing_time_ms=(time.time() - start_time) * 1000,
                    machine_id=MAIN_SIGNAL_DETECTOR_ID
                )
                return df_3m,'BUY',signal_data,candle_type,'BBUpLowBand','3m'

            elif (
                all_not_none(
                    last_high_price_3m, previous_high_price_3m,
                    bb_upper_band_3m, bb_middle_band_3m, bb_lower_band_3m,
                    ema_9_3m, ema_14_3m, last_close_price_3m,
                    last_candle_color_3m, macd_color_signal_3m,
                    previous_candle_color_3m, prior_candle_color_3m
                )
                and (
                    last_high_price_3m > bb_upper_band_3m
                    or previous_high_price_3m > bb_upper_band_3m
                    or prior_high_price_3m > bb_upper_band_3m
                )
                and (last_close_price_3m > bb_middle_band_3m)
                and (last_candle_color_3m == 'RED')
                and (
                    previous_candle_color_3m == 'GREEN'
                    or prior_candle_color_3m == 'GREEN'
                )
                and (
                    macd_color_signal_3m == 'SELL'
                    or macd_cross_over_3m == 'SELL'
                )
                and (
                    price_trend_direction_5m == 'DOWNTREND'
                ) and (is_volume_increasing)
            ):
                print(f"🔴 {symbol} Sell Signal")
                # Update status and log sell signal
                if 'status' in df_3m.columns:
                    df_3m['status'] = 'Sell Signal Found'
                # Calculate stop loss and take profit
                current_price = last_close_price_1m
                # Update signal data with current price for sell signal
                signal_data['price'] = current_price
                log_signal_processing(
                    candel_time=current_candle_time,
                    symbol=symbol,
                    interval='3m',
                    signal_type='SELL',
                    signal_source='BBUpLowBand',
                    signal_data=signal_data,
                    processing_time_ms=(time.time() - start_time) * 1000,
                    machine_id=MAIN_SIGNAL_DETECTOR_ID
                )
                return df_3m,'SELL',signal_data,candle_type,'BBUpLowBand','3m' 


        return None,None,None,None,None,None

    except Exception as e:
        log_error(e, 'BBUpLowBand Error', symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)   
        return None,None,None,None,None,None        

def BollingerBandBreakout(pair_info,check_exists = False):
    # Add null checks for all required fields
    if not pair_info or not isinstance(pair_info, dict):
        print(f"❌ Invalid pair_info provided to BollingerBandBreakout")
        return None, None, None, None, None, None
    
    symbol = pair_info.get('pair')
    active_squeeze_trend = pair_info.get('active_squeeze_trend')
    
    # Check if essential fields are missing
    if not symbol:
        print(f"❌ Missing symbol in pair_info for BollingerBandBreakout")
        return None, None, None, None, None, None
    
    try:

        if check_exists:
            result = check_if_record_exists(symbol, '15m', 'IMACD')

            if result in ['None', None, 'error']:
                # Both candle types are already running — skip or return
                print(f"⏭️ Skipping {symbol} on 3m - Both candle types are running or an error occurred.")
                return None, None, None, None, None, None
        
        
        start_time = time.time()
        results = process_candle_patterns_for_symbol(symbol, '15m')
        
        for candle, (dfs, all_last_rows) in results.items():
            row_1m = all_last_rows.get('1m')
            row_3m = all_last_rows.get('3m')
            row_5m = all_last_rows.get('5m')
            row_15m = all_last_rows.get('15m')
            row_30m = all_last_rows.get('30m')
            row_1h = all_last_rows.get('1h')
            row_2h = all_last_rows.get('2h')
            row_4h = all_last_rows.get('4h')
            row_1d = all_last_rows.get('1d')
            candle_type = all_last_rows.get('candle_type')

            print(f"Processing {symbol} - 15m for BollingerBand Breakout: {candle_type}")
            
            if check_exists and candle_type != result and result != 'both':
                 return None, None, None, None, None, None

            # Access the full dataframe for the requested interval ('15m')
            df_15m = all_last_rows.get('df')

            if not row_15m or not row_1m or not row_30m or not row_1h or not row_2h or not row_4h or not row_1d:
                continue

            current_candle_time = row_15m.get('time', datetime.now(timezone.utc))
            record_exists = check_signal_processing_log_exists(symbol, '15m', candle_type, current_candle_time)

            # If record exists, skip processing and return
            if record_exists:
                return None, None, None, None, None, None

            signal_data = {
                   
                   'pair_info': pair_info,
                    'all_last_rows': {k: v for k, v in all_last_rows.items() if k != 'df'}
                }

            log_signal_processing(
                candel_time=current_candle_time,
                symbol=symbol,
                interval='15m',
                signal_type='CHECKING',
                signal_source='BollingerBandBreakout',
                signal_data=signal_data,
                processing_time_ms=(time.time() - start_time) * 1000,
                machine_id=MAIN_SIGNAL_DETECTOR_ID
            )

            def all_not_none(*args):
                return all(x is not None for x in args)

            # Extract needed variables for buy/sell logic
            # Use the full dataframe (df_15m) to get previous and prior candle values instead of None
            last_low_price_15m = row_15m.get('ha_low', row_15m.get('low'))
            last_high_price_15m = row_15m.get('ha_high', row_15m.get('high'))

            # Get previous and prior rows from df_15m if available
            previous_row_15m = None
            prior_row_15m = None
            if df_15m is not None and len(df_15m) >= 2:
                previous_row_15m = df_15m.iloc[-2]
            if df_15m is not None and len(df_15m) >= 3:
                prior_row_15m = df_15m.iloc[-3]

            previous_low_price_15m = (
                previous_row_15m['ha_low'] if previous_row_15m is not None and 'ha_low' in previous_row_15m else
                previous_row_15m['low'] if previous_row_15m is not None and 'low' in previous_row_15m else
                None
            )
            prior_low_price_15m = (
                prior_row_15m['ha_low'] if prior_row_15m is not None and 'ha_low' in prior_row_15m else
                prior_row_15m['low'] if prior_row_15m is not None and 'low' in prior_row_15m else
                None
            )
            previous_high_price_15m = (
                previous_row_15m['ha_high'] if previous_row_15m is not None and 'ha_high' in previous_row_15m else
                previous_row_15m['high'] if previous_row_15m is not None and 'high' in previous_row_15m else
                None
            )
            prior_high_price_15m = (
                prior_row_15m['ha_high'] if prior_row_15m is not None and 'ha_high' in prior_row_15m else
                prior_row_15m['high'] if prior_row_15m is not None and 'high' in prior_row_15m else
                None
            )

            bb_middle_band_15m = row_15m.get('BOLL_middle_band')
            bb_upper_band_15m = row_15m.get('BOLL_upper_band')
            ema_9_15m = row_15m.get('ema_9')
            ema_14_15m = row_15m.get('ema_14')
            last_close_price_15m = row_15m.get('ha_close', row_15m.get('close'))
            bb_lower_band_15m = row_15m.get('BOLL_lower_band')
            last_candle_color_15m = row_15m.get('ha_color', row_15m.get('color'))
            macd_color_signal_15m = row_15m.get('macd_color_signal')
            macd_color_signal_5m = row_5m.get('macd_color_signal')

            macd_cross_over_15m = row_15m.get('MACD_CrossOver')
            is_still_squeeze = row_15m.get('BBW')

            previous_candle_color_15m = (
                previous_row_15m['ha_color'] if previous_row_15m is not None and 'ha_color' in previous_row_15m else
                previous_row_15m['color'] if previous_row_15m is not None and 'color' in previous_row_15m else
                None
            )
            prior_candle_color_15m = (
                prior_row_15m['ha_color'] if prior_row_15m is not None and 'ha_color' in prior_row_15m else
                prior_row_15m['color'] if prior_row_15m is not None and 'color' in prior_row_15m else
                None
            )

            last_close_price_1m = row_1m.get('ha_close', row_1m.get('close'))
            last_close_price_2h = row_2h.get('ha_close', row_2h.get('close'))
            price_trend_direction_2h = row_2h.get('price_trend_direction')
            macd_color_signal_1m = row_1m.get('macd_color_signal')
            macd_cross_over_1m = row_1m.get('MACD_CrossOver')
            macd_color_signal_30m = row_30m.get('macd_color_signal')
            macd_cross_over_30m = row_30m.get('MACD_CrossOver')

            # Now you can use df_15m (full dataframe) and row_15m (last row) as needed

                      # Buy Signal
            if (
                all_not_none(
                    last_low_price_15m, previous_low_price_15m, bb_middle_band_15m,
                    ema_9_15m, ema_14_15m, last_close_price_15m, bb_lower_band_15m,
                    last_candle_color_15m, macd_color_signal_15m, macd_cross_over_15m,
                    last_close_price_1m, last_close_price_2h,
                    macd_color_signal_1m, macd_cross_over_1m,
                    macd_color_signal_30m, macd_cross_over_30m
                )
                and (active_squeeze_trend == 'UPTREND' or active_squeeze_trend == 'NO_TREND')
                # and (
                #     last_low_price_15m < bb_lower_band_15m
                #     # or last_low_price_15m < ema_9_15m
                #     # or last_low_price_15m < ema_14_15m
                #     or previous_low_price_15m < bb_lower_band_15m
                #     # or previous_low_price_15m < ema_9_15m
                #     # or previous_low_price_15m < ema_14_15m
                #     or prior_low_price_15m < bb_lower_band_15m
                #     # or prior_low_price_15m < ema_9_15m
                #     # or prior_low_price_15m < ema_14_15m 
                # )

                and (
                    last_low_price_15m < bb_middle_band_15m
                    or last_low_price_15m < ema_9_15m
                    or last_low_price_15m < ema_14_15m
                    or previous_low_price_15m < bb_middle_band_15m
                    or previous_low_price_15m < ema_9_15m
                    or previous_low_price_15m < ema_14_15m
                    or prior_low_price_15m < bb_middle_band_15m
                    or prior_low_price_15m < ema_9_15m
                    or prior_low_price_15m < ema_14_15m 
                )
                and last_close_price_15m > bb_middle_band_15m and last_close_price_15m < bb_upper_band_15m
                and last_candle_color_15m == 'GREEN'
                and (
                    previous_candle_color_15m == 'RED'
                    or prior_candle_color_15m == 'RED'
                )
                and (
                    macd_color_signal_15m == 'BUY'
                    or macd_cross_over_15m == 'BUY'
                )
                and (
                    last_candle_color_15m == 'GREEN'
                    or previous_candle_color_15m == 'GREEN'
                    or prior_candle_color_15m == 'GREEN'
                )
                and (
                    last_close_price_1m is not None
                    and last_close_price_2h is not None
                    and isinstance(last_close_price_1m, (int, float))
                    and isinstance(last_close_price_2h, (int, float))
                    and price_trend_direction_2h == 'UPTREND'
                )
                and (
                    macd_color_signal_1m == 'BUY'
                    or macd_cross_over_1m == 'BUY'
                )
                and (
                    macd_color_signal_30m == 'BUY'
                    or macd_cross_over_30m == 'BUY'
                )
                and (macd_color_signal_5m == 'BUY')
            ):
                print(f"🟢 {symbol} Buy Signal")
                
                # Update status and log buy signal
                if 'status' in df_15m.columns:
                    df_15m['status'] = 'Buy Signal Found'
                
                # Calculate stop loss and take profit
                current_price = last_close_price_1m 

                # Update signal data with current price for buy signal
                signal_data['price'] = current_price
                
                log_signal_processing(
                    candel_time=current_candle_time,
                    symbol=symbol,
                    interval='15m',
                    signal_type='BUY',
                    signal_source='BollingerBandBreakout',
                    signal_data=signal_data,
                    processing_time_ms=(time.time() - start_time) * 1000,
                    machine_id=MAIN_SIGNAL_DETECTOR_ID
                )
                update_squeeze_status_if_changed(symbol, False,is_still_squeeze,True,'UPTREND')
                return df_15m,'BUY',signal_data,candle_type,'IMACD','15m'

            # Sell Signal
            elif (
                all_not_none(
                    last_high_price_15m, previous_high_price_15m, bb_middle_band_15m,
                    ema_9_15m, ema_14_15m, last_close_price_15m, bb_lower_band_15m,
                    last_candle_color_15m, macd_color_signal_15m, macd_cross_over_15m,
                    last_close_price_1m, last_close_price_2h,
                    macd_color_signal_1m, macd_cross_over_1m,
                    macd_color_signal_30m, macd_cross_over_30m
                ) and (active_squeeze_trend == 'DOWNTREND' or active_squeeze_trend == 'NO_TREND')
                # and (
                #     last_high_price_15m > bb_upper_band_15m    
                #     # or last_high_price_15m > ema_9_15m
                #     # or last_high_price_15m > ema_14_15m
                #     or previous_high_price_15m > bb_upper_band_15m
                #     # or previous_high_price_15m > ema_9_15m
                #     # or previous_high_price_15m > ema_14_15m
                #     or prior_high_price_15m > bb_upper_band_15m
                #     # or prior_high_price_15m > ema_9_15m
                #     # or prior_high_price_15m > ema_14_15m 
                # )

                and (
                    last_high_price_15m > bb_middle_band_15m    
                    or last_high_price_15m > ema_9_15m
                    or last_high_price_15m > ema_14_15m
                    or previous_high_price_15m > bb_middle_band_15m
                    or previous_high_price_15m > ema_9_15m
                    or previous_high_price_15m > ema_14_15m
                    or prior_high_price_15m > bb_middle_band_15m
                    or prior_high_price_15m > ema_9_15m
                    or prior_high_price_15m > ema_14_15m 
                )
                and last_close_price_15m < bb_middle_band_15m and last_close_price_15m > bb_lower_band_15m
                and last_candle_color_15m == 'RED'
                and (
                    previous_candle_color_15m == 'GREEN'
                    or prior_candle_color_15m == 'GREEN'
                )
                and (
                    macd_color_signal_15m == 'SELL'
                    or macd_cross_over_15m == 'SELL'
                )
                and (
                    isinstance(last_close_price_1m, (int, float)) and
                    isinstance(last_close_price_2h, (int, float)) and
                    price_trend_direction_2h == 'DOWNTREND'
                )
                and (
                    macd_color_signal_1m == 'SELL'
                    or macd_cross_over_1m == 'SELL'
                )
                and (
                    macd_color_signal_30m == 'SELL'
                    or macd_cross_over_30m == 'SELL'
                )
                 and (macd_color_signal_5m == 'SELL')
            ):
                print(f"🟢 {symbol} Sell Signal")
                
                # Update status and log sell signal
                if 'status' in df_15m.columns:
                    df_15m['status'] = 'Sell Signal Found'
                
                # Calculate stop loss and take profit
                current_price = last_close_price_1m

                # Update signal data with current price for sell signal
                signal_data['price'] = current_price
                
                
                log_signal_processing(
                    current_candle_time,
                    symbol=symbol,
                    interval='15m',
                    signal_type='SELL',
                    signal_source='BollingerBandBreakout',
                    signal_data=signal_data,
                    processing_time_ms=(time.time() - start_time) * 1000,
                    machine_id=MAIN_SIGNAL_DETECTOR_ID
                )
                update_squeeze_status_if_changed(symbol, False, is_still_squeeze, True, 'DOWNTREND')
                return df_15m, 'SELL', signal_data, candle_type, 'IMACD','15m'
                
        return None, None, None, None, None, None
    except Exception as e:
        print(f"❌ Error processing squeezed pair {symbol}: {e}")
        log_error(e, "BollingerBandBreakout", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None,None,None,None,None,None




def getSpikeDetect(df,interval):
        
        curr_row_change =  abs(df['Total_Change'].iloc[-1])
        previous_row_change = abs(df['Total_Change'].iloc[-2])
        prior_row_change = abs(df['Total_Change'].iloc[-3])

        spike_threshold = get_spike_threshold(interval)

        if previous_row_change >= spike_threshold or curr_row_change >= spike_threshold or prior_row_change >= spike_threshold:
            return True  # Spike detected
        else:
            return False # No spike

def get_spike_threshold(interval):
    # Adjust threshold % based on interval
    thresholds = {
        "1m": 1.0,
        "3m": 1.5,
        "5m": 2.0,
        "15m": 2.5,
        "30m": 3.0,
        "1h": 4.0,
		"2h": 4.5,
        "4h": 5.0,
        "1d" : 6.0
    }
    return thresholds.get(interval)  # Default to 3% if not found



def MacdCrossOver(pair_info,check_exists = False):
    # Add null checks for all required fields
    if not pair_info or not isinstance(pair_info, dict):
        print(f"❌ Invalid pair_info provided to MacdCrossOver")
        return None, None, None, None, None, None
    
    symbol = pair_info.get('pair')
    
    # Check if essential fields are missing
    if not symbol:
        print(f"❌ Missing symbol in pair_info for MacdCrossOver")
        return None, None, None, None, None, None
    
    try:

        start_time = time.time()
        interval = ['4h','2h','1h','30m','15m']
        for interval in interval:
            # Check if running trade already exists for this symbol, interval, and signal source

            if check_exists:
                result = check_if_record_exists(symbol, interval, 'Kicker')

                if result in ['None', None, 'error']:
                    # Both candle types are already running — skip or return
                    print(f"⏭️ Skipping {symbol} on 3m - Both candle types are running or an error occurred.")
                    return None, None, None, None, None, None


            results = process_candle_patterns_for_symbol(symbol, interval)
            for candle, (dfs, all_last_rows) in results.items():
                row_1m = all_last_rows.get('1m')
                row_3m = all_last_rows.get('3m')
                row_5m = all_last_rows.get('5m')
                row_15m = all_last_rows.get('15m')
                row_30m = all_last_rows.get('30m')
                row_1h = all_last_rows.get('1h')
                row_2h = all_last_rows.get('2h')
                row_4h = all_last_rows.get('4h')
                row_1d = all_last_rows.get('1d')
                candle_type = all_last_rows.get('candle_type')

                print(f"Processing {symbol} - {interval} for MACD CrossOver: {candle_type}")
                
                if check_exists and candle_type != result and result != 'both':
                    continue

                # Access the full dataframe for the requested interval ('3m')
                df = all_last_rows.get('df')

                spike = getSpikeDetect(df,interval)
                if spike :
                    return None, None, None, None, None, None

                if interval == '4h':
                    main_row = row_4h
                    confirmation_row = row_1d
                    bbw_check_trend = 0.8
                    bbw_check_reverse = 0.26
                    bbw_check_narrow = 0.08
                    
                elif interval == '2h':
                    main_row = row_2h
                    confirmation_row = row_1d
                    bbw_check_trend = 0.5
                    bbw_check_reverse = 0.22 
                    bbw_check_narrow = 0.06                   

                elif interval == '1h':
                    main_row = row_1h
                    confirmation_row = row_1d
                    bbw_check_trend = 0.4
                    bbw_check_reverse = 0.11
                    bbw_check_narrow = 0.05

                elif interval == '30m':
                    main_row = row_30m
                    confirmation_row = row_4h
                    bbw_check_trend = 0.3
                    bbw_check_reverse = 0.09
                    bbw_check_narrow = 0.04

                elif interval == '15m':
                    main_row = row_15m
                    confirmation_row = row_2h
                    bbw_check_trend = 0.2
                    bbw_check_reverse = 0.07       
                    bbw_check_narrow = 0.02           

    

                if not row_3m or not row_1m or not row_30m or not row_1h or not row_2h or not row_4h or not row_1d:
                    continue


                current_candle_time = main_row.get('time', datetime.now(timezone.utc))
                # record_exists = check_signal_processing_log_exists(symbol, interval, candle_type, current_candle_time)

                signal_data = {
                   
                   'pair_info': pair_info,
                    'all_last_rows': {k: v for k, v in all_last_rows.items() if k != 'df'}
                }

                # if not record_exists:
                #     log_signal_processing(
                #         candel_time=current_candle_time,
                #         symbol=symbol,
                #         interval=interval,
                #         signal_type='CHECKING',
                #         signal_source='MACD_CrossOver',
                #         signal_data=signal_data,
                #         processing_time_ms=(time.time() - start_time) * 1000,
                #         machine_id=MAIN_SIGNAL_DETECTOR_ID
                #     )

                def all_not_none(*args):
                    return all(x is not None for x in args)
                
                macd_cross_over = main_row.get('MACD_CrossOver')
                lower_macd_cross_over = main_row.get('lower_MACD_CrossOver')
                ema_trend_100_14 = main_row.get('ema_trend_100_14')
                candle_strength = main_row.get('candle_strength')
                bbw = main_row.get('BBW')
                bbw_percentile = main_row.get('BBW_PERCENTILE')
                price_trend_direction = confirmation_row.get('price_trend_direction')
                price_trend_direction_15m = row_15m.get('price_trend_direction')
                price_trend_direction_30m = row_30m.get('price_trend_direction')
                bbw_increasing = confirmation_row.get('BBW_Increasing')
                last_close_price_1m = row_1m.get('ha_close', row_1m.get('close'))
                is_still_squeeze = row_15m.get('BBW')
                macd_color_signal_15m = row_15m.get('macd_color_signal')
                macd_color_signal_5m = row_5m.get('macd_color_signal')
                higher_interval_macd_color_signal = confirmation_row.get('macd_color_signal')


                macd_cross_over_15m = row_15m.get('MACD_CrossOver')
                macd_color_signal_1m = row_1m.get('macd_color_signal')
                macd_cross_over_1m = row_1m.get('MACD_CrossOver')
                macd_color_signal_30m = row_30m.get('macd_color_signal')
                macd_cross_over_30m = row_30m.get('MACD_CrossOver')

                macd_above_last_line_15m = row_15m.get('macd_above_last_line')
                macd_below_Last_line_15m = row_15m.get('macd_below_Last_line')





                timeframes = [row_5m, row_15m, row_30m, row_1h, row_2h, row_4h, row_1d]

                lower_macd_cross_over_SELL = any(
                    tf.get('MACD_CrossOver') != 'SELL' for tf in timeframes
                )
                lower_macd_cross_over_BUY = any(
                    tf.get('MACD_CrossOver') != 'BUY' for tf in timeframes
                )
                  # Zero Lag indicators

                # Swing levels for stop loss
                swing_high = main_row.get('swing_high_zone')
                swing_low = main_row.get('swing_low_zone')

                zlema_bullish_entry = main_row.get('zlema_bullish_entry')
                zlema_bearish_entry = main_row.get('zlema_bearish_entry')
                zlema_bullish_trend_signal = main_row.get('zlema_bullish_trend_signal')
                zlema_bearish_trend_signal = main_row.get('zlema_bearish_trend_signal')
                zlema_trend = main_row.get('zlema_trend')

                  # Entry conditions (same as Pine Script)
                long_condition = (
                    (zlema_bullish_entry or zlema_bullish_trend_signal) and 
                    all_not_none(zlema_bullish_entry, zlema_bullish_trend_signal, last_close_price_1m) and
                    not macd_above_last_line_15m
                )
                
                short_condition = (
                    (zlema_bearish_entry or zlema_bearish_trend_signal) and 
                    all_not_none(zlema_bearish_entry, zlema_bearish_trend_signal, last_close_price_1m) and
                    not macd_below_Last_line_15m
                )

                all_price_direction = (
                'UPTREND' if all(tf.get('price_trend_direction') == 'UPTREND' for tf in [confirmation_row, row_15m, row_30m])
                else 'DOWNTREND' if all(tf.get('price_trend_direction') == 'DOWNTREND' for tf in [confirmation_row, row_15m, row_30m])
                else 'HOLD'  )

                

                if all_price_direction == 'UPTREND' and  lower_macd_cross_over_SELL and macd_color_signal_15m == 'BUY' and macd_color_signal_5m == 'BUY' and (
                    (macd_cross_over == 'BUY' and (bbw < bbw_check_trend or bbw_percentile < 0.2) and bbw_increasing and ema_trend_100_14 == 'bullish') or
                    (lower_macd_cross_over == 'BUY' and ema_trend_100_14 == 'bearish' and (bbw > bbw_check_reverse or bbw_percentile > 0.1) and candle_strength > 0.6 )
                     ):

                    print(f"🟢 {symbol} Buy Signal")
                    # Update status and log buy signal

                    
                    # Calculate stop loss and take profit
                    current_price = last_close_price_1m 

                    # Update signal data with current price for buy signal
                    signal_data['price'] = current_price
                    
                    log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=interval,
                        signal_type='BUY',
                        signal_source='MACD_CrossOver',
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )
                    return df,'BUY',signal_data,candle_type,'Kicker',interval
                    
                elif all_price_direction == 'DOWNTREND'  and lower_macd_cross_over_BUY and macd_color_signal_15m == 'SELL' and macd_color_signal_5m == 'SELL' and (
                    (macd_cross_over == 'SELL' and (bbw < bbw_check_trend or bbw_percentile < 0.2) and bbw_increasing and ema_trend_100_14 == 'bearish') or
                    (lower_macd_cross_over == 'SELL' and ema_trend_100_14 == 'bullish' and (bbw > bbw_check_reverse or bbw_percentile > 0.1) and candle_strength > 0.6 )
                     ):
                    print(f"🔴 {symbol} Sell Signal")
                    # Update status and log sell signal
                    if 'status' in df.columns:
                        df['status'] = 'Sell Signal Found'
                        
                    # Calculate stop loss and take profit
                    current_price = last_close_price_1m 
                    signal_data['price'] = current_price
                    log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=interval,
                        signal_type='SELL',
                        signal_source='MACD_CrossOver',
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )
                    return df,'SELL',signal_data,candle_type,'Kicker',interval
                    

                if long_condition and macd_color_signal_15m == 'BUY' and macd_color_signal_5m == 'BUY' and higher_interval_macd_color_signal == 'BUY' :
                    print(f"🟢 {symbol} Zero Lag Buy Signal on {interval}")
                    
                    # Calculate stop loss (same as Pine Script)
                    current_price = last_close_price_1m
                    stop_price = None
                    if swing_low is not None:
                        stop_price = swing_low * (1 - 1.5 / 100)  # 1.5% below swing low
                    
                    # Update signal data with current price and stop loss
                    signal_data['price'] = current_price
                    signal_data['stopPrice'] = stop_price
                    signal_data['strategy_type'] = 'ZeroLag_Trend'
                    
                    log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=interval,
                        signal_type='BUY',
                        signal_source='ZeroLag_Trend_Strategy',
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )
                    return df,'BUY',signal_data,candle_type,'Spike',interval
                    
                elif short_condition and macd_color_signal_15m == 'SELL' and macd_color_signal_5m == 'SELL' and higher_interval_macd_color_signal == 'SELL' :
                    print(f"🔴 {symbol} Zero Lag Sell Signal on {interval}")
                    
                    # Calculate stop loss (same as Pine Script)
                    current_price = last_close_price_1m
                    stop_price = None
                    if swing_high is not None:
                        stop_price = swing_high * (1 + 1.5 / 100)  # 1.5% above swing high
                    
                    # Update signal data with current price and stop loss
                    signal_data['price'] = current_price
                    signal_data['stopPrice'] = stop_price
                    signal_data['strategy_type'] = 'ZeroLag_Trend'
                    
                    log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=interval,
                        signal_type='SELL',
                        signal_source='ZeroLag_Trend_Strategy',
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )
                    return df,'SELL',signal_data,candle_type,'Spike',interval

                # elif df["breakout_long_condition"].iloc[-1] and bbw < bbw_check_narrow and not macd_above_last_line_15m:
                #     print(f"🟢 {symbol} Buy Signal")
                #     # Update status and log buy signal

                    
                #     # Calculate stop loss and take profit
                #     current_price = last_close_price_1m 

                #     # Update signal data with current price for buy signal
                #     signal_data['price'] = current_price
                #     signal_data["breakout_source"] = df["breakout_source"].iloc[-1]
                    
                #     log_signal_processing(
                #         candel_time=current_candle_time,
                #         symbol=symbol,
                #         interval=interval,
                #         signal_type='BUY',
                #         signal_source='ProGap',
                #         signal_data=signal_data,
                #         processing_time_ms=(time.time() - start_time) * 1000,
                #         machine_id=MAIN_SIGNAL_DETECTOR_ID
                #     )
                #     return df,'BUY',signal_data,candle_type,'ProGap',interval

                # elif df["breakout_short_condition"].iloc[-1] and bbw < bbw_check_narrow and not macd_below_Last_line_15m:
                #     print(f"🔴 {symbol} Sell Signal")
                #     # Update status and log sell signal

                    
                #     # Calculate stop loss and take profit
                #     current_price = last_close_price_1m 

                #     # Update signal data with current price for sell signal
                #     signal_data['price'] = current_price
                #     signal_data["breakout_source"] = df["breakout_source"].iloc[-1]
                    
                #     log_signal_processing(
                #         candel_time=current_candle_time,
                #         symbol=symbol,
                #         interval=interval,
                #         signal_type='SELL',
                #         signal_source='ProGap',
                #         signal_data=signal_data,
                #         processing_time_ms=(time.time() - start_time) * 1000,
                #         machine_id=MAIN_SIGNAL_DETECTOR_ID
                #     )
  
                #     return df,'SELL',signal_data,candle_type,'ProGap',interval


        return None, None, None, None, None, None

    except Exception as e:  
        log_error(e, "MacdCrossOver Error", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None, None, None, None, None, None

# def ZeroLagTrendStrategy(pair_info,check_exists = False):
#     # Add null checks for all required fields
#     if not pair_info or not isinstance(pair_info, dict):
#         print(f"❌ Invalid pair_info provided to ZeroLagTrendStrategy")
#         return None, None, None, None, None, None
    
#     symbol = pair_info.get('pair')
#     active_squeeze = pair_info.get('active_squeeze')
#     active_squeeze_trend = pair_info.get('active_squeeze_trend')
#     overall_trend_RC = pair_info.get('overall_trend_RC')
#     overall_trend_percentage_RC = pair_info.get('overall_trend_percentage_RC')
#     overall_trend_HC = pair_info.get('overall_trend_HC')
#     overall_trend_percentage_HC = pair_info.get('overall_trend_percentage_HC')
#     overall_trend_4h = pair_info.get('overall_trend_4h')
#     overall_trend_percentage_4h = str(pair_info.get('overall_trend_percentage_4h', 0))
#     overall_trend_1h = pair_info.get('overall_trend_1h')
#     overall_trend_percentage_1h = str(pair_info.get('overall_trend_percentage_1h', 0))
#     volume_1h = str(pair_info.get('volume_1h', 0))
    
#     # Check if essential fields are missing
#     if not symbol:
#         print(f"❌ Missing symbol in pair_info for ZeroLagTrendStrategy")
#         return None, None, None, None, None, None
    
#     try:
#         start_time = time.time()
#         interval = ['15m','30m','1h','2h','4h']  # Zero Lag strategy timeframes
#         for interval in interval:
#             # Check if running trade already exists for this symbol, interval, and signal source

#             if check_exists:
#                 result = check_if_record_exists(symbol, interval, 'Spike')  

#                 if result in ['None', None, 'error']:
#                     # Both candle types are already running — skip or return
#                     print(f"⏭️ Skipping {symbol} on 3m - Both candle types are running or an error occurred.")
#                     return None, None, None, None, None, None


#             results = process_candle_patterns_for_symbol(symbol, interval)
#             for candle, (dfs, all_last_rows) in results.items():
#                 row_1m = all_last_rows.get('1m')
#                 row_3m = all_last_rows.get('3m')
#                 row_5m = all_last_rows.get('5m')
#                 row_15m = all_last_rows.get('15m')
#                 row_30m = all_last_rows.get('30m')
#                 row_1h = all_last_rows.get('1h')
#                 row_2h = all_last_rows.get('2h')
#                 row_4h = all_last_rows.get('4h')
#                 row_1d = all_last_rows.get('1d')
#                 candle_type = all_last_rows.get('candle_type')

#                 print(f"Processing {symbol} - {interval} for Zero Lag Trend Strategy: {candle_type}")


#                 if check_exists and candle_type != result and result != 'both':
#                     continue

#                 # Access the full dataframe for the requested interval
#                 df = all_last_rows.get('df')
#                 if interval == '15m':
#                     main_row = row_15m
#                     confirmation_row = row_30m
#                 elif interval == '30m':
#                     main_row = row_30m
#                     confirmation_row = row_1h
#                 elif interval == '1h':
#                     main_row = row_1h
#                     confirmation_row = row_2h
#                 elif interval == '2h':
#                     main_row = row_2h
#                     confirmation_row = row_4h
#                 elif interval == '4h':
#                     main_row = row_4h
#                     confirmation_row = row_1d

#                 if not row_3m or not row_1m or not row_30m or not row_1h or not row_2h or not row_4h or not row_1d:
#                     continue

#                 current_candle_time = main_row.get('time', datetime.now(timezone.utc))
#                 record_exists = check_signal_processing_log_exists(symbol, interval, candle_type, current_candle_time)



#                 signal_data = {
#                     'active_squeeze_trend': active_squeeze_trend,
#                     'overall_trend_RC': overall_trend_RC,
#                     'overall_trend_percentage_RC': overall_trend_percentage_RC,
#                     'overall_trend_HC': overall_trend_HC,
#                     'overall_trend_percentage_HC': overall_trend_percentage_HC,
#                     'overall_trend_4h': overall_trend_4h,
#                     'overall_trend_percentage_4h': overall_trend_percentage_4h,
#                     'overall_trend_1h': overall_trend_1h,
#                     'overall_trend_percentage_1h': overall_trend_percentage_1h,
#                     'volume_1h': volume_1h,
#                     'all_last_rows': {k: v for k, v in all_last_rows.items() if k != 'df'}
#                 }
#                 if not record_exists:

#                     log_signal_processing(
#                         candel_time=current_candle_time,
#                         symbol=symbol,
#                         interval=interval,
#                         signal_type='CHECKING',
#                         signal_source='ZeroLag_Trend_Strategy',
#                         signal_data=signal_data,
#                         processing_time_ms=(time.time() - start_time) * 1000,
#                         machine_id=MAIN_SIGNAL_DETECTOR_ID
#                     )

#                 def all_not_none(*args):
#                     return all(x is not None for x in args)
                
#                 # Zero Lag indicators
#                 zlema_bullish_entry = main_row.get('zlema_bullish_entry')
#                 zlema_bearish_entry = main_row.get('zlema_bearish_entry')
#                 zlema_bullish_trend_signal = main_row.get('zlema_bullish_trend_signal')
#                 zlema_bearish_trend_signal = main_row.get('zlema_bearish_trend_signal')
#                 zlema_trend = main_row.get('zlema_trend')
                
#                 # Heiken Ashi indicators for exit
#                 ha_trend_up = main_row.get('ha_trend_up')
#                 ha_trend_down = main_row.get('ha_trend_down')
#                 price_vs_ha_open = main_row.get('price_vs_ha_open')
                
#                 # Swing levels for stop loss
#                 swing_high = main_row.get('swing_high_zone')
#                 swing_low = main_row.get('swing_low_zone')
                
#                 last_close_price_1m = row_1m.get('close', row_1m.get('ha_close'))

#                 # Entry conditions (same as Pine Script)
#                 long_condition = (
#                     (zlema_bullish_entry or zlema_bullish_trend_signal) and 
#                     all_not_none(zlema_bullish_entry, zlema_bullish_trend_signal, last_close_price_1m)
#                 )
                
#                 short_condition = (
#                     (zlema_bearish_entry or zlema_bearish_trend_signal) and 
#                     all_not_none(zlema_bearish_entry, zlema_bearish_trend_signal, last_close_price_1m)
#                 )

#                 macd_color_signal_15m = row_15m.get('macd_color_signal')
#                 macd_color_signal_5m = row_5m.get('macd_color_signal')

#                 if long_condition and macd_color_signal_15m == 'BUY' and macd_color_signal_5m == 'BUY':
#                     print(f"🟢 {symbol} Zero Lag Buy Signal on {interval}")
                    
#                     # Calculate stop loss (same as Pine Script)
#                     current_price = last_close_price_1m
#                     stop_price = None
#                     if swing_low is not None:
#                         stop_price = swing_low * (1 - 1.5 / 100)  # 1.5% below swing low
                    
#                     # Update signal data with current price and stop loss
#                     signal_data['price'] = current_price
#                     signal_data['stop_loss'] = stop_price
#                     signal_data['strategy_type'] = 'ZeroLag_Trend'
                    
#                     log_signal_processing(
#                         candel_time=current_candle_time,
#                         symbol=symbol,
#                         interval=interval,
#                         signal_type='BUY',
#                         signal_source='ZeroLag_Trend_Strategy',
#                         signal_data=signal_data,
#                         processing_time_ms=(time.time() - start_time) * 1000,
#                         machine_id=MAIN_SIGNAL_DETECTOR_ID
#                     )
#                     return df,'BUY',signal_data,candle_type,'Spike',interval    
                    
#                 elif short_condition and macd_color_signal_15m == 'SELL' and macd_color_signal_5m == 'SELL':
#                     print(f"🔴 {symbol} Zero Lag Sell Signal on {interval}")
                    
#                     # Calculate stop loss (same as Pine Script)
#                     current_price = last_close_price_1m
#                     stop_price = None
#                     if swing_high is not None:
#                         stop_price = swing_high * (1 + 1.5 / 100)  # 1.5% above swing high
                    
#                     # Update signal data with current price and stop loss
#                     signal_data['price'] = current_price
#                     signal_data['stop_loss'] = stop_price
#                     signal_data['strategy_type'] = 'ZeroLag_Trend'
                    
#                     log_signal_processing(
#                         candel_time=current_candle_time,
#                         symbol=symbol,
#                         interval=interval,
#                         signal_type='SELL',
#                         signal_source='ZeroLag_Trend_Strategy',
#                         signal_data=signal_data,
#                         processing_time_ms=(time.time() - start_time) * 1000,
#                         machine_id=MAIN_SIGNAL_DETECTOR_ID
#                     )
#                     return df,'SELL',signal_data,candle_type,'Spike',interval  
                 

#         return None, None, None, None, None, None

#     except Exception as e:  
#         log_error(e, "ZeroLagTrendStrategy Error", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
#         return None, None, None, None, None, None


def process_squeezed_pair_with_signal(pair_info):
    """
    Orchestrates signal checks for a squeezed pair. Tries BollingerBandStrategy, then MacdCrossOver, then BBUpLowBand.
    Does not update squeeze status directly.
    """
    try:
        symbol = pair_info['pair']
        # 1. Try main squeeze strategy
        
        # result = BollingerBandStrategy(pair_info)   
        # if result is not None and isinstance(result, tuple) and len(result) == 6:
        #     df, action, signal_data, candle_type, signalFrom, interval = result
        #     if action == 'BUY' or action =='SELL':
        #         placeOrder(symbol, interval, action, signalFrom, df, signal_data, candle_type)
        #         return
        # 2. Try MACD crossover strategy
        result = MacdCrossOver(pair_info,check_exists = True)
        if result is not None and isinstance(result, tuple) and len(result) == 6:
            df, action, signal_data, candle_type, signalFrom, interval = result
            if action == 'BUY' or action =='SELL':
                placeOrder(symbol, interval, action, signalFrom, df, signal_data, candle_type)
                return
        # result = ZeroLagTrendStrategy(pair_info,check_exists = True)
        # if result is not None and isinstance(result, tuple) and len(result) == 6:
        #     df, action, signal_data, candle_type, signalFrom, interval = result
        #     if action == 'BUY' or action =='SELL':
        #         placeOrder(symbol, interval, action, signalFrom, df, signal_data, candle_type)
        #         return

    except Exception as e:
        log_error(e, "process_squeezed_pair_with_signal", pair_info.get('pair', 'unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)


def BollingerBandStrategy(pair_info):
    try:
        symbol = pair_info['pair']
        active_squeeze = pair_info['active_squeeze']
        active_squeeze_trend = pair_info['active_squeeze_trend']
        print(f"🎯 Processing squeezed pair with signals: {symbol}")
        
        # Only read squeeze status from pair_info, do not calculate or update
        # Remove is_still_squeeze calculation and update_squeeze_status_if_changed calls
        # Only call BollingerBandBreakout with the squeeze status from pair_info
        
        if active_squeeze:    
            if check_active_squeeze_trend(None, active_squeeze_trend):  # Pass None or appropriate df if needed
                print(f"🎯 Start Checking for Signal 2h (Trend) - 30m:(MACD) - 15m:(Boolinger Band Middle) {symbol}")
                df,action,signal_data,candle_type,signalFrom,interval = BollingerBandBreakout(pair_info,check_exists = True)
                return df,action,signal_data,candle_type,signalFrom,interval
            else:
                print(f"🟢 {symbol} no longer in Trend")
                return None,None,None,None,None,None
        else:
            df,action,signal_data,candle_type,signalFrom,interval = BBUpLowBand(pair_info,check_exists = True)
            print(f"🟢 {symbol} in squeeze (no update)")
            return df,action,signal_data,candle_type,'ProGap',interval


        
    except Exception as e:
        print(f"❌ Error processing squeezed pair {symbol}: {e}")
        log_error(e, "BollingerBandStrategy", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None,None,None,None,None,None

def process_non_squeezed_pair_with_signal(pair_info):
    try:
        symbol = pair_info['pair']     
        # result = BollingerBandStrategy(pair_info)
        # if result is not None and isinstance(result, tuple) and len(result) == 6:
        #     df, action, signal_data, candle_type, signalFrom, interval   = result
        #     if action == 'BUY' or action =='SELL':              
        #         placeOrder(symbol, interval, action, signalFrom, df, signal_data, candle_type)   

        result = MacdCrossOver(pair_info,check_exists = True)
        if result is not None and isinstance(result, tuple) and len(result) == 6:
            df, action, signal_data, candle_type, signalFrom, interval = result
            if action == 'BUY' or action =='SELL':              
                placeOrder(symbol, interval, action, signalFrom, df, signal_data, candle_type)  

        # result = ZeroLagTrendStrategy(pair_info,check_exists = True)
        # if result is not None and isinstance(result, tuple) and len(result) == 6:
        #     df, action, signal_data, candle_type, signalFrom, interval = result
        #     if action == 'BUY' or action =='SELL':              
        #         placeOrder(symbol, interval, action, signalFrom, df, signal_data, candle_type)  
        
    except Exception as e:
        print(f"❌ Error processing squeezed pair {pair_info.get('pair', 'unknown')}: {e}")
        log_error(e, "process_squeezed_pair_with_signal", pair_info.get('pair', 'unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)



def start_squeezed_pairs_loop(offset=0, limit=10):
    consecutive_crashes = 0
    max_consecutive_crashes = MAX_CONSECUTIVE_CRASHES
    
    # Run only one cycle instead of infinite loop
    try:
        cycle_start_time = time.time()
        print(f"🎯 Fetching squeezed pairs from DB (offset: {offset}, limit: {limit})...")
        
        # Use the new paginated function
        squeezed_pairs = safe_db_call(fetch_squeezed_pairs_from_db_paginated, offset, limit)
        
        if squeezed_pairs is None:
            print("⚠️ Database timeout or error. Exiting cycle.")
            return
        
        if not squeezed_pairs:
            print("⚠️ No squeezed pairs found. Exiting cycle.")
            return
        
        print(f"🎯 Processing {len(squeezed_pairs)} squeezed pairs with ProcessPoolExecutor...")
        
        #max_workers = get_dynamic_workers(len(squeezed_pairs))
        max_workers = 6
        
        if consecutive_crashes >= max_consecutive_crashes:
            print(f"🔄 Using ThreadPoolExecutor with {max_workers} workers (fallback due to crashes).")
            executor_class = concurrent.futures.ThreadPoolExecutor
        else:
            print(f"🚀 Using ProcessPoolExecutor with {max_workers} workers for squeezed pairs.")
            executor_class = concurrent.futures.ProcessPoolExecutor
        
        batch_start_time = time.time()
        with executor_class(max_workers=max_workers) as executor:
            futures = [executor.submit(process_squeezed_pair_with_signal, pair_info) for pair_info in squeezed_pairs]
            
            completed_count = 0
            error_count = 0
            crash_count = 0
            
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                try:
                    future.result(timeout=PROCESS_TIMEOUT)
                    completed_count += 1
                except concurrent.futures.TimeoutError:
                    print(f"⏰ Timeout for squeezed pair {squeezed_pairs[i-1].get('pair', 'unknown')} after 5 minutes")
                    error_count += 1
                except Exception as e:
                    error_msg = str(e)
                    if "terminated abruptly" in error_msg:
                        crash_count += 1
                        print(f"💥 Process crash for squeezed pair {squeezed_pairs[i-1].get('pair', 'unknown')}: {e}")
                    else:
                        print(f"❌ Error in process for squeezed pair {squeezed_pairs[i-1].get('pair', 'unknown')}: {e}")
                    log_error(e, "process_squeezed_pairs_loop_future", squeezed_pairs[i-1].get('pair', 'unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)
                    error_count += 1
            
            print(f"📊 Squeezed pairs batch completed: {completed_count} successful, {error_count} errors, {crash_count} crashes")
            
            # Log batch processing performance
            total_processing_time_ms = int((time.time() - batch_start_time) * 1000)
            log_batch_processing(
                batch_type="SQUEEZED_PAIRS",
                batch_size=len(squeezed_pairs),
                successful_count=completed_count,
                error_count=error_count,
                crash_count=crash_count,
                total_processing_time_ms=total_processing_time_ms,
                executor_type=executor_class.__name__,
                worker_count=max_workers,
                machine_id=MAIN_SIGNAL_DETECTOR_ID
            )
            
            if crash_count > 0:
                consecutive_crashes += 1
                print(f"⚠️ Consecutive crashes: {consecutive_crashes}/{max_consecutive_crashes}")
            else:
                consecutive_crashes = 0
        
        total_processing_time = time.time() - batch_start_time
        print(f"📊 Total processing time: {total_processing_time:.2f}s for {len(squeezed_pairs)} squeezed pairs")
        print(f"📊 Average time per squeezed pair: {total_processing_time/len(squeezed_pairs):.2f}s")
        
        total_cycle_time = time.time() - cycle_start_time
        print(f'⏰ Total cycle time: {total_cycle_time:.2f}s')
        print('✅ Squeezed pairs cycle completed')
        
    except Exception as e:
            print(f"❌ Error in squeezed pairs loop: {e}")
            log_error(e, "process_squeezed_pairs_loop", "main_loop", machine_id=MAIN_SIGNAL_DETECTOR_ID)
    
    print("🛑 Squeezed pairs loop stopped.")

def start_non_squeezed_pairs_loop(offset=0, limit=10):
    consecutive_crashes = 0
    max_consecutive_crashes = MAX_CONSECUTIVE_CRASHES
    
    # Run only one cycle instead of infinite loop
    try:
        cycle_start_time = time.time()
        print(f"🧠 Fetching non-squeezed pairs from DB (offset: {offset}, limit: {limit})...")
        
        # Use the new paginated function
        pairs_info = safe_db_call(fetch_non_squeezed_pairs_from_db_paginated, offset, limit)

        if pairs_info is None:
            print("⚠️ Database timeout or error. Exiting cycle.")
            return

        if not pairs_info:
            print("⚠️ No non-squeezed pairs found. Exiting cycle.")
            return

        print(f"🧠 Running PriceAction for {len(pairs_info)} non-squeezed pairs...")

        #max_workers = get_dynamic_workers(len(pairs_info))
        max_workers = 12
        
        if consecutive_crashes >= max_consecutive_crashes:
            print(f"🔄 Using ThreadPoolExecutor with {max_workers} workers (fallback due to crashes).")
            executor_class = concurrent.futures.ThreadPoolExecutor
        else:
            print(f"🚀 Using ProcessPoolExecutor with {max_workers} workers (reduced for stability).")
            executor_class = concurrent.futures.ProcessPoolExecutor

        batch_start_time = time.time()
        with executor_class(max_workers=max_workers) as executor:
            futures = [executor.submit(process_non_squeezed_pair_with_signal, pair_info) for pair_info in pairs_info]
            
            completed_count = 0
            error_count = 0
            crash_count = 0
            
            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                try:
                    future.result(timeout=PROCESS_TIMEOUT)
                    completed_count += 1
                except concurrent.futures.TimeoutError:
                    print(f"⏰ Timeout for pair {pairs_info[i-1].get('pair', 'unknown')} after 5 minutes")
                    error_count += 1
                except Exception as e:
                    error_msg = str(e)
                    if "terminated abruptly" in error_msg:
                        crash_count += 1
                        print(f"💥 Process crash for pair {pairs_info[i-1].get('pair', 'unknown')}: {e}")
                    else:
                        print(f"❌ Error in process for pair {pairs_info[i-1].get('pair', 'unknown')}: {e}")
                    log_error(e, "start_non_squeezed_pairs_loop_future", pairs_info[i-1].get('pair', 'unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)
                    error_count += 1
            
            print(f"📊 Non-squeezed batch completed: {completed_count} successful, {error_count} errors, {crash_count} crashes")
            
            # Log batch processing performance
            total_processing_time_ms = int((time.time() - batch_start_time) * 1000)
            log_batch_processing(
                batch_type="NON_SQUEEZED_PAIRS",
                batch_size=len(pairs_info),
                successful_count=completed_count,
                error_count=error_count,
                crash_count=crash_count,
                total_processing_time_ms=total_processing_time_ms,
                executor_type=executor_class.__name__,
                worker_count=max_workers,
                machine_id=MAIN_SIGNAL_DETECTOR_ID
            )
            
            if crash_count > 0:
                consecutive_crashes += 1
                print(f"⚠️ Consecutive crashes: {consecutive_crashes}/{max_consecutive_crashes}")
            else:
                consecutive_crashes = 0

        total_processing_time = time.time() - batch_start_time
        print(f"📊 Total processing time: {total_processing_time:.2f}s for {len(pairs_info)} non-squeezed pairs")
        print(f"📊 Average time per pair: {total_processing_time/len(pairs_info):.2f}s")

        cleanup_cache()
        total_cycle_time = time.time() - cycle_start_time
        print(f'⏰ Total cycle time: {total_cycle_time:.2f}s')
        print('✅ Non-squeezed pairs cycle completed')
        
    except Exception as e:
        print(f"❌ Error in start_non_squeezed_pairs_loop: {e}")
        log_error(e, "start_non_squeezed_pairs_loop", "main_loop", machine_id=MAIN_SIGNAL_DETECTOR_ID)
    
    print("🛑 Non-squeezed pairs loop stopped.")

def main():
    global shutdown_requested
    
    try:
        print("🚀 Starting Trading Bot with ProcessPoolExecutor Architecture...")
        print("📊 Pairs will be fetched from database and processed with ProcessPoolExecutor")

        print("🎯 Starting Squeezed Pairs Processing Loop...")
        squeezed_thread = threading.Thread(target=start_squeezed_pairs_loop, daemon=True)
        squeezed_thread.start()
        
        print("🧠 Starting Non-Squeezed Pairs Processing Loop...")
        non_squeezed_thread = threading.Thread(target=start_non_squeezed_pairs_loop, daemon=True)
        non_squeezed_thread.start()

        # System health monitoring counter
        health_check_counter = 0
        
        while not shutdown_requested:
            time.sleep(1)
            health_check_counter += 1
            
            # Log system health every 5 minutes (300 seconds)
            if health_check_counter >= 300:
                log_system_health(machine_id=MAIN_SIGNAL_DETECTOR_ID)
                health_check_counter = 0
            
        print("🛑 Waiting for threads to finish...")
        squeezed_thread.join(timeout=10)
        non_squeezed_thread.join(timeout=10)
        print("🛑 Shutdown complete.")

    except KeyboardInterrupt:
        print("🛑 Shutdown requested by user.")
        shutdown_requested = True
    except Exception as e:
        log_error(e, 'main', 'Fatal crash', machine_id=MAIN_SIGNAL_DETECTOR_ID)
        print(f"❌ Fatal error in main loop: {e}")
        shutdown_requested = True
        time.sleep(5)
        sys.exit(1)

def update_squeeze_status_if_changed(symbol, squeeze_status, squeeze_value, active_squeeze, active_squeeze_trend):
    current = fetch_single_pair_from_db(symbol)
    if current is None:
        update_squeeze_status(symbol, squeeze_status, squeeze_value, active_squeeze, active_squeeze_trend)
        return
    # Only update if any value is different
    if (
        current.get('active_squeeze') != active_squeeze or
        current.get('squeeze_value') != squeeze_value or
        current.get('active_squeeze_trend') != active_squeeze_trend
    ):
        update_squeeze_status(symbol, squeeze_status, squeeze_value, active_squeeze, active_squeeze_trend)

if __name__ == "__main__":
    main() 
