import pandas as pd
import numpy as np
import talib
from talib._ta_lib import MA_Type
import time
import threading
import concurrent.futures

import sys
import warnings
import asyncio
import signal
import multiprocessing
import psutil
from binance.um_futures import UMFutures
from utils.keys1 import api, secret
from datetime import datetime,timedelta


warnings.filterwarnings('ignore')

from utils.FinalVersionTradingDB_PostgreSQL import (
    fetch_squeezed_pairs_from_db, 
    fetch_non_squeezed_pairs_from_db,
    update_squeeze_status,
    fetch_price_precision_from_db,
    fetch_data_safe,
    # check_signal_processing_log_exists,
    # insert_signal_processing_log,
    # AssignTradeToMachineLAB,
    fetch_single_pair_from_db,
    # check_running_trade_exists,
    fetch_squeezed_pairs_from_db_paginated,
    fetch_non_squeezed_pairs_from_db_paginated,
    getSuperTrend,
    getSuperTrendPercent,
    # count_running_trades,
    # count_running_trades_negative
)

from utils.Final_olab_database import (
    olab_AssignTradeToMachineLAB,
    olab_check_signal_processing_log_exists,    
    olab_check_running_trade_exists,
    olab_count_running_trades,
    fetch_ohlcv
)
from telegram_message_sender import send_message_to_users





# Import logging functions for main signal detection
from utils.logger import (
    log_error,
    log_signal_processing,
    log_signal_validation,
    log_performance_metric,
    log_batch_processing,
    log_system_health,
    log_cache_performance,
    performance_monitor,
    log_to_file_reject_from_api
)


client = UMFutures(key=api, secret=secret)

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


# Global SuperTrend variables
superTrend = None
superTrendPercent = False
superTrendLong = False
superTrendShort = False




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
        # df = df.sort_values("time").copy()

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

# def calculate_all_indicators_optimized(df, candle='regular'):
#     """
#     Calculate all technical indicators in one optimized pass through the dataframe
#     Supports both regular and Heiken Ashi candles
#     """
#     try:
#         if df is None or df.empty:
#             return df
        
#         # df = df.sort_values("time").set_index("time")
#         df = df.sort_values("time").set_index("time", drop=False)


#         df_copy = df.copy()
#         # 1. Heiken Ashi calculations (always needed for HA candles)
#         # if candle == 'heiken':
#         df = calculate_heiken_ashi_optimized(df)
        
#         # 2. Dynamic OHLC column selection
#         if candle == 'heiken':
#             open_col = 'ha_open'
#             low_col = 'ha_low'
#             high_col = 'ha_high'
#             close_col = 'ha_close'
            
#         else:
#             open_col = 'open'
#             low_col = 'low'
#             high_col = 'high'
#             close_col = 'close'
            
#         df['color'] = np.where(df['close'] >= df['open'], 'GREEN', 'RED')
#         # 3. Basic indicators (RSI, MACD, Bollinger Bands, Moving Averages)
#         df['RSI_9'] = talib.RSI(df[close_col], timeperiod=9)
#         df['RSI_14'] = talib.RSI(df[close_col], timeperiod=14)

#         df['ema_9'] = talib.EMA(df[close_col], timeperiod=9)
#         df['ema_14'] = talib.EMA(df[close_col], timeperiod=14)
#         df['ema_21'] = talib.EMA(df[close_col], timeperiod=21)
#         df['ema_39'] = talib.EMA(df[close_col], timeperiod=39)
#         df['ema_50'] = talib.EMA(df[close_col], timeperiod=50)
#         df['ema_100'] = talib.EMA(df[close_col], timeperiod=144)

        
#         df['MACD'], df['MACD_Signal'], df['MACD_Histogram'] = talib.MACD(
#             df[close_col], fastperiod=12, slowperiod=26, signalperiod=9
#         )
        
#         df['BOLL_upper_band'], df['BOLL_middle_band'], df['BOLL_lower_band'] = talib.BBANDS(
#             df[close_col], timeperiod=20, nbdevup=2, nbdevdn=2, matype=MA_Type.SMA
#         )
#         # ➕ Calculate BBW (Bollinger Band Width)
#         df['BBW'] = (df['BOLL_upper_band'] - df['BOLL_lower_band']) / df['BOLL_middle_band']
#         df['BBW_Increasing'] =  df['BBW'] > df['BBW'].shift(1)
#         # Compute relative percentile
#         df['BBW_PERCENTILE'] = df['BBW'].rolling(100).apply(
#             lambda x: pd.Series(x).rank(pct=True).iloc[-1]
#         )
        

        
#         df['Volume_MA'] = talib.SMA(df['volume'], timeperiod=20)
#         df['Volume_Ratio'] = df['volume'] / df['Volume_MA']
#         df['volume_increasing'] = df['volume'] > df['volume'].shift(1)

        

#         df['two_pole_macd'], df['two_pole_Signal_Line'], df['two_pole_macdhist'] = talib.MACD(
#             df[close_col], fastperiod=13, slowperiod=21, signalperiod=9
#         )

#         df['lower_two_pole_macd'], df['lower_two_pole_Signal_Line'], df['lower_two_pole_macdhist'] = talib.MACD(
#             df[close_col], fastperiod=5, slowperiod=8, signalperiod=9
#         )
#         df['lower_two_pole_MACD_Cross_Up'] = (df['lower_two_pole_macd'] > df['lower_two_pole_Signal_Line']) & (df['lower_two_pole_macd'].shift(1) <= df['lower_two_pole_Signal_Line'].shift(1))
#         df['lower_two_pole_MACD_Cross_Down'] = (df['lower_two_pole_macd'] < df['lower_two_pole_Signal_Line']) & (df['lower_two_pole_macd'].shift(1) >= df['lower_two_pole_Signal_Line'].shift(1))

#         df['lower_MACD_CrossOver'] = np.where(
#             df['lower_two_pole_MACD_Cross_Up'], 'BUY',
#             np.where(
#                 df['lower_two_pole_MACD_Cross_Down'], 'SELL',
#                 np.nan
#             )
#         )

#         df['5_8_9_macd_pos'] = np.where(
#                 df['lower_two_pole_macdhist'] > 0, 'BUY',
#                 np.where(
#                     df['lower_two_pole_macdhist'] < 0, 'SELL',
#                     np.nan
#                 )
#             )
        
#         df['13_21_9_macd_pos'] = np.where(
#             df['two_pole_macdhist'] > 0, 'BUY',
#             np.where(
#                 df['two_pole_macdhist'] < 0, 'SELL',
#                 np.nan
#             )
#         )

#         df['34_144_9_macd'], df['34_144_9_Signal_Line'], df['34_144_9_macdhist'] = talib.MACD(
#         df[close_col], fastperiod=34, slowperiod=144, signalperiod=9
#         )

#         df['34_144_9_macd_pos'] = np.where(
#             df['34_144_9_macdhist'] > 0, 'BUY',
#             np.where(
#                 df['34_144_9_macdhist'] < 0, 'SELL',
#                 np.nan
#             )
#         )
		
#         same_side_decreasing_34_144_9 = (
#             ((df["34_144_9_macdhist"] > 0) & (df["34_144_9_macdhist"] < df["34_144_9_macdhist"].shift(1))) |  # dark green from light green
#             ((df["34_144_9_macdhist"] < 0) & (df["34_144_9_macdhist"] > df["34_144_9_macdhist"].shift(1)))    # dark red from light red
#         )

#         # Combine both conditions
#         df["Histogram_Decreasing_34_144_9"] = same_side_decreasing_34_144_9 

#         # Assign MACD_COLOR_34_144_9 based on two_pole MACD cross and histogram decreasing
#         df['MACD_COLOR_34_144_9'] = np.select(
#             [
#                 (df['34_144_9_macd'] > df['34_144_9_Signal_Line']) & ~df["Histogram_Decreasing_34_144_9"],  # Dark green
#                 (df['34_144_9_macd'] > df['34_144_9_Signal_Line']) & df["Histogram_Decreasing_34_144_9"],   # Light green
#                 (df['34_144_9_macd'] < df['34_144_9_Signal_Line']) & ~df["Histogram_Decreasing_34_144_9"],  # Dark red
#                 (df['34_144_9_macd'] < df['34_144_9_Signal_Line']) & df["Histogram_Decreasing_34_144_9"],   # Light red
#             ],
#             [
#                 'DARK_GREEN',
#                 'LIGHT_GREEN',
#                 'DARK_RED',
#                 'LIGHT_RED'
#             ],
#             default='NONE'
#         )


#         # Assign BUY/SELL to MACD_COLOR_34_144_9_signal based on MACD_COLOR_34_144_9
#         # Fix: Use .astype(str) to ensure correct string comparison, and default to 'NONE'
#         df['MACD_COLOR_34_144_9_signal'] = np.select(
#             [
#                 (df['MACD_COLOR_34_144_9'] == 'DARK_GREEN') | (df['MACD_COLOR_34_144_9'] == 'LIGHT_RED'),
#                 (df['MACD_COLOR_34_144_9'] == 'LIGHT_GREEN') | (df['MACD_COLOR_34_144_9'] == 'DARK_RED')
#             ],
#             [
#                 'BUY',
#                 'SELL'
#             ],
#             default='NONE'
#         )



#         df['200_macd'], df['200_Signal_Line'], df['200_macdhist'] = talib.MACD(
#         df[close_col], fastperiod=100, slowperiod=200, signalperiod=50
#         )
            
#         df['200_macd_Cross_Up'] = df['200_macdhist'] > 0     # histogram green
#         df['200_macd_Cross_Down'] = df['200_macdhist'] < 0     # histogram red

#         df['200_macd_pos'] =  np.where(
#             df['200_macd_Cross_Up'], 'BUY',
#             np.where(
#                 df['200_macd_Cross_Down'], 'SELL',
#                 np.nan
#             )
#         )
     

#         # df['two_pole_MACD_Cross_Up'] = (df['two_pole_macd'] > df['two_pole_Signal_Line']) & (df['two_pole_macd'].shift(1) <= df['two_pole_Signal_Line'].shift(1))
#         # df['two_pole_MACD_Cross_Down'] = (df['two_pole_macd'] < df['two_pole_Signal_Line']) & (df['two_pole_macd'].shift(1) >= df['two_pole_Signal_Line'].shift(1))

#         df['two_pole_MACD_Cross_Up'] = df['two_pole_macdhist'] > 0
#         df['two_pole_MACD_Cross_Down'] = df['two_pole_macdhist'] < 0

#         # Detect same-side weakening
#         same_side_decreasing = (
#             ((df["two_pole_macdhist"] > 0) & (df["two_pole_macdhist"] < df["two_pole_macdhist"].shift(1))) |  # dark green from light green
#             ((df["two_pole_macdhist"] < 0) & (df["two_pole_macdhist"] > df["two_pole_macdhist"].shift(1)))    # dark red from light red
#         )

#         # Combine both conditions
#         df["Histogram_Decreasing"] = same_side_decreasing 

#         # Assign MACD_COLOR based on two_pole MACD cross and histogram decreasing
#         df['MACD_COLOR'] = np.select(
#             [
#                 (df['two_pole_macd'] > df['two_pole_Signal_Line']) & ~df["Histogram_Decreasing"],  # Dark green
#                 (df['two_pole_macd'] > df['two_pole_Signal_Line']) & df["Histogram_Decreasing"],   # Light green
#                 (df['two_pole_macd'] < df['two_pole_Signal_Line']) & ~df["Histogram_Decreasing"],  # Dark red
#                 (df['two_pole_macd'] < df['two_pole_Signal_Line']) & df["Histogram_Decreasing"],   # Light red
#             ],
#             [
#                 'DARK_GREEN',
#                 'LIGHT_GREEN',
#                 'DARK_RED',
#                 'LIGHT_RED'
#             ],
#             default='NONE'
#         )


#         # Assign BUY/SELL to macd_color_signal based on MACD_COLOR
#         # Fix: Use .astype(str) to ensure correct string comparison, and default to 'NONE'
#         df['macd_color_signal'] = np.select(
#             [
#                 (df['MACD_COLOR'] == 'DARK_GREEN') | (df['MACD_COLOR'] == 'LIGHT_RED'),
#                 (df['MACD_COLOR'] == 'LIGHT_GREEN') | (df['MACD_COLOR'] == 'DARK_RED')
#             ],
#             [
#                 'BUY',
#                 'SELL'
#             ],
#             default='NONE'
#         )

#         lower_same_side_decreasing = (
#             ((df["lower_two_pole_macdhist"] > 0) & (df["lower_two_pole_macdhist"] < df["lower_two_pole_macdhist"].shift(1))) |  # dark green from light green
#             ((df["lower_two_pole_macdhist"] < 0) & (df["lower_two_pole_macdhist"] > df["lower_two_pole_macdhist"].shift(1)))    # dark red from light red
#         )

#         # Combine both conditions
#         df["Lower_Histogram_Decreasing"] = lower_same_side_decreasing 


#         df['LOWER_MACD_COLOR'] = np.select(
#             [
#                 (df['lower_two_pole_macd'] > df['lower_two_pole_Signal_Line']) & ~df["Lower_Histogram_Decreasing"],  # Dark green
#                 (df['lower_two_pole_macd'] > df['lower_two_pole_Signal_Line']) & df["Lower_Histogram_Decreasing"],   # Light green
#                 (df['lower_two_pole_macd'] < df['lower_two_pole_Signal_Line']) & ~df["Lower_Histogram_Decreasing"],  # Dark red
#                 (df['lower_two_pole_macd'] < df['lower_two_pole_Signal_Line']) & df["Lower_Histogram_Decreasing"],   # Light red
#             ],
#             [
#                 'DARK_GREEN',
#                 'LIGHT_GREEN',
#                 'DARK_RED',
#                 'LIGHT_RED'
#             ],
#             default='NONE'
#         )

#         df['lower_macd_color_signal'] = np.select(
#             [
#                 (df['LOWER_MACD_COLOR'] == 'DARK_GREEN') | (df['LOWER_MACD_COLOR'] == 'LIGHT_RED'),
#                 (df['LOWER_MACD_COLOR'] == 'LIGHT_GREEN') | (df['LOWER_MACD_COLOR'] == 'DARK_RED')
#             ],
#             [
#                 'BUY',
#                 'SELL'
#             ],
#             default='NONE'
#         )        
        

#         # Detect bullish crossover: red → green
#         bullish_crossover = (
#             (df["two_pole_macdhist"].shift(1) < 0) & (df["two_pole_macdhist"] > 0)
#         )

#         # Detect bearish crossover: green → red
#         bearish_crossover = (
#             (df["two_pole_macdhist"].shift(1) > 0) & (df["two_pole_macdhist"] < 0)
#         )


#         df['two_pole_trade_signal'] = np.where(
#                             df['two_pole_Signal_Line'] > 0,
#                             'BUY',
#                             'SELL'
#                     )


#         # Optional: store crossover types in their own columns
#         df["two_pole_MACD_CrossOver"] = np.where(
#             bullish_crossover, 'BUY',
#             np.where(
#                 bearish_crossover, 'SELL',
#                 np.nan
#             )
#         )


#         # make sure crossover column already exists:
#         # df["two_pole_MACD_CrossOver"] = ...

#         df['RSI_9_MACD'] = np.nan
#         df['TAKEACTION'] = np.nan

#         state = None  # can be 'SELL', 'BUY', or None

#         # iterate row by row (needed because state carries forward)
#         for i in range(len(df)):
#             rsi   = df['RSI_9'].iloc[i]
#             cross = df['two_pole_MACD_CrossOver'].iloc[i]

#             # 1) Arm the state when RSI extreme happens
#             # (if later opposite extreme happens before crossover, it will switch)
#             if rsi > 70:
#                 state = 'SELL'
#             elif rsi < 30:
#                 state = 'BUY'

#             # 2) If crossover matches the armed state → take action and reset
#             if state is not None and cross == state:
#                 df.iloc[i, df.columns.get_loc('TAKEACTION')] = state
#                 state = None

            

#             # 3) Store current state into dataframe (persisting flag)
#             df.iloc[i, df.columns.get_loc('RSI_9_MACD')] = state




#     # Label EMA trend as 'bullish' or 'bearish'
#         df['ema_trend_100_14'] = np.where(
#             df['ema_14'] > df['ema_100'],
#             'bullish',
#             np.where(
#                 df['ema_14'] < df['ema_100'],
#                 'bearish',
#                 'neutral'
#             )
#         )

#         # Signal: bullish if price above ema_14 and trend bullish, bearish if price below ema_14 and trend bearish, else neutral
#         df['ema_price_trend_signal'] = np.where(
#             (df[close_col] > df['ema_14']) & (df['ema_trend_100_14'] == 'bullish'),
#             'bullish',
#             np.where(
#                 (df[close_col] < df['ema_14']) & (df['ema_trend_100_14'] == 'bearish'),
#                 'bearish',
#                 'neutral'
#             )
#         )

#         # Fix: Assign trend_direction for each row based on close price vs previous close
#         df['price_trend_direction'] = 'SIDEWAYS'
#         df.loc[df[close_col] > df[close_col].shift(1), 'price_trend_direction'] = 'UPTREND'
#         df.loc[df[close_col] < df[close_col].shift(1), 'price_trend_direction'] = 'DOWNTREND'


#         # Zero Lag EMA calculation 
#         length = 70
#         lag = int((length - 1) / 2)
#         zlema_input = df[close_col] + (df[close_col] - df[close_col].shift(lag))
#         df['zlema'] = talib.EMA(zlema_input, timeperiod=length)

#         # Calculate volatility for Zero Lag bands
#         tr1 = df[high_col] - df[low_col]
#         tr2 = abs(df[high_col] - df[close_col].shift(1))
#         tr3 = abs(df[low_col] - df[close_col].shift(1))
#         tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
#         atr = tr.rolling(window=length).mean()
#         volatility = atr.rolling(window=length * 3).max() * 1.2  # mult = 1.2

#         # Calculate trend based on Zero Lag bands (corrected forward fill logic)
#         crossover_up = (df[close_col] > df['zlema'] + volatility) & (df[close_col].shift(1) <= df['zlema'].shift(1) + volatility.shift(1))
#         crossunder_down = (df[close_col] < df['zlema'] - volatility) & (df[close_col].shift(1) >= df['zlema'].shift(1) - volatility.shift(1))

#         df['zlema_trend'] = np.nan  # use NaN so forward fill actually works
#         df.loc[crossover_up, 'zlema_trend'] = 1
#         df.loc[crossunder_down, 'zlema_trend'] = -1
#         df['zlema_trend'] = df['zlema_trend'].ffill().fillna(0)  # fill missing values


#         # Zero Lag entry signals
#         df['zlema_bullish_entry'] = (
#             (df[close_col] > df['zlema']) & (df[close_col].shift(1) <= df['zlema'].shift(1)) &  # crossover
#             (df['zlema_trend'] == 1) & (df['zlema_trend'].shift(1) == 1)  # trend continuity
#         )

#         df['zlema_bearish_entry'] = (
#             (df[close_col] < df['zlema']) & (df[close_col].shift(1) >= df['zlema'].shift(1)) &  # crossunder
#             (df['zlema_trend'] == -1) & (df['zlema_trend'].shift(1) == -1)  # trend continuity
#         )

#         # Zero Lag trend change signals
#         df['zlema_bullish_trend_signal'] = (df['zlema_trend'] == 1) & (df['zlema_trend'].shift(1) == -1)
#         df['zlema_bearish_trend_signal'] = (df['zlema_trend'] == -1) & (df['zlema_trend'].shift(1) == 1)
        
#                 # Heiken Ashi exit indicators (for Zero Lag strategy)

#         df['ha_trend_up'] = df[close_col] > df[open_col]
#         df['ha_trend_down'] = df[close_col] < df[open_col]

#         # === Delta Volume (Pine-style) ======================================
#         # We follow the script logic:
#         # - Trend is the boolean is_trend_up (here derived from zlema_trend).
#         # - While the trend regime stays the same, we accumulate:
#         #     up_trend_volume  += volume on GREEN bars (close > open)
#         #     down_trend_volume+= volume on RED   bars (close < open)
#         # - When trend flips, both counters reset to 0.

#         # 1) Trend booleans and crosses (reuse your zlema_trend)
#         df['is_trend_up'] = (df['zlema_trend'] == 1)

#         df['trend_cross_up']   = (~df['is_trend_up'].shift(1).fillna(False)) & (df['is_trend_up'])
#         df['trend_cross_down'] = (df['is_trend_up'].shift(1).fillna(False)) & (~df['is_trend_up'])

#         # 2) Build regime groups: a new group each time trend changes
#         trend_change = df['is_trend_up'] != df['is_trend_up'].shift(1)
#         regime_id = trend_change.cumsum()

#         # 3) GREEN / RED volume by your chosen candle type
#         green_vol = np.where(df[close_col] > df[open_col], df['volume'].astype(float), 0.0)
#         red_vol   = np.where(df[close_col] < df[open_col], df['volume'].astype(float), 0.0)

#         # 4) Cumulative sums inside each regime (reset on flip)
#         df['up_trend_volume']   = pd.Series(green_vol, index=df.index).groupby(regime_id).cumsum()
#         df['down_trend_volume'] = pd.Series(red_vol,   index=df.index).groupby(regime_id).cumsum()

#         # 5) Delta volume % = ((Buy - Sell) / average(Buy,Sell)) * 100, safe when avg==0
#         avg_vol = (df['up_trend_volume'] + df['down_trend_volume']) / 2.0
#         df['delta_volume_pct'] = np.where(
#             avg_vol > 0,
#             ((df['up_trend_volume'] - df['down_trend_volume']) / avg_vol) * 100.0,
#             0.0
#         )
#         # =====================================================================




#         # Previous HA open (shifted by one bar)
#         prev_ha_open = df[open_col].shift(1)


#         # Price vs previous HA open
#         df['price_vs_ha_open'] = df[close_col] > prev_ha_open

#         # Raw exit flags (independent of your position state)
#         df['exit_long_raw']  = df['ha_trend_down'] | (~df['price_vs_ha_open'].fillna(False))
#         df['exit_short_raw'] = df['ha_trend_up']   | ( df['price_vs_ha_open'].fillna(False))

  
#         # 6. Consolidation detection
#         bb_upper, bb_middle, bb_lower = talib.BBANDS(
#             df[close_col],
#             timeperiod=3,
#             nbdevup=2,
#             nbdevdn=2,
#             matype=MA_Type.SMA
#         )
        

#         df['BB_Width'] = df['BOLL_upper_band'] - df['BOLL_lower_band']
#         df['bb_flat_market'] = df['BB_Width'] < df['BB_Width'].rolling(window=20).mean()
        
#         df['price_range'] = (
#             (df[high_col].rolling(window=20).max() - df[low_col].rolling(window=20).min())
#             / df[low_col].rolling(window=20).min()
#         )
#         df['price_range_flat_market'] = df['price_range'] < 0.1
#         df['consolidating'] = df['bb_flat_market'] & df['price_range_flat_market']
        
#         # 7. Swing highs/lows detection (Optimized)
#         window = 5
        
#         # Boolean mask for swings
#         is_swing_high = df[high_col] == df[high_col].rolling(window*2+1, center=True).max()
#         is_swing_low = df[low_col] == df[low_col].rolling(window*2+1, center=True).min()

#         df['swing_high'] = is_swing_high
#         df['swing_low'] = is_swing_low

#         # # Store price at swing points for zone calculations, NaN otherwise
#         # df['swing_high_zone'] = np.where(is_swing_high, df[high_col], np.nan)
#         # df['swing_low_zone'] = np.where(is_swing_low, df[low_col], np.nan)


#                 # Mark swings (NaN where not a swing)
#         df['swing_high_zone'] = np.where(is_swing_high, df[high_col], np.nan)
#         df['swing_low_zone']  = np.where(is_swing_low,  df[low_col],  np.nan)

#         # Carry last swing forward on every next row
#         df['swing_high_zone'] = df['swing_high_zone'].ffill()
#         df['swing_low_zone']  = df['swing_low_zone'].ffill()

        
#         # 8. Candle strength calculations (always use Heiken Ashi for strength)
#         if candle == 'heiken':
#             df['candle_strength'] = df.apply(lambda row: abs(row['ha_close'] - row['ha_open']) / (row['ha_high'] - row['ha_low']) if (row['ha_high'] - row['ha_low']) > 0 else 0, axis=1)
#             df['candle_strength'] = df['candle_strength'].round(2)
            
#             df['candle_strength_bool'] = df.apply(lambda row: abs(row['ha_close'] - row['ha_open']) / (row['ha_high'] - row['ha_low']) >= 0.6 if (row['ha_high'] - row['ha_low']) > 0 else False, axis=1)
#         else:
#             # For regular candles, calculate strength using regular OHLC
#             df['candle_strength'] = df.apply(lambda row: abs(row['close'] - row['open']) / (row['high'] - row['low']) if (row['high'] - row['low']) > 0 else 0, axis=1)
#             df['candle_strength'] = df['candle_strength'].round(2)
            
#             df['candle_strength_bool'] = df.apply(lambda row: abs(row['close'] - row['open']) / (row['high'] - row['low']) >= 0.6 if (row['high'] - row['low']) > 0 else False, axis=1)
    
    
#     # 9. Total Change Added After Analysis
#         # Calculate the total percentage change from open to close
#         df['Total_Change'] = ((df[close_col] - df[open_col]) / df[open_col]) * 100
#         # Round the total percentage change
#         df['Total_Change'] = df['Total_Change'].round(2)  


#         df['Total_Change_Regular'] = ((df['close'] - df['open']) / df['open']) * 100
#         # Round the total percentage change
#         df['Total_Change_Regular'] = df['Total_Change_Regular'].round(2)  


#         # --- EMA calculations ---
#         df['ema8_high'] = talib.EMA(df['high'], timeperiod=8)
#         df['ema8_low'] = talib.EMA(df['low'], timeperiod=8)

#         df['ema34_high'] = talib.EMA(df['high'], timeperiod=34)
#         df['ema34_low'] = talib.EMA(df['low'], timeperiod=34)

#         df['ema144_close'] = talib.EMA(df['close'], timeperiod=144)
#         df['ema233_close'] = talib.EMA(df['close'], timeperiod=233)

#         # --- Buy and Sell Conditions ---
#         df['3ema_buy_signal'] = (
#             (df['ema8_high'] > df['ema34_high']) &
#             (df['ema8_low'] > df['ema34_low']) &
#             (df['ema34_high'] > df['ema144_close']) &
#             (df['ema34_low'] > df['ema144_close']) &
#             (df['ema144_close'] > df['ema233_close'])
#         )

#         df['3ema_sell_signal'] = (
#             (df['ema8_high'] < df['ema34_high']) &
#             (df['ema8_low'] < df['ema34_low']) &
#             (df['ema34_high'] < df['ema144_close']) &
#             (df['ema34_low'] < df['ema144_close']) &
#             (df['ema144_close'] < df['ema233_close'])
#         )

#         ## added for flat maket and ema 9 signal check with all interval and follows lower to upper time frame

#         # Keep all earlier columns on `df`, and add AO state from df_copy
#         ao_col = andean_oscillator(df)['andean_oscillator']   # 1D Series aligned by index
#         df['andean_oscillator'] = ao_col
       
#        # CCI minimal on raw candles, then assign only needed cols back
#         # tmp = cci_minimal(df_copy)  # returns df_copy with 3 new columns
#         # cols = ['cci_entry_state', 'cci_exit_cross', 'cci_sma']
#         # df[cols] = tmp[cols]        # index-aligned assign

#         ### Here we need to add the 100 for ProLab

#         # tmp = cci_minimal(df_copy,length=100)  # returns df_copy with 3 new columns
#         # cols = ['cci_entry_state', 'cci_exit_cross', 'cci_sma']
#         # df[cols] = tmp[cols]        # index-aligned assign


#         # CCI(9)
#         # tmp9 = cci_minimal(df, cci_len=9,  smoothing_len=20, exit_len=20, suffix="_9")
#         # df[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9"]] = tmp9[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9"]]

#         # # CCI(100)
#         # tmp100 = cci_minimal(df, cci_len=100, smoothing_len=20, exit_len=20, suffix="_100")
#         # df[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100"]] = tmp100[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100"]]

#         tmp9 = cci_minimal(df, cci_len=9, smoothing_len=21, suffix="_9")
        
#         df[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9","cci_value_9","cci_yellow_value_9"]] = tmp9[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9","cci_value_9","cci_yellow_value_9"]]      

#         # print(df[['cci_entry_state_9','cci_exit_cross_9','cci_sma_9']].tail(12))

#         # CCI(100)
#         tmp100 = cci_minimal(df, cci_len=20, smoothing_len=20, suffix="_100")
#         df[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100","cci_value_100","cci_yellow_value_100"]] = tmp100[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100","cci_value_100","cci_yellow_value_100"]]




#         # Add TDFI state
#         tmp = tdfi_assign_state_talib(
#             df,                 # raw OHLC frame
#             lookback=9,
#             mmaLength=9, mmaMode="ema",
#             smmaLength=9, smmaMode="ema",
#             nLength=3, filterHigh=0.05, filterLow=-0.05
#         )

#         # Assign just the one column back to your working df
#         df['tdfi_state'] = tmp['tdfi_state']

#         # Access:
#         df['tdfi_state'].iloc[-1]   # 'FLAT' | 'BULL' | 'BEAR'

#         tmp1 = tdfi_assign_state_talib(
#             df,                 # raw OHLC frame
#             lookback=2,
#             mmaLength=2, mmaMode="ema",
#             smmaLength=2, smmaMode="ema",
#             nLength=3, filterHigh=0.05, filterLow=-0.05
#         )

#         df['tdfi_state_2_ema'] = tmp1['tdfi_state']


#         tmp2 = tdfi_assign_state_talib(
#             df,                 # raw OHLC frame
#             lookback=3,
#             mmaLength=3, mmaMode="ema",
#             smmaLength=3, smmaMode="ema",
#             nLength=3, filterHigh=0.05, filterLow=-0.05
#         )

#         df['tdfi_state_3_ema'] = tmp2['tdfi_state']

#         df = label_heikin_types(df)
#         df = label_candle_types_regular(df)

#         return df
        
#     except Exception as e:
#         print(f"Error in calculate_all_indicators_optimized: {e}")
#         log_error(e, "calculate_all_indicators_optimized", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
#         return df





# def is_order_allowed(order_time, last_div_str, action):
#     """
#     Block BUY if there is a BEAR divergence on the same date.
#     Otherwise allow.
    
#     order_time      : datetime (e.g. 2025-08-23 15:30:00)
#     last_div_str    : "2025-08-23-05::45_BEAR" or NaN / None / ""
#     action          : "BUY" / "SELL" / etc.
#     """

#     # If not a BUY, always allowed as per your rule


#     # If no divergence info, allow
#     if not isinstance(last_div_str, str) or not last_div_str.strip():
#         return True

#     # Try to parse "time_side" format safely
#     if '_' not in last_div_str:
#         # Unexpected format, just allow
#         return True

#     try:
#         time_part, side = last_div_str.rsplit('_', 1)
#         # Parse "2025-08-23-05::45"
#         last_div_time = datetime.strptime(time_part, '%Y-%m-%d-%H::%M')
#     except Exception:
#         # If parsing fails for any row, do not block the trade
#         return True

#     same_date = order_time.date() == last_div_time.date()
#     bear_same_day = same_date and (side == 'BEAR')

#     # Block only when BUY and BEAR divergence same day
#     if bear_same_day:
#         return False
#     return True


# def is_order_allowed(order_time, last_div_str, action):
#     """
#     Block:
#       - BUY if same-date divergence is BEAR
#       - SELL if same-date divergence is BULL
#     Otherwise allow.
#     """

#     # If no action, just allow
#     if action not in ('BUY', 'SELL'):
#         return True

#     # Handle NaN / None / non-string
#     if not isinstance(last_div_str, str) or not last_div_str.strip():
#         return True

#     # Expect "2025-08-23-05::45_BEAR"
#     if '_' not in last_div_str:
#         return True

#     try:
#         time_part, side = last_div_str.rsplit('_', 1)   # side = 'BULL' / 'BEAR'
#         last_div_time = datetime.strptime(time_part, '%Y-%m-%d-%H::%M')
#     except Exception:
#         # If parsing fails, don't block
#         return True

#     same_date = order_time.date() == last_div_time.date()

#     # Rules:
#     # BUY blocked by BEAR on same date
#     if action == 'BUY' and same_date and side == 'BEAR':
#         return False

#     # SELL blocked by BULL on same date
#     if action == 'SELL' and same_date and side == 'BULL':
#         return False

#     return True




def calculate_all_indicators_optimized(df, candle='regular'):
    """
    Calculate all technical indicators in one optimized pass through the dataframe
    Supports both regular and Heiken Ashi candles
    """
    try:
        if df is None or df.empty:
            return df
        
        # df = df.sort_values("time").set_index("time")
        df = df.sort_values("time").set_index("time", drop=False)


        df_copy = df.copy()
        # 1. Heiken Ashi calculations (always needed for HA candles)
        # if candle == 'heiken':
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



        df['RSI_5']  = talib.RSI(df[close_col], timeperiod=5)
        df['RSI_21'] = talib.RSI(df[close_col], timeperiod=21)

        buy_cond = (
            (df['RSI_5'] > 50) &
            (df['RSI_21'] > 50) &
            (df['RSI_5'] > df['RSI_21'])
        )

        sell_cond = (
            (df['RSI_5'] < 50) &
            (df['RSI_21'] < 50) &
            (df['RSI_5'] < df['RSI_21'])
        )

        df['RSI_SIGNAL'] = np.where(
            buy_cond, 'BUY',
            np.where(sell_cond, 'SELL', 'NONE')
        )

        # ============================
        # 2) RSI 5/21 CROSSOVER signal
        # ============================
        rsi5_prev  = df['RSI_5'].shift(1)
        rsi21_prev = df['RSI_21'].shift(1)

        # Cross UP: RSI_5 crosses above RSI_21 → bullish
        df['RSI_5_21_cross_up'] = (
            (rsi5_prev <= rsi21_prev) &
            (df['RSI_5'] > df['RSI_21'])
        )

        # Cross DOWN: RSI_5 crosses below RSI_21 → bearish
        df['RSI_5_21_cross_down'] = (
            (rsi5_prev >= rsi21_prev) &
            (df['RSI_5'] < df['RSI_21'])
        )

        df['RSI_CROSS_SIGNAL'] = np.where(
            df['RSI_5_21_cross_up'],  'BUY',
            np.where(df['RSI_5_21_cross_down'], 'SELL', 'NONE')
        )

        df['ema_5'] = talib.EMA(df[close_col], timeperiod=5)
        df['ema_8'] = talib.EMA(df[close_col], timeperiod=8)
        df['ema_9'] = talib.EMA(df[close_col], timeperiod=9)
        df['ema_14'] = talib.EMA(df[close_col], timeperiod=14)
        df['ema_21'] = talib.EMA(df[close_col], timeperiod=21)
        df['ema_39'] = talib.EMA(df[close_col], timeperiod=39)
        df['ema_50'] = talib.EMA(df[close_col], timeperiod=50)
        df['ema_100'] = talib.EMA(df[close_col], timeperiod=200)


              
        df['MACD'], df['MACD_Signal'], df['MACD_Histogram'] = talib.MACD(
            df[close_col], fastperiod=12, slowperiod=26, signalperiod=9
        )
        
        df['BOLL_upper_band'], df['BOLL_middle_band'], df['BOLL_lower_band'] = talib.BBANDS(
            df[close_col], timeperiod=20, nbdevup=2, nbdevdn=2, matype=MA_Type.SMA
        )
        # ➕ Calculate BBW (Bollinger Band Width)
        df['BBW'] = (df['BOLL_upper_band'] - df['BOLL_lower_band']) / df['BOLL_middle_band']
        df['BBW_Increasing'] =  df['BBW'] > df['BBW'].shift(1)
        # Compute relative percentile
        df['BBW_PERCENTILE'] = df['BBW'].rolling(100).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1]
        )
        

        
        df['Volume_MA'] = talib.SMA(df['volume'], timeperiod=20)
        df['Volume_Ratio'] = df['volume'] / df['Volume_MA']
        df['volume_increasing'] = df['volume'] > df['volume'].shift(1)

        

        df['two_pole_macd'], df['two_pole_Signal_Line'], df['two_pole_macdhist'] = talib.MACD(
            df[close_col], fastperiod=13, slowperiod=21, signalperiod=9
        )

        df['lower_two_pole_macd'], df['lower_two_pole_Signal_Line'], df['lower_two_pole_macdhist'] = talib.MACD(
            df[close_col], fastperiod=5, slowperiod=8, signalperiod=9
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

        df['5_8_9_macd_pos'] = np.where(
                df['lower_two_pole_macdhist'] > 0, 'BUY',
                np.where(
                    df['lower_two_pole_macdhist'] < 0, 'SELL',
                    np.nan
                )
            )
        
        df['13_21_9_macd_pos'] = np.where(
            df['two_pole_macdhist'] > 0, 'BUY',
            np.where(
                df['two_pole_macdhist'] < 0, 'SELL',
                np.nan
            )
        )

        df['34_144_9_macd'], df['34_144_9_Signal_Line'], df['34_144_9_macdhist'] = talib.MACD(
        df[close_col], fastperiod=34, slowperiod=144, signalperiod=9
        )

        df['34_144_9_macd_pos'] = np.where(
            df['34_144_9_macdhist'] > 0, 'BUY',
            np.where(
                df['34_144_9_macdhist'] < 0, 'SELL',
                np.nan
            )
        )
		
        same_side_decreasing_34_144_9 = (
            ((df["34_144_9_macdhist"] > 0) & (df["34_144_9_macdhist"] < df["34_144_9_macdhist"].shift(1))) |  # dark green from light green
            ((df["34_144_9_macdhist"] < 0) & (df["34_144_9_macdhist"] > df["34_144_9_macdhist"].shift(1)))    # dark red from light red
        )

        # Combine both conditions
        df["Histogram_Decreasing_34_144_9"] = same_side_decreasing_34_144_9 

        # Assign MACD_COLOR_34_144_9 based on two_pole MACD cross and histogram decreasing
        df['MACD_COLOR_34_144_9'] = np.select(
            [
                (df['34_144_9_macd'] > df['34_144_9_Signal_Line']) & ~df["Histogram_Decreasing_34_144_9"],  # Dark green
                (df['34_144_9_macd'] > df['34_144_9_Signal_Line']) & df["Histogram_Decreasing_34_144_9"],   # Light green
                (df['34_144_9_macd'] < df['34_144_9_Signal_Line']) & ~df["Histogram_Decreasing_34_144_9"],  # Dark red
                (df['34_144_9_macd'] < df['34_144_9_Signal_Line']) & df["Histogram_Decreasing_34_144_9"],   # Light red
            ],
            [
                'DARK_GREEN',
                'LIGHT_GREEN',
                'DARK_RED',
                'LIGHT_RED'
            ],
            default='NONE'
        )


        # Assign BUY/SELL to MACD_COLOR_34_144_9_signal based on MACD_COLOR_34_144_9
        # Fix: Use .astype(str) to ensure correct string comparison, and default to 'NONE'
        df['MACD_COLOR_34_144_9_signal'] = np.select(
            [
                (df['MACD_COLOR_34_144_9'] == 'DARK_GREEN') | (df['MACD_COLOR_34_144_9'] == 'LIGHT_RED'),
                (df['MACD_COLOR_34_144_9'] == 'LIGHT_GREEN') | (df['MACD_COLOR_34_144_9'] == 'DARK_RED')
            ],
            [
                'BUY',
                'SELL'
            ],
            default='NONE'
        )



        df['200_macd'], df['200_Signal_Line'], df['200_macdhist'] = talib.MACD(
        df[close_col], fastperiod=100, slowperiod=200, signalperiod=50
        )
            
        df['200_macd_Cross_Up'] = df['200_macdhist'] > 0     # histogram green
        df['200_macd_Cross_Down'] = df['200_macdhist'] < 0     # histogram red

                # Detect same-side weakening
        same_side_decreasing_200MACD = (
            ((df["200_macdhist"] > 0) & (df["200_macdhist"] < df["200_macdhist"].shift(1))) |  # dark green from light green
            ((df["200_macdhist"] < 0) & (df["200_macdhist"] > df["200_macdhist"].shift(1)))    # dark red from light red
        )

        df["Histogram_Decreasing_200MACD"] = same_side_decreasing_200MACD 

        df['MACD_COLOR_200'] = np.select(
            [
                (df['200_macd'] > df['200_Signal_Line']) & ~df["Histogram_Decreasing_200MACD"],  # Dark green
                (df['200_macd'] > df['200_Signal_Line']) & df["Histogram_Decreasing_200MACD"],   # Light green
                (df['200_macd'] < df['200_Signal_Line']) & ~df["Histogram_Decreasing_200MACD"],  # Dark red
                (df['200_macd'] < df['200_Signal_Line']) & df["Histogram_Decreasing_200MACD"],   # Light red
            ],
            [
                'DARK_GREEN',
                'LIGHT_GREEN',
                'DARK_RED',
                'LIGHT_RED'
            ],
            default='NONE'
        )

        df['macd_color_signal_200MACD'] = np.select(
            [
                (df['MACD_COLOR_200'] == 'DARK_GREEN'),
                (df['MACD_COLOR_200'] == 'DARK_RED')
            ],
            [
                'BUY',
                'SELL'
            ],
            default='NONE'
        )



        df['200_macd_pos'] =  np.where(
            df['200_macd_Cross_Up'], 'BUY',
            np.where(
                df['200_macd_Cross_Down'], 'SELL',
                np.nan
            )
        )
     

        # df['two_pole_MACD_Cross_Up'] = (df['two_pole_macd'] > df['two_pole_Signal_Line']) & (df['two_pole_macd'].shift(1) <= df['two_pole_Signal_Line'].shift(1))
        # df['two_pole_MACD_Cross_Down'] = (df['two_pole_macd'] < df['two_pole_Signal_Line']) & (df['two_pole_macd'].shift(1) >= df['two_pole_Signal_Line'].shift(1))

        df['two_pole_MACD_Cross_Up'] = df['two_pole_macdhist'] > 0
        df['two_pole_MACD_Cross_Down'] = df['two_pole_macdhist'] < 0

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

        lower_same_side_decreasing = (
            ((df["lower_two_pole_macdhist"] > 0) & (df["lower_two_pole_macdhist"] < df["lower_two_pole_macdhist"].shift(1))) |  # dark green from light green
            ((df["lower_two_pole_macdhist"] < 0) & (df["lower_two_pole_macdhist"] > df["lower_two_pole_macdhist"].shift(1)))    # dark red from light red
        )

        # Combine both conditions
        df["Lower_Histogram_Decreasing"] = lower_same_side_decreasing 


        df['LOWER_MACD_COLOR'] = np.select(
            [
                (df['lower_two_pole_macd'] > df['lower_two_pole_Signal_Line']) & ~df["Lower_Histogram_Decreasing"],  # Dark green
                (df['lower_two_pole_macd'] > df['lower_two_pole_Signal_Line']) & df["Lower_Histogram_Decreasing"],   # Light green
                (df['lower_two_pole_macd'] < df['lower_two_pole_Signal_Line']) & ~df["Lower_Histogram_Decreasing"],  # Dark red
                (df['lower_two_pole_macd'] < df['lower_two_pole_Signal_Line']) & df["Lower_Histogram_Decreasing"],   # Light red
            ],
            [
                'DARK_GREEN',
                'LIGHT_GREEN',
                'DARK_RED',
                'LIGHT_RED'
            ],
            default='NONE'
        )

        df['lower_macd_color_signal'] = np.select(
            [
                (df['LOWER_MACD_COLOR'] == 'DARK_GREEN') | (df['LOWER_MACD_COLOR'] == 'LIGHT_RED'),
                (df['LOWER_MACD_COLOR'] == 'LIGHT_GREEN') | (df['LOWER_MACD_COLOR'] == 'DARK_RED')
            ],
            [
                'BUY',
                'SELL'
            ],
            default='NONE'
        )        
        

        # # Detect bullish crossover: red → green histogram
        # bullish_crossover = (
        #     (df["two_pole_macdhist"].shift(1) < 0) & (df["two_pole_macdhist"] > 0)
        # )

        # # Detect bearish crossover: green → red
        # bearish_crossover = (
        #     (df["two_pole_macdhist"].shift(1) > 0) & (df["two_pole_macdhist"] < 0)
        # )

        # Detect bullish crossover: red → green signal line
        bullish_crossover = (
            (df["two_pole_macdhist"].shift(1) < 0) & (df["two_pole_macdhist"] > 0)
        )

        # Detect bearish crossover: green → red
        bearish_crossover = (
            (df["two_pole_macdhist"].shift(1) > 0) & (df["two_pole_macdhist"] < 0)
        )


        
        
        df['ADX'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)



        df['two_pole_trade_signal'] = np.where(
                            df['two_pole_Signal_Line'] > 0,
                            'BUY',
                            'SELL'
                    )


        # Optional: store crossover types in their own columns
        df["two_pole_MACD_CrossOver"] = np.where(
            bullish_crossover, 'BUY',
            np.where(
                bearish_crossover, 'SELL',
                np.nan
            )
        )

        # ------------------------------------------------------------------
        # 0) Shortcuts
        # ------------------------------------------------------------------
        hist = df['two_pole_macdhist']          # MACD histogram (13,21,9)
        hist_abs = hist.abs()

        # ------------------------------------------------------------------
        # 1) Basic histogram crossovers through zero
        #    red → green = bullish, green → red = bearish
        # ------------------------------------------------------------------
        bullish_cross_hist = (hist.shift(1) < 0) & (hist > 0)
        bearish_cross_hist = (hist.shift(1) > 0) & (hist < 0)
        is_cross = bullish_cross_hist | bearish_cross_hist

        df['MACD_hist_cross'] = np.where(
            bullish_cross_hist, 'BUY',
            np.where(bearish_cross_hist, 'SELL', 'NONE')
        )

        # ------------------------------------------------------------------
        # 2) Define "waves" of histogram: continuous positive or negative
        #    (tiny zeros are treated as continuation of previous sign)
        # ------------------------------------------------------------------
        sign = np.sign(hist)
        sign_filled = sign.replace(0, np.nan).ffill().fillna(0)

        # New wave whenever sign changes (+1 <-> -1)
        wave_id = (sign_filled != sign_filled.shift(1)).cumsum()
        df['macd_wave_id'] = wave_id

        # ------------------------------------------------------------------
        # 3) For each wave: peak distance from 0 and "curve vs flat"
        # ------------------------------------------------------------------
        df['macd_wave_peak_abs'] = np.nan      # max |hist| in this wave
        df['macd_wave_is_curve'] = False       # True = proper curve (rise+fall)

        for wid, grp in df.groupby(wave_id):
            idx  = grp.index
            vals = hist_abs.loc[idx].values

            if len(vals) == 0:
                continue

            peak_abs = vals.max()
            curve = False

            # We only consider it a real "curve" if:
            # - at least 3 bars in the wave
            # - peak is inside (not first/last bar)
            # - there is some increase before peak and some decrease after
            if len(vals) >= 3:
                peak_pos = vals.argmax()            # index in 0..len-1
                if 0 < peak_pos < len(vals) - 1:    # not at edges
                    before = vals[:peak_pos+1]      # up to and incl. peak
                    after  = vals[peak_pos:]        # from peak onwards

                    incr_before = (np.diff(before) > 0).any()
                    decr_after  = (np.diff(after)  < 0).any()

                    curve = incr_before and decr_after

            df.loc[idx, 'macd_wave_peak_abs'] = peak_abs
            df.loc[idx, 'macd_wave_is_curve'] = curve

        # ------------------------------------------------------------------
        # 4) At each NEW crossover, read the PREVIOUS wave's stats
        #    (wave that just ended at bar i-1)
        # ------------------------------------------------------------------
        df['macd_prev_wave_peak_abs'] = np.where(
            is_cross,
            df['macd_wave_peak_abs'].shift(1),   # previous bar's wave peak
            np.nan
        )

        df['macd_prev_wave_is_curve'] = np.where(
            is_cross,
            df['macd_wave_is_curve'].shift(1),   # previous bar's wave shape
            False
        )

        # (optional) forward-fill if you want to refer later
        df['macd_prev_wave_peak_abs_ffill'] = df['macd_prev_wave_peak_abs'].ffill()
        df['macd_prev_wave_is_curve_ffill'] = df['macd_prev_wave_is_curve'].ffill()

        # ------------------------------------------------------------------
        # 5) Final "valid crossover" signals:
        #    - previous wave is a proper curve
        #    - previous wave had enough amplitude away from zero
        # ------------------------------------------------------------------
        # You will tune this threshold per symbol/timeframe
        min_prev_peak = 0.0005  # example; adjust after looking at data

        df['macd_valid_bullish_cross'] = (
            bullish_cross_hist &
            df['macd_prev_wave_is_curve'] &
            (df['macd_prev_wave_peak_abs'] >= min_prev_peak)
        )

        df['macd_valid_bearish_cross'] = (
            bearish_cross_hist &
            df['macd_prev_wave_is_curve'] &
            (df['macd_prev_wave_peak_abs'] >= min_prev_peak)
        )

        df['MACD_VALID_CROSS_SIGNAL'] = np.where(
            df['macd_valid_bullish_cross'], 'BUY',
            np.where(df['macd_valid_bearish_cross'], 'SELL', 'NONE')
        )



        bullish_stack = (
            (df['ema_9']  > df['ema_14']) &
            (df['ema_14'] > df['ema_21']) &
            (df['ema_21'] > df['ema_39']) &
            (df['ema_39'] > df['ema_50'])
        )

        bearish_stack = (
            (df['ema_9']  < df['ema_14']) &
            (df['ema_14'] < df['ema_21']) &
            (df['ema_21'] < df['ema_39']) &
            (df['ema_39'] < df['ema_50'])
        )

        df['all_ema_trend'] = np.where(
            bullish_stack, 'bullish',
            np.where(bearish_stack, 'bearish', 'neutral')
        )

        # Optional: direct BUY/SELL signal using price + stacked EMAs
        df['ALL_EMA_SIGNAL'] = np.where(
            bullish_stack & (df[close_col] > df['ema_9']),  'BUY',
            np.where(bearish_stack & (df[close_col] < df['ema_9']), 'SELL', 'NONE')
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

        df['ha_trend_up'] = df[close_col] > df[open_col]
        df['ha_trend_down'] = df[close_col] < df[open_col]

        # === Delta Volume (Pine-style) ======================================
        # We follow the script logic:
        # - Trend is the boolean is_trend_up (here derived from zlema_trend).
        # - While the trend regime stays the same, we accumulate:
        #     up_trend_volume  += volume on GREEN bars (close > open)
        #     down_trend_volume+= volume on RED   bars (close < open)
        # - When trend flips, both counters reset to 0.

        # 1) Trend booleans and crosses (reuse your zlema_trend)
        df['is_trend_up'] = (df['zlema_trend'] == 1)

        df['trend_cross_up']   = (~df['is_trend_up'].shift(1).fillna(False)) & (df['is_trend_up'])
        df['trend_cross_down'] = (df['is_trend_up'].shift(1).fillna(False)) & (~df['is_trend_up'])

        # 2) Build regime groups: a new group each time trend changes
        trend_change = df['is_trend_up'] != df['is_trend_up'].shift(1)
        regime_id = trend_change.cumsum()

        # 3) GREEN / RED volume by your chosen candle type
        green_vol = np.where(df[close_col] > df[open_col], df['volume'].astype(float), 0.0)
        red_vol   = np.where(df[close_col] < df[open_col], df['volume'].astype(float), 0.0)

        # 4) Cumulative sums inside each regime (reset on flip)
        df['up_trend_volume']   = pd.Series(green_vol, index=df.index).groupby(regime_id).cumsum()
        df['down_trend_volume'] = pd.Series(red_vol,   index=df.index).groupby(regime_id).cumsum()

        # 5) Delta volume % = ((Buy - Sell) / average(Buy,Sell)) * 100, safe when avg==0
        avg_vol = (df['up_trend_volume'] + df['down_trend_volume']) / 2.0
        df['delta_volume_pct'] = np.where(
            avg_vol > 0,
            ((df['up_trend_volume'] - df['down_trend_volume']) / avg_vol) * 100.0,
            0.0
        )
        # =====================================================================




        # Previous HA open (shifted by one bar)
        prev_ha_open = df[open_col].shift(1)


        # Price vs previous HA open
        df['price_vs_ha_open'] = df[close_col] > prev_ha_open

        # Raw exit flags (independent of your position state)
        df['exit_long_raw']  = df['ha_trend_down'] | (~df['price_vs_ha_open'].fillna(False))
        df['exit_short_raw'] = df['ha_trend_up']   | ( df['price_vs_ha_open'].fillna(False))

  
        # 6. Consolidation detection
        bb_upper, bb_middle, bb_lower = talib.BBANDS(
            df[close_col],
            timeperiod=3,
            nbdevup=2,
            nbdevdn=2,
            matype=MA_Type.SMA
        )
        

        df['BB_Width'] = df['BOLL_upper_band'] - df['BOLL_lower_band']
        df['bb_flat_market'] = df['BB_Width'] < df['BB_Width'].rolling(window=20).mean()
        
        flat_window = 3  # try 10–14 on 15m/30m, 20 on 1m/3m
        hiN = df[high_col].rolling(flat_window).max()
        loN = df[low_col].rolling(flat_window).min()
        ref_price = df['close'].rolling(flat_window).mean()

        df['price_range'] = (hiN - loN) / ref_price
        df['price_range_flat_market'] = df['price_range'] < 0.02  # start with 2%

        df['consolidating'] = df['bb_flat_market'] & df['price_range_flat_market']
        
       

        # 7. Swing highs/lows detection (Optimized)
        window = 5
        
        is_swing_high = df[high_col] == df[high_col].rolling(window*2+1, center=True).max()
        is_swing_low  = df[low_col]  == df[low_col].rolling(window*2+1, center=True).min()

        df['swing_high'] = is_swing_high
        df['swing_low']  = is_swing_low

        df['swing_high_zone'] = np.where(is_swing_high, df[high_col], np.nan)
        df['swing_low_zone']  = np.where(is_swing_low,  df[low_col],  np.nan)

        df['swing_high_zone'] = df['swing_high_zone'].ffill()
        df['swing_low_zone']  = df['swing_low_zone'].ffill()


        # ============================================================
        # PRICE ACTION TREND (LIVE-SAFE) using CONFIRMED swing points
        # NOTE: your swing_high/swing_low uses center=True => lookahead.
        # So we delay by `window` bars to make it live-safe.
        # ============================================================
        pa_confirm_delay = window  # same window used in swing detection (5)

        df['pa_swing_high'] = df['swing_high'].shift(pa_confirm_delay).fillna(False)
        df['pa_swing_low']  = df['swing_low'].shift(pa_confirm_delay).fillna(False)

        # price at the confirmed swing (shifted value)
        df['pa_swing_high_price'] = np.where(df['pa_swing_high'], df[high_col].shift(pa_confirm_delay), np.nan)
        df['pa_swing_low_price']  = np.where(df['pa_swing_low'],  df[low_col].shift(pa_confirm_delay),  np.nan)

        # Keep last confirmed swing levels (ffill)
        df['pa_swing_high_zone'] = pd.Series(df['pa_swing_high_price'], index=df.index).ffill()
        df['pa_swing_low_zone']  = pd.Series(df['pa_swing_low_price'],  index=df.index).ffill()

        # Output columns
        df['PA_STRUCTURE_BREAK'] = 'NONE'
        df['PA_TREND'] = 'RANGE'
        df['PA_TREND_CHANGE'] = 'NONE'




        # ---------------------------------------------------------
        # 5 / 8 EMA cross + regime vs EMA 100 (BUY + SELL logic)
        # ---------------------------------------------------------

        # 1) 5 vs 8 relationship and crossovers
        df['ema_5_above_8'] = df['ema_5'] > df['ema_8']
        prev_5_above_8 = df['ema_5_above_8'].shift(1)

        # Bullish crossover: 5 crosses UP above 8
        df['ema_5_8_cross_up'] = (df['ema_5_above_8']) & (prev_5_above_8 == False)

        # Bearish crossover: 5 crosses DOWN below 8
        df['ema_5_8_cross_down'] = (~df['ema_5_above_8']) & (prev_5_above_8 == True)

        # 2) 5 & 8 vs 100: regimes

        both_above_100 = (df['ema_5'] > df['ema_100']) & (df['ema_8'] > df['ema_100'])
        both_below_100 = (df['ema_5'] < df['ema_100']) & (df['ema_8'] < df['ema_100'])

        prev_both_above_100 = both_above_100.shift(1).fillna(False)
        prev_both_below_100 = both_below_100.shift(1).fillna(False)

        # "ema 5 and ema 8 cross ema 100" from BELOW to ABOVE  → BUY regime start
        df['ema_5_8_cross_ema100_up'] = both_above_100 & (~prev_both_above_100)

        # "ema 5 and ema 8 cross ema 100" from ABOVE to BELOW → SELL regime start
        df['ema_5_8_cross_ema100_down'] = both_below_100 & (~prev_both_below_100)

        # 3) State: first & second BUY and SELL after regime start

        df['ema_5_8_buy_rank']  = 0        # 0 = none, 1 = first buy, 2 = second buy
        df['ema_5_8_buy_signal']  = 'NONE' # 'BUY' only on those bars

        df['ema_5_8_sell_rank'] = 0        # 0 = none, 1 = first sell, 2 = second sell
        df['ema_5_8_sell_signal'] = 'NONE' # 'SELL' only on those bars

        buy_regime  = False
        sell_regime = False
        buy_count   = 0
        sell_count  = 0

                # --- RSI Divergence prep (no loop yet) ------------------------------
        lookback_left  = 5
        lookback_right = 5
        range_lower    = 5
        range_upper    = 60

        rsi_series = df['RSI_14']
        price_low  = df[low_col]
        price_high = df[high_col]

        # Pivot detection on RSI (similar to ta.pivotlow/pivothigh)
        pivot_window = lookback_left + lookback_right + 1
        rsi_min = rsi_series.rolling(window=pivot_window, center=True).min()
        rsi_max = rsi_series.rolling(window=pivot_window, center=True).max()

        pivot_low  = (rsi_series == rsi_min)
        pivot_high = (rsi_series == rsi_max)

        # Init divergence columns
        df['rsi_bull_div'] = False
        df['rsi_bear_div'] = False
        df['RSI_30_70']    = False   # start pivot in 30/70 zone

        # Numpy views for the single loop
        rsi_vals   = rsi_series.to_numpy()
        low_vals   = price_low.to_numpy()
        high_vals  = price_high.to_numpy()
        pl_vals    = pivot_low.to_numpy()
        ph_vals    = pivot_high.to_numpy()

        # --- Init columns used by loop -------------------------------------
        df['RSI_9_MACD']          = np.nan
        df['TAKEACTION']          = np.nan
        df['breakout_entry']      = np.nan   # 'BUY' / 'SELL'
        df['breakout_long_state'] = np.nan
        df['breakout_short_state']= np.nan
        df['DIVERGEN_SIGNAL']     = np.nan   # raw (non-live) structure-break

        # state machines
        state_rsi_macd       = None    # 'BUY' / 'SELL' / None  (RSI→MACD logic)
        state_breakout_long  = 'IDLE'  # 'IDLE','WAIT_PULLBACK','WAIT_MACD'
        state_breakout_short = 'IDLE'  # same for short side

        # RSI divergence state: last pivot indices
        prev_low_idx  = None   # last RSI pivot low index
        prev_high_idx = None   # last RSI pivot high index

            # *** ADD THESE TWO LINES ***
        pending_div_type  = None     # 'BULL' or 'BEAR' for RAW divergence
        pending_div_level = np.nan   # swing level for RAW divergence
        # ****************************

        # Flag: divergence that starts from classic 30/70 RSI zones
        RSI_OVERSOLD   = 30
        RSI_OVERBOUGHT = 70


        # ---- PA Trend state memory ----
        pa_trend = 'RANGE'
        pa_last_high = np.nan
        pa_prev_high = np.nan
        pa_last_low  = np.nan
        pa_prev_low  = np.nan

        # Numpy for speed
        pa_sh = df['pa_swing_high'].to_numpy(dtype=bool)
        pa_sl = df['pa_swing_low'].to_numpy(dtype=bool)
        pa_sh_price = df['pa_swing_high_price'].to_numpy(dtype=np.float64)
        pa_sl_price = df['pa_swing_low_price'].to_numpy(dtype=np.float64)

        idx_pa_break  = df.columns.get_loc('PA_STRUCTURE_BREAK')
        idx_pa_trend  = df.columns.get_loc('PA_TREND')
        idx_pa_change = df.columns.get_loc('PA_TREND_CHANGE')


        # ---------- MAIN LOOP OVER BARS ------------------------------------
        # ---------- RAW divergence detection (with 30/70 tagging) ----------
        for i in range(1, len(df)):


        # current regime side
            curr_both_above_100 = bool(both_above_100.iloc[i])
            curr_both_below_100 = bool(both_below_100.iloc[i])

            # ----- start regimes -----
            if df['ema_5_8_cross_ema100_up'].iloc[i]:
                buy_regime = True
                buy_count  = 0    # reset buys for new up-regime

            if df['ema_5_8_cross_ema100_down'].iloc[i]:
                sell_regime = True
                sell_count  = 0   # reset sells for new down-regime

            # ----- end regimes if EMAs leave that side of ema_100 -----
            if buy_regime and not curr_both_above_100:
                buy_regime = False
                buy_count  = 0

            if sell_regime and not curr_both_below_100:
                sell_regime = False
                sell_count  = 0

            # ----- inside BUY regime -----
            if buy_regime:
                cond_crossover_buy = bool(df['ema_5_8_cross_up'].iloc[i])
                cond_above_100     = df[close_col].iloc[i] > df['ema_100'].iloc[i]

                # Only 1st and 2nd crossover after regime start
                if cond_crossover_buy and cond_above_100 and buy_count < 20:
                    buy_count += 1
                    df.iat[i, df.columns.get_loc('ema_5_8_buy_rank')]   = buy_count
                    df.iat[i, df.columns.get_loc('ema_5_8_buy_signal')] = 'BUY'

            # ----- inside SELL regime -----
            if sell_regime:
                cond_crossover_sell = bool(df['ema_5_8_cross_down'].iloc[i])
                cond_below_100      = df[close_col].iloc[i] < df['ema_100'].iloc[i]

                # Only 1st and 2nd crossover after regime start
                if cond_crossover_sell and cond_below_100 and sell_count < 20:
                    sell_count += 1
                    df.iat[i, df.columns.get_loc('ema_5_8_sell_rank')]   = sell_count
                    df.iat[i, df.columns.get_loc('ema_5_8_sell_signal')] = 'SELL'


            # Common values for this bar
            rsi_9     = df['RSI_9'].iloc[i]
            cross     = df['two_pole_MACD_CrossOver'].iloc[i]   # 'BUY'/'SELL'/nan

            close_i    = df[close_col].iloc[i]
            ema_i      = df['ema_100'].iloc[i]
            prev_close = df[close_col].iloc[i - 1]

            last_high  = df['swing_high_zone'].iloc[i]
            last_low   = df['swing_low_zone'].iloc[i]


                        # ============================================================
            # PRICE ACTION TREND update (confirmed swings + structure break)
            # ============================================================
            prev_pa_trend = pa_trend

            # Update last/prev swing highs/lows ONLY when a new confirmed swing prints
            if pa_sh[i] and not np.isnan(pa_sh_price[i]):
                pa_prev_high = pa_last_high
                pa_last_high = pa_sh_price[i]

            if pa_sl[i] and not np.isnan(pa_sl_price[i]):
                pa_prev_low = pa_last_low
                pa_last_low = pa_sl_price[i]

            # Structure break signals
            pa_break = 'NONE'
            if not np.isnan(pa_last_high) and close_i > pa_last_high:
                pa_break = 'BREAK_UP'
                pa_trend = 'UPTREND'
            elif not np.isnan(pa_last_low) and close_i < pa_last_low:
                pa_break = 'BREAK_DOWN'
                pa_trend = 'DOWNTREND'
            else:
                # No break => use HH/HL or LH/LL
                if (not np.isnan(pa_prev_high)) and (not np.isnan(pa_prev_low)):
                    is_hh_hl = (pa_last_high > pa_prev_high) and (pa_last_low > pa_prev_low)
                    is_lh_ll = (pa_last_high < pa_prev_high) and (pa_last_low < pa_prev_low)

                    if is_hh_hl:
                        pa_trend = 'UPTREND'
                    elif is_lh_ll:
                        pa_trend = 'DOWNTREND'
                    else:
                        pa_trend = 'RANGE'
                else:
                    pa_trend = 'RANGE'

                # If consolidating and no break => RANGE (optional but recommended)
                if bool(df['consolidating'].iloc[i]):
                    pa_trend = 'RANGE'

            # Trend change label
            pa_change = 'NONE'
            if pa_trend != prev_pa_trend:
                pa_change = 'UP' if pa_trend == 'UPTREND' else ('DOWN' if pa_trend == 'DOWNTREND' else 'NONE')

            # Write to df
            df.iat[i, idx_pa_break]  = pa_break
            df.iat[i, idx_pa_trend]  = pa_trend
            df.iat[i, idx_pa_change] = pa_change


            # ----------------- RAW divergence (future-aware) ----------------
            # Bullish divergence: RSI higher low, price lower low
            if pl_vals[i]:
                if prev_low_idx is not None:
                    dist = i - prev_low_idx
                    if range_lower <= dist <= range_upper:
                        rsi_higher_low  = rsi_vals[i]  > rsi_vals[prev_low_idx]
                        price_lower_low = low_vals[i]  < low_vals[prev_low_idx]
                        if rsi_higher_low and price_lower_low:
                            df.iloc[i, df.columns.get_loc('rsi_bull_div')] = True

                            # mark if starting pivot was oversold
                            if rsi_vals[prev_low_idx] < RSI_OVERSOLD:
                                df.iloc[i, df.columns.get_loc('RSI_30_70')] = True

                prev_low_idx = i

            # Bearish divergence: RSI lower high, price higher high
            if ph_vals[i]:
                if prev_high_idx is not None:
                    dist = i - prev_high_idx
                    if range_lower <= dist <= range_upper:
                        rsi_lower_high    = rsi_vals[i]   < rsi_vals[prev_high_idx]
                        price_higher_high = high_vals[i]  > high_vals[prev_high_idx]
                        if rsi_lower_high and price_higher_high:
                            df.iloc[i, df.columns.get_loc('rsi_bear_div')] = True

                            # mark if starting pivot was overbought
                            if rsi_vals[prev_high_idx] > RSI_OVERBOUGHT:
                                df.iloc[i, df.columns.get_loc('RSI_30_70')] = True

                prev_high_idx = i

            # ============================================================
            # (0.1) Divergence → wait for structure break (RAW VERSION)
            #       - On bullish divergence: wait for close > last swing HIGH
            #       - On bearish divergence: wait for close < last swing LOW
            # ============================================================
            if df['rsi_bull_div'].iloc[i]:
                pending_div_type  = 'BULL'
                pending_div_level = last_high    # swing high at divergence bar

            elif df['rsi_bear_div'].iloc[i]:
                pending_div_type  = 'BEAR'
                pending_div_level = last_low     # swing low at divergence bar

            # If we are armed, watch for price to break the reference swing
            if pending_div_type == 'BULL':
                if close_i > pending_div_level:
                    df.iloc[i, df.columns.get_loc('DIVERGEN_SIGNAL')] = 'BUY'
                    pending_div_type  = None
                    pending_div_level = np.nan

            elif pending_div_type == 'BEAR':
                if close_i < pending_div_level:
                    df.iloc[i, df.columns.get_loc('DIVERGEN_SIGNAL')] = 'SELL'
                    pending_div_type  = None
                    pending_div_level = np.nan

            # ================================================================
            # (A) RSI → MACD TAKEACTION (your old logic)
            # ================================================================
            if rsi_9 > 70:
                state_rsi_macd = 'SELL'
            elif rsi_9 < 30:
                state_rsi_macd = 'BUY'

            if state_rsi_macd is not None and cross == state_rsi_macd:
                # Fire TAKEACTION on matching crossover
                df.iloc[i, df.columns.get_loc('TAKEACTION')] = state_rsi_macd
                state_rsi_macd = None

            # store current RSI_9_MACD state (for debugging / analysis)
            df.iloc[i, df.columns.get_loc('RSI_9_MACD')] = state_rsi_macd

            # ================================================================
            # (B1) Long breakout → pullback → MACD BUY
            # ================================================================
            breakout_long = (
                (close_i > ema_i) and
                (close_i > last_high) and
                ((prev_close <= ema_i) or (prev_close <= last_high))
            )

            if state_breakout_long == 'IDLE':
                if breakout_long:
                    state_breakout_long = 'WAIT_PULLBACK'

            elif state_breakout_long == 'WAIT_PULLBACK':
                # Pullback DOWN to EMA
                if close_i <= ema_i:
                    state_breakout_long = 'WAIT_MACD'
                # Optional invalidation: too deep under EMA
                elif close_i < ema_i * 0.99:
                    state_breakout_long = 'IDLE'

            elif state_breakout_long == 'WAIT_MACD':
                if cross == 'BUY':
                    df.iloc[i, df.columns.get_loc('breakout_entry')] = 'BUY'
                    state_breakout_long = 'IDLE'
                elif close_i < ema_i * 0.99:
                    state_breakout_long = 'IDLE'

            # ================================================================
            # (B2) Short breakout → pullback → MACD SELL
            # ================================================================
            breakout_short = (
                (close_i < ema_i) and
                (close_i < last_low) and
                ((prev_close >= ema_i) or (prev_close >= last_low))
            )

            if state_breakout_short == 'IDLE':
                if breakout_short:
                    state_breakout_short = 'WAIT_PULLBACK'

            elif state_breakout_short == 'WAIT_PULLBACK':
                # Pullback UP to EMA
                if close_i >= ema_i:
                    state_breakout_short = 'WAIT_MACD'
                # Optional invalidation: too far above EMA
                elif close_i > ema_i * 0.5:
                    state_breakout_short = 'IDLE'

            elif state_breakout_short == 'WAIT_MACD':
                if cross == 'SELL':
                    df.iloc[i, df.columns.get_loc('breakout_entry')] = 'SELL'
                    state_breakout_short = 'IDLE'
                elif close_i > ema_i * 0.5:
                    state_breakout_short = 'IDLE'

            # Save states for debugging / analysis
            df.iloc[i, df.columns.get_loc('breakout_long_state')]  = state_breakout_long
            df.iloc[i, df.columns.get_loc('breakout_short_state')] = state_breakout_short

        # ---------- AFTER LOOP: labels & LIVE-safe divergence ---------------

        # RAW divergence label – for plotting / debug only
        df['RSI_DIVERGENCE_RAW'] = np.where(
            df['rsi_bull_div'], 'BULL',
            np.where(df['rsi_bear_div'], 'BEAR', 'NONE')
        )

        # LIVE-SAFE divergence (shift by right lookback)
        confirm_delay = lookback_right  # 5

        df['rsi_bull_div_live'] = df['rsi_bull_div'].shift(confirm_delay).fillna(False)
        df['rsi_bear_div_live'] = df['rsi_bear_div'].shift(confirm_delay).fillna(False)
        df['RSI_30_70_LIVE']    = df['RSI_30_70'].shift(confirm_delay).fillna(False)

        df['RSI_DIVERGENCE_LIVE'] = np.where(
            df['rsi_bull_div_live'], 'BULL',
            np.where(df['rsi_bear_div_live'], 'BEAR', 'NONE')
        )

        # Treat RSI_DIVERGENCE as live version for logic
        df['RSI_DIVERGENCE'] = df['RSI_DIVERGENCE_LIVE']

        # Last divergence timestamp (LIVE)
        if 'time' in df.columns:
            time_series = pd.to_datetime(df['time'])
        else:
            time_series = pd.to_datetime(df.index)

        df['last_divergenen_time_live'] = np.nan

        mask_bull_live = df['rsi_bull_div_live']
        mask_bear_live = df['rsi_bear_div_live']

        df.loc[mask_bull_live, 'last_divergenen_time_live'] = (
            time_series[mask_bull_live].dt.strftime('%Y-%m-%d-%H::%M') + '_BULL'
        )
        df.loc[mask_bear_live, 'last_divergenen_time_live'] = (
            time_series[mask_bear_live].dt.strftime('%Y-%m-%d-%H::%M') + '_BEAR'
        )

        df['last_divergenen_time_live'] = df['last_divergenen_time_live'].ffill()
        df['last_divergenen_time'] =  df['last_divergenen_time_live'] 

        # LIVE divergence → structure-break entry signal
        df['DIVERGEN_SIGNAL_LIVE'] = np.nan

        pending_div_type  = None     # 'BULL' or 'BEAR'
        pending_div_level = np.nan   # swing level to break

        for i in range(len(df)):
            close_i   = df[close_col].iloc[i]
            last_high = df['swing_high_zone'].iloc[i]
            last_low  = df['swing_low_zone'].iloc[i]

            # Arm on LIVE divergence, not raw
            if df['rsi_bull_div_live'].iloc[i]:
                pending_div_type  = 'BULL'
                pending_div_level = last_high     # need break above this

            elif df['rsi_bear_div_live'].iloc[i]:
                pending_div_type  = 'BEAR'
                pending_div_level = last_low      # need break below this

            # Wait for structure break after divergence is confirmed
            if pending_div_type == 'BULL' and close_i > pending_div_level:
                df.iloc[i, df.columns.get_loc('DIVERGEN_SIGNAL_LIVE')] = 'BUY'
                pending_div_type  = None
                pending_div_level = np.nan

            elif pending_div_type == 'BEAR' and close_i < pending_div_level:
                df.iloc[i, df.columns.get_loc('DIVERGEN_SIGNAL_LIVE')] = 'SELL'
                pending_div_type  = None
                pending_div_level = np.nan

        # Simple final breakout label
        df['BREAKOUT_SIGNAL'] = np.where(
            df['breakout_entry'] == 'BUY',  'BUY',
            np.where(df['breakout_entry'] == 'SELL', 'SELL', 'NONE')
        )


        # =====================================================================
        
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


        df['Total_Change_Regular'] = ((df['close'] - df['open']) / df['open']) * 100
        # Round the total percentage change
        df['Total_Change_Regular'] = df['Total_Change_Regular'].round(2)  


        # --- EMA calculations ---
        df['ema8_high'] = talib.EMA(df['high'], timeperiod=8)
        df['ema8_low'] = talib.EMA(df['low'], timeperiod=8)

        df['ema34_high'] = talib.EMA(df['high'], timeperiod=34)
        df['ema34_low'] = talib.EMA(df['low'], timeperiod=34)

        df['ema144_close'] = talib.EMA(df['close'], timeperiod=144)
        df['ema233_close'] = talib.EMA(df['close'], timeperiod=233)

        # --- Buy and Sell Conditions ---
        df['3ema_buy_signal'] = (
            (df['ema8_high'] > df['ema34_high']) &
            (df['ema8_low'] > df['ema34_low']) &
            (df['ema34_high'] > df['ema144_close']) &
            (df['ema34_low'] > df['ema144_close']) &
            (df['ema144_close'] > df['ema233_close'])
        )

        df['3ema_sell_signal'] = (
            (df['ema8_high'] < df['ema34_high']) &
            (df['ema8_low'] < df['ema34_low']) &
            (df['ema34_high'] < df['ema144_close']) &
            (df['ema34_low'] < df['ema144_close']) &
            (df['ema144_close'] < df['ema233_close'])
        )

        ## added for flat maket and ema 9 signal check with all interval and follows lower to upper time frame

        # Keep all earlier columns on `df`, and add AO state from df_copy
        ao_col = andean_oscillator(df)['andean_oscillator']   # 1D Series aligned by index
        df['andean_oscillator'] = ao_col
       
       # CCI minimal on raw candles, then assign only needed cols back
        # tmp = cci_minimal(df_copy)  # returns df_copy with 3 new columns
        # cols = ['cci_entry_state', 'cci_exit_cross', 'cci_sma']
        # df[cols] = tmp[cols]        # index-aligned assign

        ### Here we need to add the 100 for ProLab

        # tmp = cci_minimal(df_copy,length=100)  # returns df_copy with 3 new columns
        # cols = ['cci_entry_state', 'cci_exit_cross', 'cci_sma']
        # df[cols] = tmp[cols]        # index-aligned assign


        # CCI(9)
        # tmp9 = cci_minimal(df, cci_len=9,  smoothing_len=20, exit_len=20, suffix="_9")
        # df[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9"]] = tmp9[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9"]]

        # # CCI(100)
        # tmp100 = cci_minimal(df, cci_len=100, smoothing_len=20, exit_len=20, suffix="_100")
        # df[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100"]] = tmp100[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100"]]

        tmp9 = cci_minimal(df, cci_len=9, smoothing_len=21, suffix="_9")
        
        df[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9","cci_value_9","cci_yellow_value_9"]] = tmp9[["cci_entry_state_9", "cci_exit_cross_9", "cci_sma_9","cci_value_9","cci_yellow_value_9"]]      

        # print(df[['cci_entry_state_9','cci_exit_cross_9','cci_sma_9']].tail(12))

        # CCI(100)
        tmp100 = cci_minimal(df, cci_len=20, smoothing_len=20, suffix="_100")
        df[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100","cci_value_100","cci_yellow_value_100"]] = tmp100[["cci_entry_state_100", "cci_exit_cross_100", "cci_sma_100","cci_value_100","cci_yellow_value_100"]]




        # Add TDFI state
        tmp = tdfi_assign_state_talib(
            df,                 # raw OHLC frame
            lookback=9,
            mmaLength=9, mmaMode="ema",
            smmaLength=9, smmaMode="ema",
            nLength=3, filterHigh=0.05, filterLow=-0.05
        )

        # Assign just the one column back to your working df
        df['tdfi_state'] = tmp['tdfi_state']

        # Access:
        df['tdfi_state'].iloc[-1]   # 'FLAT' | 'BULL' | 'BEAR'

        tmp1 = tdfi_assign_state_talib(
            df,                 # raw OHLC frame
            lookback=2,
            mmaLength=2, mmaMode="ema",
            smmaLength=2, smmaMode="ema",
            nLength=3, filterHigh=0.05, filterLow=-0.05
        )

        df['tdfi_state_2_ema'] = tmp1['tdfi_state']


        tmp2 = tdfi_assign_state_talib(
            df,                 # raw OHLC frame
            lookback=3,
            mmaLength=3, mmaMode="ema",
            smmaLength=3, smmaMode="ema",
            nLength=3, filterHigh=0.05, filterLow=-0.05
        )

        df['tdfi_state_3_ema'] = tmp2['tdfi_state']

        df = label_heikin_types(df)
        df = label_candle_types_regular(df)

                # === Price-action based exits (structure + patterns) ==============
        # 1) Structure break:
        #    - For LONG: close below last swing low → trend broken
        #    - For SHORT: close above last swing high → trend broken
        df['pa_structure_exit_long']  = df[close_col] < df['swing_low_zone']
        df['pa_structure_exit_short'] = df[close_col] > df['swing_high_zone']

        # 2) Reversal-pattern exits:
        #    - For longs: strong bearish candle/pattern (engulf, strong bear)
        #    - For shorts: strong bullish candle/pattern (engulf, hammer, etc.)
        df['pa_reversal_exit_long']  = df['pa_strong_bearish']
        df['pa_reversal_exit_short'] = df['pa_strong_bullish']

        # 3) Combine into raw PA exit flags
        df['pa_exit_long_raw']  = df['pa_structure_exit_long']  | df['pa_reversal_exit_long']
        df['pa_exit_short_raw'] = df['pa_structure_exit_short'] | df['pa_reversal_exit_short']

        # 4) Final combined exit hints (includes old HA exits)
        df['exit_long_price_action']  = df['exit_long_raw']  | df['pa_exit_long_raw']
        df['exit_short_price_action'] = df['exit_short_raw'] | df['pa_exit_short_raw']


                # --- StochRSI (RSI length=14, Stoch length=134, K=3, D=3) ---
        rsi_length   = 14
        stoch_length = 134
        k_smooth     = 3   # %K smoothing
        d_smooth     = 3   # %D smoothing

        # TA-Lib STOCHRSI:
        # timeperiod    = RSI length
        # fastk_period  = Stoch length
        # fastd_period  = first smoothing (we'll treat as pre-smoothing)
        srsi_k_raw, srsi_d_raw = talib.STOCHRSI(
            df[close_col],
            timeperiod=rsi_length,
            fastk_period=stoch_length,
            fastd_period=k_smooth,
            fastd_matype=MA_Type.SMA
        )

        # Map to TradingView-style K,D with extra smoothing:
        #  - stochrsi_k = SMA(raw_k, 3)
        #  - stochrsi_d = SMA(stochrsi_k, 3)
        df['stochrsi_k_raw'] = srsi_k_raw
        df['stochrsi_k']     = talib.SMA(df['stochrsi_k_raw'], timeperiod=k_smooth)
        df['stochrsi_d']     = talib.SMA(df['stochrsi_k'],      timeperiod=d_smooth)



                # --- Stochastic Oscillator 7,3,3 (on selected candle type) ---
        fastk_period = 7   # %K length
        slowk_period = 3   # %K smoothing
        slowd_period = 3   # %D smoothing

        df['stoch_k_7_3_3'], df['stoch_d_7_3_3'] = talib.STOCH(
            df[high_col],
            df[low_col],
            df[close_col],
            fastk_period=fastk_period,
            slowk_period=slowk_period,
            slowk_matype=MA_Type.SMA,
            slowd_period=slowd_period,
            slowd_matype=MA_Type.SMA
        )

        # Overbought / oversold helper flags
        df['stoch_7_3_3_overbought'] = df['stoch_k_7_3_3'] > 80
        df['stoch_7_3_3_oversold']   = df['stoch_k_7_3_3'] < 20

        # --- Stochastic 7,3,3 K/D cross signals with 20/80 filter ---

        k  = df['stoch_k_7_3_3']
        d  = df['stoch_d_7_3_3']
        k1 = k.shift(1)
        d1 = d.shift(1)

        # BUY:
        #  - K crosses ABOVE D
        #  - Both were below 20 on previous bar (oversold zone)
        df['stoch_7_3_3_cross_buy'] = (
            (k1 < d1) &           # previously K <= D
            (k > d)  &           # now K > D  → bullish cross
            (k1 < 50) #& (d1 < 20)  # both in oversold zone
        )

        # SELL:
        #  - K crosses BELOW D
        #  - Both were above 80 on previous bar (overbought zone)
        df['stoch_7_3_3_cross_sell'] = (
            (k1 > d1) &           # previously K >= D
            (k < d)  &           # now K < D → bearish cross
            (k1 > 50) #& (d1 > 80)  # both in overbought zone
        )

        # Combined signal column for convenience
        df['STOCH_7_3_3_SIGNAL'] = np.where(
            df['stoch_7_3_3_cross_buy'],  'BUY',
            np.where(df['stoch_7_3_3_cross_sell'], 'SELL', 'NONE')
        )

        df = add_flux_order_blocks(
                df,
                open_col=open_col,
                high_col=high_col,
                low_col=low_col,
                close_col=close_col,
                volume_col="volume",
                time_col="time",
                swing_length=10,
                atr_len=10,
                max_atr_mult=3.5,
                ob_end_method="Wick",   # or "Close"
                max_order_blocks=30,
                entry_confirm="close_outside",
                sl_buffer=0.0,
            )
        
        df = add_institutional_range_signals(
                df,
                open_col=open_col,
                high_col=high_col,
                low_col=low_col,
                close_col=close_col,
                volume_col="volume",
                range_len=48,          # tune
                atr_len=14,
                sweep_atr_mult=0.15,
                wick_ratio=1.6,
                vol_ratio_hi=1.5,
                near_atr=0.6,
                delta_thr=20.0
            )





        return df
        
    except Exception as e:
        print(f"Error in calculate_all_indicators_optimized: {e}")
        log_error(e, "calculate_all_indicators_optimized", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return df

def _atr_fallback(high, low, close, period=10):
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def add_flux_order_blocks(
    df: pd.DataFrame,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    time_col: str = "time",          # if missing, we’ll use df.index
    swing_length: int = 10,
    atr_len: int = 10,               # Flux script uses ta.atr(10)
    max_atr_mult: float = 3.5,
    ob_end_method: str = "Wick",     # "Wick" or "Close"
    max_order_blocks: int = 30,
    entry_confirm: str = "close_outside",  # "close_outside" (recommended)
    sl_buffer: float = 0.0,          # optional extra buffer beyond OB boundary
) -> pd.DataFrame:
    """
    Adds Flux-like order block zones + simple retest entry signals into df.

    Output columns (latest / most recent zone only):
      - OB_BULL_TOP, OB_BULL_BOTTOM, OB_BULL_BREAKER
      - OB_BEAR_TOP, OB_BEAR_BOTTOM, OB_BEAR_BREAKER
      - OB_SIGNAL: 'BUY'/'SELL'/''  (retest + confirmation)
      - OB_ENTRY_PRICE, OB_SL
    """

    df = df.copy()

    # ---- ATR ----
    if talib is not None:
        atr = talib.ATR(df[high_col], df[low_col], df[close_col], timeperiod=atr_len)
    else:
        atr = _atr_fallback(df[high_col], df[low_col], df[close_col], period=atr_len)
    df["ATR_OB"] = atr

    o = df[open_col].to_numpy(dtype=float)
    h = df[high_col].to_numpy(dtype=float)
    l = df[low_col].to_numpy(dtype=float)
    c = df[close_col].to_numpy(dtype=float)
    v = df[volume_col].to_numpy(dtype=float) if volume_col in df.columns else np.full(len(df), np.nan)

    if time_col in df.columns:
        t = df[time_col].to_numpy()
    else:
        t = df.index.to_numpy()

    n = len(df)
    if n < swing_length + 3:
        # still return columns even if not enough data
        for col in [
            "OB_BULL_TOP","OB_BULL_BOTTOM","OB_BULL_BREAKER",
            "OB_BEAR_TOP","OB_BEAR_BOTTOM","OB_BEAR_BREAKER",
            "OB_SIGNAL","OB_ENTRY_PRICE","OB_SL","ATR_OB"
        ]:
            if col not in df.columns:
                df[col] = np.nan if col not in ("OB_SIGNAL",) else ""
        return df

    # ---- Order block containers (like Pine lists) ----
    bullish = []  # newest at index 0
    bearish = []

    # ---- Swing state (Flux findOBSwings) ----
    swingType = 0  # 0=looking top, 1=looking bottom (same behavior as Pine var)
    prevSwingType = 0

    top_x = None
    top_y = np.nan
    top_crossed = False

    btm_x = None
    btm_y = np.nan
    btm_crossed = False

    # ---- Output arrays ----
    bull_top_arr = np.full(n, np.nan)
    bull_bot_arr = np.full(n, np.nan)
    bull_brk_arr = np.full(n, False, dtype=bool)

    bear_top_arr = np.full(n, np.nan)
    bear_bot_arr = np.full(n, np.nan)
    bear_brk_arr = np.full(n, False, dtype=bool)

    signal_arr = np.array([""] * n, dtype=object)
    entry_price_arr = np.full(n, np.nan)
    sl_arr = np.full(n, np.nan)

    # Retest tracking (so we can “touch then confirm”)
    pending_bull_touch = False
    pending_bear_touch = False
    pending_bull_zone = None
    pending_bear_zone = None

    def _min_oc(i):  # min(open,close)
        return min(o[i], c[i])

    def _max_oc(i):  # max(open,close)
        return max(o[i], c[i])

    for i in range(n):
        # ----------- findOBSwings(len) equivalent -----------
        # Pine:
        # upper = ta.highest(len), lower = ta.lowest(len)
        # swingType := high[len] > upper ? 0 : low[len] < lower ? 1 : swingType
        # if swingType == 0 and swingType[1] != 0 => top = (bar_index[len], high[len])
        # if swingType == 1 and swingType[1] != 1 => bottom = (bar_index[len], low[len])
        if i >= swing_length:
            upper = np.max(h[i - swing_length + 1 : i + 1])
            lower = np.min(l[i - swing_length + 1 : i + 1])

            prevSwingType = swingType

            if h[i - swing_length] > upper:
                swingType = 0
            elif l[i - swing_length] < lower:
                swingType = 1

            if swingType == 0 and prevSwingType != 0:
                top_x = i - swing_length
                top_y = h[top_x]
                top_crossed = False

            if swingType == 1 and prevSwingType != 1:
                btm_x = i - swing_length
                btm_y = l[btm_x]
                btm_crossed = False

        # ----------- update existing OBs (breaker logic) -----------
        # Bullish list breaker & removal
        if bullish:
            for k in range(len(bullish) - 1, -1, -1):
                ob = bullish[k]
                if not ob["breaker"]:
                    invalid = (l[i] < ob["bottom"]) if ob_end_method == "Wick" else (_min_oc(i) < ob["bottom"])
                    if invalid:
                        ob["breaker"] = True
                        ob["breakTime"] = t[i]
                        ob["bbVolume"] = v[i]
                else:
                    # remove if price goes above top after breaker
                    if h[i] > ob["top"]:
                        bullish.pop(k)

        # Bearish list breaker & removal
        if bearish:
            for k in range(len(bearish) - 1, -1, -1):
                ob = bearish[k]
                if not ob["breaker"]:
                    invalid = (h[i] > ob["top"]) if ob_end_method == "Wick" else (_max_oc(i) > ob["top"])
                    if invalid:
                        ob["breaker"] = True
                        ob["breakTime"] = t[i]
                        ob["bbVolume"] = v[i]
                else:
                    # remove if price goes below bottom after breaker
                    if l[i] < ob["bottom"]:
                        bearish.pop(k)

        # ----------- create new order blocks on structure break -----------
        # Bullish creation: if close > top.y and not top.crossed
        if top_x is not None and (not top_crossed) and c[i] > top_y:
            top_crossed = True

            # Pine init:
            # boxBtm = max[1] ; boxTop = min[1] ; boxLoc = time[1]
            if i >= 1:
                boxBtm = h[i - 1]
                boxTop = l[i - 1]
                boxLoc = t[i - 1]

                # loop: for j = 1 to (bar_index - top.x) - 1
                dist = i - top_x
                for j in range(1, max(dist - 1, 1)):
                    idx = i - j
                    if idx <= top_x:
                        break
                    new_btm = min(l[idx], boxBtm)
                    if new_btm != boxBtm:
                        boxBtm = new_btm
                        boxTop = h[idx]
                        boxLoc = t[idx]

                obSize = abs(boxTop - boxBtm)
                atr_i = df["ATR_OB"].iloc[i]
                if pd.notna(atr_i) and obSize <= atr_i * max_atr_mult:
                    new_ob = {
                        "top": float(boxTop),
                        "bottom": float(boxBtm),
                        "obVolume": float(v[i] + (v[i - 1] if i >= 1 else 0) + (v[i - 2] if i >= 2 else 0)),
                        "obType": "Bull",
                        "startTime": boxLoc,
                        "breaker": False,
                        "breakTime": None,
                        "bbVolume": np.nan,
                    }
                    bullish.insert(0, new_ob)
                    if len(bullish) > max_order_blocks:
                        bullish.pop()

        # Bearish creation: if close < btm.y and not btm.crossed
        if btm_x is not None and (not btm_crossed) and c[i] < btm_y:
            btm_crossed = True

            if i >= 1:
                # Pine init:
                # boxBtm = min[1] ; boxTop = max[1]
                boxBtm = l[i - 1]
                boxTop = h[i - 1]
                boxLoc = t[i - 1]

                dist = i - btm_x
                for j in range(1, max(dist - 1, 1)):
                    idx = i - j
                    if idx <= btm_x:
                        break
                    new_top = max(h[idx], boxTop)
                    if new_top != boxTop:
                        boxTop = new_top
                        boxBtm = l[idx]
                        boxLoc = t[idx]

                obSize = abs(boxTop - boxBtm)
                atr_i = df["ATR_OB"].iloc[i]
                if pd.notna(atr_i) and obSize <= atr_i * max_atr_mult:
                    new_ob = {
                        "top": float(boxTop),
                        "bottom": float(boxBtm),
                        "obVolume": float(v[i] + (v[i - 1] if i >= 1 else 0) + (v[i - 2] if i >= 2 else 0)),
                        "obType": "Bear",
                        "startTime": boxLoc,
                        "breaker": False,
                        "breakTime": None,
                        "bbVolume": np.nan,
                    }
                    bearish.insert(0, new_ob)
                    if len(bearish) > max_order_blocks:
                        bearish.pop()

        # ----------- write latest (most recent) zones into df arrays -----------
        if bullish:
            bull_top_arr[i] = bullish[0]["top"]
            bull_bot_arr[i] = bullish[0]["bottom"]
            bull_brk_arr[i] = bullish[0]["breaker"]

        if bearish:
            bear_top_arr[i] = bearish[0]["top"]
            bear_bot_arr[i] = bearish[0]["bottom"]
            bear_brk_arr[i] = bearish[0]["breaker"]

        # ----------- trading signals (simple & clean) -----------
        # We only trade FRESH zones (not breaker)
        active_bull = bullish[0] if bullish and (not bullish[0]["breaker"]) else None
        active_bear = bearish[0] if bearish and (not bearish[0]["breaker"]) else None

        # detect “touch / overlap” with zone
        bull_touch = False
        if active_bull is not None:
            bull_touch = (l[i] <= active_bull["top"]) and (h[i] >= active_bull["bottom"])

        bear_touch = False
        if active_bear is not None:
            bear_touch = (h[i] >= active_bear["bottom"]) and (l[i] <= active_bear["top"])

        # Arm touch -> confirm next candle
        if bull_touch:
            pending_bull_touch = True
            pending_bull_zone = active_bull

        if bear_touch:
            pending_bear_touch = True
            pending_bear_zone = active_bear

        # Confirmations
        if pending_bull_touch and pending_bull_zone is not None:
            # confirm buy when close closes back above OB.top
            if entry_confirm == "close_outside" and c[i] > pending_bull_zone["top"]:
                signal_arr[i] = "BUY"
                entry_price_arr[i] = c[i]
                sl_arr[i] = pending_bull_zone["bottom"] - sl_buffer
                pending_bull_touch = False
                pending_bull_zone = None

        if pending_bear_touch and pending_bear_zone is not None:
            # confirm sell when close closes back below OB.bottom
            if entry_confirm == "close_outside" and c[i] < pending_bear_zone["bottom"]:
                signal_arr[i] = "SELL"
                entry_price_arr[i] = c[i]
                sl_arr[i] = pending_bear_zone["top"] + sl_buffer
                pending_bear_touch = False
                pending_bear_zone = None

    # ---- attach columns ----
    df["OB_BULL_TOP"] = bull_top_arr
    df["OB_BULL_BOTTOM"] = bull_bot_arr
    df["OB_BULL_BREAKER"] = bull_brk_arr

    df["OB_BEAR_TOP"] = bear_top_arr
    df["OB_BEAR_BOTTOM"] = bear_bot_arr
    df["OB_BEAR_BREAKER"] = bear_brk_arr

    df["OB_SIGNAL"] = signal_arr
    df["OB_ENTRY_PRICE"] = entry_price_arr
    df["OB_SL"] = sl_arr

    return df




def add_institutional_range_signals(
    df: pd.DataFrame,
    open_col: str,
    high_col: str,
    low_col: str,
    close_col: str,
    volume_col: str = "volume",
    range_len: int = 48,          # 48 bars on 15m = 12 hours
    atr_len: int = 14,
    sweep_atr_mult: float = 0.15, # how far beyond range to count as "sweep"
    wick_ratio: float = 1.6,      # wick must be bigger than body * ratio
    vol_ratio_hi: float = 1.5,    # Volume_Ratio threshold
    near_atr: float = 0.6,        # how close to range edge (in ATRs)
    delta_thr: float = 20.0       # delta_volume_pct threshold
) -> pd.DataFrame:
    df = df.copy()

    # ----- ATR (use your ATR_OB if present, else compute TR/ATR quickly)
    prev_close = df[close_col].shift(1)
    tr = pd.concat([
        (df[high_col] - df[low_col]).abs(),
        (df[high_col] - prev_close).abs(),
        (df[low_col] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["TR"] = tr
    df["ATR_INST"] = tr.rolling(atr_len).mean()

    # ----- Range bounds on current timeframe (15m)
    df["RANGE_HIGH"] = df[high_col].rolling(range_len).max()
    df["RANGE_LOW"]  = df[low_col].rolling(range_len).min()
    df["RANGE_MID"]  = (df["RANGE_HIGH"] + df["RANGE_LOW"]) / 2.0
    df["RANGE_WIDTH_PCT"] = (df["RANGE_HIGH"] - df["RANGE_LOW"]) / df[close_col]

    # ----- Candle anatomy
    body = (df[close_col] - df[open_col]).abs()
    upper_wick = df[high_col] - df[[open_col, close_col]].max(axis=1)
    lower_wick = df[[open_col, close_col]].min(axis=1) - df[low_col]

    # Guards
    atr = df["ATR_INST"].replace(0, np.nan)

    # ----- Near-edge checks (where institutions work the most)
    dist_to_high_atr = (df["RANGE_HIGH"] - df[close_col]) / atr
    dist_to_low_atr  = (df[close_col] - df["RANGE_LOW"]) / atr
    df["NEAR_RANGE_HIGH"] = dist_to_high_atr <= near_atr
    df["NEAR_RANGE_LOW"]  = dist_to_low_atr  <= near_atr

    # ----- Absorption: high volume but not much movement
    # (TR small relative to ATR) + volume high
    if "Volume_Ratio" in df.columns:
        vol_ok = df["Volume_Ratio"] >= vol_ratio_hi
    else:
        vol_ok = pd.Series(False, index=df.index)
    df["ABSORPTION"] = vol_ok & ((df["TR"] / atr) < 0.8)

    # ----- Liquidity sweeps (stop hunts) + close back inside range
    prev_rh = df["RANGE_HIGH"].shift(1)
    prev_rl = df["RANGE_LOW"].shift(1)

    df["SWEEP_HIGH_REJECT"] = (
        (df[high_col] > prev_rh + sweep_atr_mult * atr) &
        (df[close_col] < prev_rh) &
        vol_ok &
        (upper_wick >= wick_ratio * body.replace(0, np.nan))
    )

    df["SWEEP_LOW_REJECT"] = (
        (df[low_col] < prev_rl - sweep_atr_mult * atr) &
        (df[close_col] > prev_rl) &
        vol_ok &
        (lower_wick >= wick_ratio * body.replace(0, np.nan))
    )

    # ----- Use your delta_volume_pct if present (already in your code)
    if "delta_volume_pct" in df.columns:
        dv = df["delta_volume_pct"]
    else:
        dv = pd.Series(0.0, index=df.index)

    # Accumulation/distribution bias inside range
    df["ACCUMULATION_HINT"] = df["NEAR_RANGE_LOW"] & df["ABSORPTION"] & (dv >= delta_thr)
    df["DISTRIBUTION_HINT"] = df["NEAR_RANGE_HIGH"] & df["ABSORPTION"] & (dv <= -delta_thr)

    # ----- Final institutional label
    df["INSTITUTIONAL_SIGNAL"] = np.select(
        [
            df["SWEEP_LOW_REJECT"],
            df["SWEEP_HIGH_REJECT"],
            df["ACCUMULATION_HINT"],
            df["DISTRIBUTION_HINT"],
        ],
        [
            "SWEEP_BUY",
            "SWEEP_SELL",
            "ACCUMULATE",
            "DISTRIBUTE",
        ],
        default="NONE"
    )

    # “Follow institution” entry permissions in ranges
    # (in range, only trade when there is real institutional footprint)
    df["FOLLOW_INST_BUY_OK"]  = df["SWEEP_LOW_REJECT"] | df["ACCUMULATION_HINT"]
    df["FOLLOW_INST_SELL_OK"] = df["SWEEP_HIGH_REJECT"] | df["DISTRIBUTION_HINT"]

    return df


def is_order_allowed(order_time, last_div_str, action,hour):
    """
    Block:
      - BUY  if a BEAR divergence happened in the last 24 hours
      - SELL if a BULL divergence happened in the last 24 hours
    Otherwise allow.
    """

    # If no proper action, allow
    if action not in ('BUY', 'SELL'):
        return True

    # Handle NaN / None / non-string
    if not isinstance(last_div_str, str) or not last_div_str.strip():
        return True

    # Expect "2025-08-23-05::45_BEAR"
    if '_' not in last_div_str:
        return True

    try:
        time_part, side = last_div_str.rsplit('_', 1)   # side = 'BULL' / 'BEAR'
        last_div_time = datetime.strptime(time_part, '%Y-%m-%d-%H::%M')
    except Exception:
        # If parsing fails, don't block
        return True

    # Time difference (only consider *past* divergences)
    delta = order_time - last_div_time

    # last_div_time must be in [0, 24h] before order_time
    if delta.total_seconds() < 0:
        # Divergence is in the future -> ignore
        return True

    within_24h = delta <= timedelta(hours=hour)

    # Rules with 24h window:
    # BUY blocked by BEAR in last 24 hours
    if action == 'BUY' and within_24h and side == 'BEAR':
        return False

    # SELL blocked by BULL in last 24 hours
    if action == 'SELL' and within_24h and side == 'BULL':
        return False

    return True

def label_heikin_types(df,
    doji_ratio=0.1,        # body <= 10% of range → DOJI
    spin_ratio=0.3,        # body <= 30% of range → SPIN_TOP
    strong_body=0.7,       # body >= 70% of range → STRONG_*
    hammer_wick=2.0,       # lower wick >= 2x body and upper wick small → HAMMER
    inv_hammer_wick=2.0,   # upper wick >= 2x body and lower wick small → INV_HAMMER
    small_wick=0.2         # “small” wick = ≤ 20% of total range
):
   
    o, h, l, c = df['ha_open'], df['ha_high'], df['ha_low'], df['ha_close']

    rng   = (h - l).replace(0, np.nan)
    body  = (c - o).abs()
    up_w  = h - np.maximum(c, o)
    dn_w  = np.minimum(c, o) - l

    # Primary shape tags
    is_green = c >= o
    is_red   = ~is_green

    # Ratios
    body_r = (body / rng).clip(0, 1)
    up_r   = (up_w / rng).fillna(0)
    dn_r   = (dn_w / rng).fillna(0)

    # Core types
    is_doji     = (body_r <= doji_ratio)
    is_spin     = (~is_doji) & (body_r <= spin_ratio)
    is_strong   = (body_r >= strong_body)

    # Wick-based
    is_hammer   = (dn_w >= hammer_wick*body) & (up_r <= small_wick)
    is_inv_ham  = (up_w >= inv_hammer_wick*body) & (dn_r <= small_wick)

    # Relationship vs previous bar (HA)
    prev_h = h.shift(1); prev_l = l.shift(1)
    prev_o = o.shift(1); prev_c = c.shift(1)
    prev_hi_body = np.maximum(prev_o, prev_c)
    prev_lo_body = np.minimum(prev_o, prev_c)

    # Relaxed engulf on HA (engulf body edges)
    bull_engulf = (is_green & (prev_c < prev_o) &
                   (c >= prev_hi_body) & (o <= prev_lo_body))
    bear_engulf = (is_red   & (prev_c > prev_o) &
                   (c <= prev_lo_body) & (o >= prev_hi_body))

    inside_bar  = (h <= prev_h) & (l >= prev_l)
    outside_bar = (h >= prev_h) & (l <= prev_l)

    # Final label precedence (top-down priority)
    label = np.where(bull_engulf, 'BULL_ENGULF',
             np.where(bear_engulf, 'BEAR_ENGULF',
             np.where(is_doji,      'DOJI',
             np.where(is_hammer,    'HAMMER',
             np.where(is_inv_ham,   'INVERTED_HAMMER',
             np.where(outside_bar,  'OUTSIDE_BAR',
             np.where(inside_bar,   'INSIDE_BAR',
             np.where(is_green & is_strong, 'STRONG_BULL',
             np.where(is_red   & is_strong, 'STRONG_BEAR',
             np.where(is_green,             'BULL', 'BEAR'))))))))))

    df['candle_pattern_signal'] = label
    return df

def label_candle_types_regular(
    df,
    open_col='open',
    high_col='high',
    low_col='low',
    close_col='close',
    wick_body_ratio=2.0,     # wick must be >= 2x body
    wick_range_ratio=0.35    # wick must be >= 35% of full range
):
    o = df[open_col].astype(float).values
    h = df[high_col].astype(float).values
    l = df[low_col].astype(float).values
    c = df[close_col].astype(float).values

    # --- TA-Lib pattern detectors (nonzero => pattern) ---
    doji        = talib.CDLDOJI(o, h, l, c)
    hammer      = talib.CDLHAMMER(o, h, l, c)
    inv_hammer  = talib.CDLINVERTEDHAMMER(o, h, l, c)
    engul       = talib.CDLENGULFING(o, h, l, c)
    spinning    = talib.CDLSPINNINGTOP(o, h, l, c)
    marubozu    = talib.CDLMARUBOZU(o, h, l, c)

    # --- Manual relationship patterns not directly in talib ---
    prev_h = df[high_col].shift(1)
    prev_l = df[low_col].shift(1)

    inside_bar  = (df[high_col] <= prev_h) & (df[low_col] >= prev_l)
    outside_bar = (df[high_col] >= prev_h) & (df[low_col] <= prev_l)

    is_green = df[close_col] >= df[open_col]
    is_red   = ~is_green

    # --- Build boolean masks ---
    bull_engulf = engul > 0
    bear_engulf = engul < 0

    is_doji    = doji != 0
    is_hammer  = hammer > 0
    is_inv_ham = inv_hammer > 0
    is_spin    = spinning != 0

    strong_bull = marubozu > 0
    strong_bear = marubozu < 0

    # ======================================================
    # ✅ Long wick detection (NEW)
    # ======================================================
    o_s = df[open_col].astype(float)
    h_s = df[high_col].astype(float)
    l_s = df[low_col].astype(float)
    c_s = df[close_col].astype(float)

    body = (c_s - o_s).abs()
    rng  = (h_s - l_s)

    # avoid division issues on tiny candles
    body_safe = body.clip(lower=1e-9)
    rng_safe  = rng.clip(lower=1e-9)

    lower_wick = np.minimum(o_s, c_s) - l_s
    upper_wick = h_s - np.maximum(o_s, c_s)

    long_lower_wick = (lower_wick >= wick_body_ratio * body_safe) & (lower_wick >= wick_range_ratio * rng_safe)
    long_upper_wick = (upper_wick >= wick_body_ratio * body_safe) & (upper_wick >= wick_range_ratio * rng_safe)

    # optional: avoid classifying doji-range noise as long-wick
    # long_lower_wick &= ~is_doji
    # long_upper_wick &= ~is_doji

    df["pa_long_lower_wick"] = long_lower_wick
    df["pa_long_upper_wick"] = long_upper_wick

    # --- Final label precedence ---
    # Put long-wick labels BEFORE generic BULL/BEAR so you can filter them
    label = np.where(bull_engulf, 'BULL_ENGULF',
             np.where(bear_engulf, 'BEAR_ENGULF',
             np.where(is_doji,      'DOJI',
             np.where(is_hammer,    'HAMMER',
             np.where(is_inv_ham,   'INVERTED_HAMMER',
             np.where(long_lower_wick, 'LONG_LOWER_WICK',
             np.where(long_upper_wick, 'LONG_UPPER_WICK',
             np.where(outside_bar,  'OUTSIDE_BAR',
             np.where(inside_bar,   'INSIDE_BAR',
             np.where(strong_bull,  'STRONG_BULL',
             np.where(strong_bear,  'STRONG_BEAR',
             np.where(is_spin,      'SPIN_TOP',
             np.where(is_green,     'BULL', 'BEAR')
             ))))))))))))

    df['candle_pattern_signal'] = label

    # Helper flags for price-action logic
    df['pa_strong_bullish'] = df['candle_pattern_signal'].isin([
        'BULL_ENGULF',
        'HAMMER',
        'INVERTED_HAMMER',
        'STRONG_BULL',
        'LONG_LOWER_WICK',    # ✅ add
    ])

    df['pa_strong_bearish'] = df['candle_pattern_signal'].isin([
        'BEAR_ENGULF',
        'STRONG_BEAR',
        'LONG_UPPER_WICK',    # ✅ add
    ])

    return df

def andean_oscillator(df: pd.DataFrame, length: int = 20, signal_length: int = 9) -> pd.DataFrame:
    """
    Andean Oscillator (Pine-style envelopes) with custom state machine:

    Lines:
      - bull  = green
      - bear  = red
      - signal = yellow (EMA of max(bull, bear))

    States:
      - flat:          yellow > green AND yellow > red
      - bull_started:  green crosses above red, then later green crosses above yellow
      - bear_started:  red crosses above green, then later red crosses above yellow
      - bull_trending: yellow was above green, then green crosses above yellow (and green > red)
      - bear_trending: yellow was above red, then red crosses above yellow (and red > green)

    Expects columns: 'open', 'close'
    Returns df with columns: bull, bear, andean_signal, andean_state
    """
    try:
        if df is None or df.empty:
            return df.assign(
                bull=pd.Series(dtype=float),
                bear=pd.Series(dtype=float),
                andean_signal=pd.Series(dtype=float),
                andean_state=pd.Series(dtype=object),
            )

        o = df["open"].to_numpy(dtype=np.float64)
        c = df["close"].to_numpy(dtype=np.float64)
        n = len(c)

        alpha = 2.0 / (length + 1.0)

        up1 = np.empty(n, dtype=np.float64)
        up2 = np.empty(n, dtype=np.float64)
        dn1 = np.empty(n, dtype=np.float64)
        dn2 = np.empty(n, dtype=np.float64)

        # Pine-style seeding
        up1[0] = c[0]
        up2[0] = c[0] * c[0]
        dn1[0] = c[0]
        dn2[0] = c[0] * c[0]

        for i in range(1, n):
            up1_i = up1[i - 1] - (up1[i - 1] - c[i]) * alpha
            up2_i = up2[i - 1] - (up2[i - 1] - c[i] * c[i]) * alpha
            dn1_i = dn1[i - 1] + (c[i] - dn1[i - 1]) * alpha
            dn2_i = dn2[i - 1] + (c[i] * c[i] - dn2[i - 1]) * alpha

            # clamp to current bar O/C (Pine-style max/min with 3 args)
            up1[i] = max(c[i], o[i], up1_i)
            up2[i] = max(c[i] * c[i], o[i] * o[i], up2_i)
            dn1[i] = min(c[i], o[i], dn1_i)
            dn2[i] = min(c[i] * c[i], o[i] * o[i], dn2_i)

        bull = np.sqrt(np.maximum(dn2 - dn1 * dn1, 0.0))  # green
        bear = np.sqrt(np.maximum(up2 - up1 * up1, 0.0))  # red
        base = np.maximum(bull, bear).astype(np.float64)

        # yellow line (signal)
        signal = talib.EMA(base, timeperiod=signal_length)

        # ---- Custom state machine ----
        state = np.empty(n, dtype=object)
        state[0] = "flat"

        bull_pending = False  # green crossed above red, waiting to cross above yellow
        bear_pending = False  # red crossed above green, waiting to cross above yellow

        for i in range(1, n):
            g, r, y = bull[i], bear[i], signal[i]
            pg, pr, py = bull[i - 1], bear[i - 1], signal[i - 1]

            # Handle EMA warmup NaNs safely
            if np.isnan(y) or np.isnan(py):
                state[i] = state[i - 1] if state[i - 1] else "flat"
                continue

            # Cross helpers
            green_cross_red = (g > r) and (pg <= pr)        # green crosses above red
            red_cross_green = (r > g) and (pr <= pg)        # red crosses above green
            green_cross_yellow = (g > y) and (pg <= py)     # green crosses above yellow
            red_cross_yellow = (r > y) and (pr <= py)       # red crosses above yellow

            # 1) flat definition
            if (y > g) and (y > r):
                state[i] = "flat"
                bull_pending = False
                bear_pending = False
                continue

            # 2) start pending sequences
            if green_cross_red:
                bull_pending = True
                bear_pending = False
            elif red_cross_green:
                bear_pending = True
                bull_pending = False

            # 3) started states (2-step)
            if bull_pending and green_cross_yellow:
                state[i] = "bull_started"
                bull_pending = False
                continue

            if bear_pending and red_cross_yellow:
                state[i] = "bear_started"
                bear_pending = False
                continue

            # 4) trending states (yellow above, then line crosses above yellow)
            # NOTE: crossover already implies prior (py >= pg) so this matches your "yellow above then cross" idea
            if green_cross_yellow and (g > r):
                state[i] = "bull_trending"
                continue

            if red_cross_yellow and (r > g):
                state[i] = "bear_trending"
                continue

            # 5) otherwise keep last state (reduces flicker)
            state[i] = state[i - 1]

        return df.assign(
                    bull=bull,
                    bear=bear,
                    andean_signal=signal,
                    andean_state=state,
                    andean_oscillator=state   # ✅ backward compatible with your old code
                )

    except Exception as e:
        print(f"Error in andean_oscillator: {e}")
        # If you have these in your project, keep them; otherwise remove.
        try:
            log_error(e, "andean_oscillator", "system", machine_id=MAIN_SIGNAL_DETECTOR_ID)
        except Exception:
            pass
        return df



def cci_minimal(
    df: pd.DataFrame,
    cci_len: int = 9,
    smoothing_len: int = 2,       # yellow = SMA(CCI,20) like TV
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    suffix: str = ""
) -> pd.DataFrame:
    """
    Returns index-aligned columns (NaN-safe):
      - cci_entry_state{suffix}: 'BULL' | 'BEAR' (ffilled after first valid)
      - cci_exit_cross{suffix} : 'BUY' | 'SELL' | NaN (event only, no ffill)
      - cci_sma{suffix}        : 'INCREASING' | 'DECREASING' (ffilled after first valid)

    Notes:
    - Uses REGULAR OHLC (must match your chart).
    - Labels are only computed where both CCI and yellow are finite; else left NaN then ffilled.
    """

    if df is None or df.empty:
        return pd.DataFrame({
            f'cci_entry_state{suffix}': pd.Series(dtype=object, index=df.index if df is not None else None),
            f'cci_exit_cross{suffix}':  pd.Series(dtype=object, index=df.index if df is not None else None),
            f'cci_sma{suffix}':         pd.Series(dtype=object, index=df.index if df is not None else None),
        })

    if not df.index.is_monotonic_increasing:
        df = df.sort_index()

    h = pd.to_numeric(df[high_col], errors="coerce").to_numpy()
    l = pd.to_numeric(df[low_col],  errors="coerce").to_numpy()
    c = pd.to_numeric(df[close_col], errors="coerce").to_numpy()

    cci_vals = talib.CCI(h, l, c, timeperiod=cci_len)
    yellow_vals = talib.SMA(cci_vals, timeperiod=smoothing_len)

    cci = pd.Series(cci_vals, index=df.index)
    yellow = pd.Series(yellow_vals, index=df.index)

    



    finite_now = cci.notna() & yellow.notna()

    # 1) Entry state (only where finite, then ffill after first valid)
    entry = pd.Series(np.where(cci > yellow, 'BULL', 'BEAR'), index=df.index)
    entry = entry.where(finite_now)  # NaN where not computable
    entry = entry.ffill()            # carry forward once we have a first valid label

    # 2) Cross signals vs SAME yellow (event-only; do not ffill)
    prev_cci   = cci.shift(1)
    prev_yellow= yellow.shift(1)
    finite_prev= prev_cci.notna() & prev_yellow.notna()




    cross_up   = finite_now & finite_prev & (cci > yellow) & (prev_cci <= prev_yellow)
    cross_down = finite_now & finite_prev & (cci < yellow) & (prev_cci >= prev_yellow)

    cross = pd.Series(np.nan, index=df.index, dtype=object)
    cross[cross_up]   = 'BUY'
    cross[cross_down] = 'SELL'

    # 3) Gap trend (|CCI - yellow| vs previous; only where both current & prev finite; then ffill label)
    gap = (cci - yellow).abs()
    cmp_mask = finite_now & gap.shift(1).notna()
    inc = pd.Series(np.where(gap > gap.shift(1), 'INCREASING', 'DECREASING'), index=df.index)
    inc = inc.where(cmp_mask)   # NaN where we cannot compare
    inc = inc.ffill()           # carry forward last known label

    out = pd.DataFrame({
        f'cci_entry_state{suffix}': entry,
        f'cci_exit_cross{suffix}':  cross,
        f'cci_sma{suffix}':         inc,
        f'cci_value{suffix}':         cci,
        f'cci_yellow_value{suffix}':         yellow,
    }, index=df.index)

    # # Tiny summary so you know what's happening
    # first_valid_cci   = cci.first_valid_index()
    # first_valid_yellow= yellow.first_valid_index()
    # print(f"[CCI debug] rows={len(df)} | CCI first_valid={first_valid_cci} | YELLOW first_valid={first_valid_yellow} "
    #       f"| entry NaNs={int(out[f'cci_entry_state{suffix}'].isna().sum())} "
    #       f"| cross events last 10:\n{out[f'cci_exit_cross{suffix}'].dropna().tail(10)}")

    return out


def _ma_talib(mode: str, src: np.ndarray, length: int) -> np.ndarray:
    mode = (mode or "ema").lower()
    if length <= 1:
        return src.astype(float)
    if mode == "ema":
        return talib.EMA(src, timeperiod=length)
    if mode == "sma":
        return talib.SMA(src, timeperiod=length)
    if mode == "wma":
        return talib.WMA(src, timeperiod=length)
    if mode == "tema":
        return talib.TEMA(src, timeperiod=length)
    # Keep it strictly TA-Lib based as requested
    raise ValueError("Unsupported MA mode for TA-Lib. Use one of: 'ema','sma','wma','tema'.")

def tdfi_assign_state_talib(
    df: pd.DataFrame,
    price_col: str = "close",
    lookback: int = 9,
    mmaLength: int = 9,
    mmaMode: str = "ema",
    smmaLength: int = 9,
    smmaMode: str = "ema",
    nLength: int = 3,
    filterHigh: float = 0.05,
    filterLow: float = -0.05,
) -> pd.DataFrame:
    """
    Adds df['tdfi_state'] based on TDFI signal:
      signal > filterHigh -> 'BULL'
      signal < filterLow  -> 'BEAR'
      else                -> 'FLAT'
    Matches the Pine logic using TA-Lib for MAs.
    """
    if df is None or df.empty:
        return df.assign(tdfi_state=pd.Series(dtype=object))

    # Pine multiplies price by 1000 inside MMA
    price = df[price_col].to_numpy(dtype=float) * 1000.0

    # MMA and SMMA per selected modes (TA-Lib only)
    mma  = _ma_talib(mmaMode,  price, mmaLength)
    smma = _ma_talib(smmaMode, mma,   smmaLength)

    # Impetus terms (first diff)
    impetmma  = np.r_[np.nan, np.diff(mma)]
    impetsmma = np.r_[np.nan, np.diff(smma)]

    divma = np.abs(mma - smma)
    averimpet = (impetmma + impetsmma) / 2.0

    # tdf = (|mma-smma|^1) * (averimpet ^ nLength)  (nLength=3 keeps sign naturally)
    tdf = (divma ** 1.0) * np.power(averimpet, nLength)

    # Normalize by highest(abs(tdf), lookback * nLength)
    win = max(1, lookback * nLength)
    max_abs = pd.Series(np.abs(tdf)).rolling(win).max().to_numpy()
    signal = np.divide(tdf, max_abs, out=np.zeros_like(tdf), where=max_abs > 0)

    # Map to states (gray/green/red -> FLAT/BULL/BEAR)
    tdfi_state = np.where(signal > filterHigh, 'BULL',
                   np.where(signal < filterLow, 'BEAR', 'FLAT'))

    return df.assign(tdfi_state=tdfi_state)

@performance_monitor("SIGNAL_PROCESSING", "CalculateSignals", machine_id=MAIN_SIGNAL_DETECTOR_ID)
def CalculateSignals(symbol, interval, candle='regular'):
    try:
        df_trading = fetch_data_safe(symbol, interval, 500)
        if df_trading is None or 'time' not in df_trading.columns:
            log_error("df_trading is None or missing 'time' column", "CalculateSignals", symbol)
            return None
        
        # Single optimized function call with candle parameter
        df_trading = calculate_all_indicators_optimized(df_trading, candle)

        
        
        return df_trading
        
    except Exception as e:
        log_error(e, 'CalculateSignals Error', symbol)
        return None


def CalculateSignals_Direct_Api(symbol, interval, candle='regular'):
    try:
        df_trading = fetch_ohlcv(symbol, interval, 300)
        if df_trading is None or 'time' not in df_trading.columns:
            log_error("df_trading is None or missing 'time' column", "CalculateSignals", symbol)
            return None
        
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
        
        # Single optimized function call with candle parameter
        # df_trading = calculate_all_indicators_optimized(df_trading, candle)
        
        return df_trading
        
    except Exception as e:
        log_error(e, "CalculateSignalsForConfirmation", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None


def placeOrder(symbol, interval, action, signalFrom, df,signal_data,min_profit,invest,candle_type):
    try:
        start_time = time.time()
        print(f"📊 Placing {action} order for {symbol} on {interval} timeframe")
        print(f"📊 Signal from: {signalFrom}")
        print(f"📊 Candle type: {candle_type}")
      
        

        stopPrice = find_last_high(df, action,candle_type)
        if action == 'BUY':
            stopPrice = df['swing_low_zone'].iloc[-1]
        else:
            stopPrice = df['swing_high_zone'].iloc[-1]

        
            
        last3Swings = get3Swings(df,action)
        candle_time = df.index[-1]

        # if signalFrom == 'Spike':
        #     stopPrice = signal_data['stopPrice']

        
        u_id, error = olab_AssignTradeToMachineLAB(df, symbol, interval, stopPrice, action, signalFrom,last3Swings,min_profit,invest,candle_type)
        if u_id is None:
            log_error(Exception(f"Not insert in database: {error}"), 'placeOrder Function', symbol)
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
        asyncio.run(send_message_to_users(f"{action} => Order success from place order -- {u_id}"))
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
    df = fetch_data_safe(symbol, interval, 500)
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
            stop_price = last_red_low - (last_red_low * 0.005)  # subtract small buffer
            return stop_price

        elif orderType == 'SELL':
            # Find last green candle: close > open
            last_green = data[data[close_col] > data[open_col]].iloc[-1]
            last_green_high = last_green[high_col]
            stop_price = last_green_high + (last_green_high * 0.005)  # add small buffer
            return stop_price

        else:
            return -1

    except Exception as e:
        log_error(e, "find_last_stop_price", "Stop Price Issue")
        return -1

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

        if olab_check_running_trade_exists(symbol, timeframe, strategy, 'henkin'):
            return True

        return False

    except Exception as e:
        print(f"❌ Error checking candle availability for {symbol} on {timeframe}: {e}")
        return False
    
def follow_overall_ema_trend(pair_info):

    try:
        # Add null checks for all required fields
        if not pair_info or not isinstance(pair_info, dict):
            print(f"❌ Invalid pair_info provided to follow_overall_ema_trend")
            return [False, None], None
        
        pair = pair_info.get('pair')
        overall_ema_trend_1m = pair_info.get('overall_ema_trend_1m')
        overall_ema_trend_5m = pair_info.get('overall_ema_trend_5m')
        overall_ema_trend_15m = pair_info.get('overall_ema_trend_15m')
        overall_ema_trend_percentage_1m = pair_info.get('overall_ema_trend_percentage_1m')
        overall_ema_trend_percentage_5m = pair_info.get('overall_ema_trend_percentage_5m')
        overall_ema_trend_percentage_15m = pair_info.get('overall_ema_trend_percentage_15m')
        print(f"Checking overall EMA trend for {pair}: 1m={overall_ema_trend_1m} ({overall_ema_trend_percentage_1m}%), 5m={overall_ema_trend_5m} ({overall_ema_trend_percentage_5m}%), 15m={overall_ema_trend_15m} ({overall_ema_trend_percentage_15m}%)")


        ### if from the supertrend the flag for both side is true then we have to trade in both sell and buy 30 count each

            # Check if essential fields are missingCNT
        count = 30
        bullish_conditions = [
            overall_ema_trend_1m == 'BULLISH' and overall_ema_trend_percentage_1m > 90,
            overall_ema_trend_5m == 'BULLISH' and overall_ema_trend_percentage_5m > 90,
            overall_ema_trend_15m == 'BULLISH' and overall_ema_trend_percentage_15m > 90
        ]
        bearish_conditions = [
            overall_ema_trend_1m == 'BEARISH' and overall_ema_trend_percentage_1m > 90,
            overall_ema_trend_5m == 'BEARISH' and overall_ema_trend_percentage_5m > 90,
            overall_ema_trend_15m == 'BEARISH' and overall_ema_trend_percentage_15m > 90
        ]

        print(f"Bullish conditions met: {sum(bullish_conditions)}, Bearish conditions met: {sum(bearish_conditions)} for {pair}"    )

        if sum(bullish_conditions) >= 2:
            total_running_count = int(olab_count_running_trades('BUY') or 0)
            # total_running_negative_sum = int(count_running_trades_negative('BUY') or 0)
            total_running_negative_sum =0

            print(f"{count}Total running BUY trades: {total_running_count}, Negative sum: {total_running_negative_sum}")

            if total_running_negative_sum < 0:
                count_need_to_add = abs(int(round(total_running_negative_sum / 5)))
                count =count + count_need_to_add
                print(f"Adjusted count after negative sum: {count}- Need to add: {count_need_to_add}")

            if total_running_count < count:  # Limit to 2 concurrent trades  
                return process_action_for_overall_ema_trend(pair,'BUY'),'BUY'
                    

        elif sum(bearish_conditions) >= 2:
            total_running_count = int(olab_count_running_trades('SELL') or 0)
            # total_running_negative_sum = int(count_running_trades_negative('SELL') or 0)
            total_running_negative_sum =0

            if total_running_negative_sum < 0:
                count_need_to_add = abs(int(round(total_running_negative_sum / 5)))
                count =count + count_need_to_add
                print(f"Adjusted count after negative sum: {count}- Need to add: {count_need_to_add}")

            if total_running_count < count:  # Limit to 2 concurrent trades
                return process_action_for_overall_ema_trend(pair,'SELL'),'SELL'

        return [False, None], None
    except Exception as e:
        log_error(e, "follow_overall_ema_trend", pair_info.get('pair', 'Unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return [False, None], None

def process_action_for_overall_ema_trend(pair,action):
    try:
        df = CalculateSignals(pair, '15m','heiken')
        if df is None or df.empty:
            return False
        
        candle_color = df['ha_color'].iloc[-1]
        last_close_price = df['ha_close'].iloc[-1]
        last_ema_9 = df['ema_9'].iloc[-1]
        print(f"Overall EMA trend action: {action}, Candle color: {candle_color} for {pair}")
        if action == 'BUY' and candle_color == 'GREEN' and (last_close_price > last_ema_9):
            return True,df
        elif action == 'SELL' and candle_color == 'RED' and (last_close_price < last_ema_9):
            return True,df
        else:
            return False,None

    except Exception as e:
        log_error(e, "process_action_for_overall_ema_trend", pair.get('pair', 'Unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return False,None

# def tdfi_breakout(pair_info, check_exists: bool = False):
#     """
#     Returns one of:
#         (df, 'BUY'|'SELL', signal_data, 'regular', 'IMACD', '15m')  OR  (None, None, None, None, None, None)
#     Logic: BUY when TDFI flips FLAT -> BULL on the last closed bar; SELL when FLAT -> BEAR.
#     Timeframe: 15m
#     """
#     # ------------------ Imports (kept local to avoid polluting module namespace) ------------------
#     import time
#     from datetime import datetime, timezone
#     import pandas as pd

#     # ------------------ Constants ------------------
#     TF = '15m'
#     STF = '5m'
#     SIGNAL_SRC = 'tdfi_breakout'
#     SIGNAL_FAMILY = 'IMACD'
#     RETURN_NONE6 = (None, None, None, None, None, None)

#     # ------------------ Basic input validation ------------------
#     if not pair_info or not isinstance(pair_info, dict):
#         print("❌ Invalid pair_info provided to tdfi_breakout")
#         return RETURN_NONE6

#     symbol = pair_info.get('pair')
#     if not symbol:
#         print("❌ Missing symbol in pair_info for tdfi_breakout")
#         return RETURN_NONE6

#     # ------------------ Helper: safe UTC timestamp ------------------
#     def to_utc_ts(x):
#         if x is None or (isinstance(x, float) and pd.isna(x)):
#             return datetime.now(timezone.utc)
#         ts = pd.to_datetime(x, utc=True, errors='coerce')
#         return ts.to_pydatetime() if ts is not None else datetime.now(timezone.utc)

#     try:
      
#         start_time = time.time()

#         df = CalculateSignals(symbol, TF,'heiken')
#         if df is None or getattr(df, "empty", True):
#             print(f"❌ No data for {symbol} on {TF} timeframe.")
#             return RETURN_NONE6
        
#         df_stf = CalculateSignals(symbol, STF,'heiken')
#         if df_stf is None or getattr(df_stf, "empty", True):
#             print(f"❌ No data for {symbol} on {STF} timeframe.")
#             return RETURN_NONE6
        
#         df_htf = CalculateSignals(symbol, '1h','heiken')

#         if df_htf is  None or getattr(df_htf, "empty", True):
#             print(f"❌ No data for {symbol} on {STF} timeframe.")
#             return RETURN_NONE6
        
        
#         ## Checking FLat market
#         df_4h = CalculateSignals(symbol, '4h','heiken')
#         if df is None or getattr(df, "empty", True):
#             print(f"❌ No data for {symbol} on {TF} timeframe.")
#             return RETURN_NONE6
        
#         a= get_low_swings_zones(df_4h)
#         b = get_high_swings_zones(df_4h)

#         # print(f'{symbol}lowwwwwwwwwwwwwwwwwwwwwwwwwww-- {a}')
#         # print(f'{symbol}highggggggggggggggggggggggggggg {b}')
        
#         tdfi_4h_2_ema = df_4h['tdfi_state_2_ema'].iloc[-1]




#         previous_row = df.iloc[-1]
#         prior_row    = df.iloc[-2]

#         previous_row_stf = df_stf.iloc[-1]

#         previous_row_htf = df_htf.iloc[-1]

#         # Safe timestamp extraction
#         current_candle_time = to_utc_ts(previous_row.get('time', None))

#         # Idempotency: if we already processed this closed candle, exit quietly
#         record_exists = olab_check_signal_processing_log_exists(symbol, TF, 'heiken', current_candle_time)
#         if record_exists:
#             return RETURN_NONE6

#         # Pull states safely (default to None; a missing key won't crash)
#         prev_state = previous_row.get('tdfi_state', None)
#         prior_state = prior_row.get('tdfi_state', None)

#         prev_state_2_ema = prior_row.get('tdfi_state_2_ema', None)
#         prior_state_2_ema = prior_row.get('tdfi_state_2_ema', None)

#         prev_state_stf = previous_row_stf.get('tdfi_state', None)
#         prev_state_2_ema_stf = previous_row_stf.get('tdfi_state_2_ema', None)

#         previous_candle_color = previous_row.get('ha_color', None) 

#         prev_andean_oscillator = previous_row.get('andean_oscillator', None)
#         prior_andean_oscillator = prior_row.get('andean_oscillator', None)

#         prev_cci_sma_9 = previous_row.get('cci_sma_9', None)
#         prev_cci_sma_100 = previous_row.get('cci_sma_100', None)

#         prev_cci_entry_state = previous_row.get('cci_entry_state_9', None)

#         prev_RSI_9 = previous_row.get('RSI_9', None)

#         prev_cci_exit_cross_9 = previous_row.get('cci_exit_cross_9', None)

#         prev_macd_color = previous_row.get('macd_color_signal', None)
#         prev_lower_macd_color_signal = previous_row.get('lower_macd_color_signal', None)

#         prev_lower_htf_macd_color_signal = previous_row_htf.get('lower_macd_color_signal', None)



#         prev_macd_up =  previous_row.get('two_pole_MACD_Cross_Up', None)
#         prev_macd_down =  previous_row.get('two_pole_MACD_Cross_Down', None)


#         prev_1_macd_5_8_9 =  previous_row.get('5_8_9_macd_pos', None)

#         prev_1_macd_13_21_9 =  previous_row.get('13_21_9_macd_pos', None)

#         prev_1_macd_34_144_9 =  previous_row.get('34_144_9_macd_pos', None)

#         prev_1_macd_200 =  previous_row.get('200_macd_pos', None)

#         prev_macd_200_up =  previous_row.get('200_macd_Cross_Up', None)
#         prev_macd_200_down =  previous_row.get('200_macd_Cross_Down', None)

#         prev_state_htf = previous_row_htf.get('tdfi_state', None)


#         prev_htf_macd_5_8_9 =  previous_row_htf.get('5_8_9_macd_pos', None)

#         prev_htf_macd_13_21_9 =  previous_row_htf.get('13_21_9_macd_pos', None)

#         prev_htf_macd_34_144_9 =  previous_row_htf.get('34_144_9_macd_pos', None)

#         prev_htf_macd_200 =  previous_row_htf.get('200_macd_pos', None)

#         prev_htf_lower_macd_color_signal =  previous_row_htf.get('lower_macd_color_signal', None)

#         prev_cci_sma_htf = previous_row_htf.get('cci_sma_9', None)




#         prev_stf_macd_5_8_9 =  previous_row_stf.get('5_8_9_macd_pos', None)

#         prev_stf_macd_13_21_9 =  previous_row_stf.get('13_21_9_macd_pos', None)

#         prev_stf_macd_200 =  previous_row_stf.get('200_macd_pos', None)

#         prev_bbw_percent = previous_row.get('BBW_PERCENTILE', None)
#         prev_bb_middle_band = previous_row.get('BOLL_middle_band', None)
#         prev_bb_flat = previous_row.get('bb_flat_market', None)  

#         prev_cci_entry_state_stf = previous_row_stf.get('cci_entry_state_9', None)
#         prev_cci_sma_stf = previous_row_stf.get('cci_sma_9', None)
#         prev_stf_cci_exit_cross_9 = previous_row_stf.get('cci_exit_cross_9', None)

#         prev_RSI_9_stf = previous_row_stf.get('RSI_9', None)

#         prev_bb_middle_band_stf = previous_row_stf.get('BOLL_middle_band', None)


#         # reference levels from 4H
#         last_high_4h = df_4h['ha_high'].iloc[-1]
#         last_low_4h  = df_4h['ha_low'].iloc[-1]

#         # take the last 3 bars from your lower TF dataframe
#         recent_highs = df_stf['ha_high'].tail(3)
#         recent_lows  = df_stf['ha_low'].tail(3)

#         last_high_stf = df_stf['ha_high'].iloc[-1]
#         last_low_stf = df_stf['ha_high'].iloc[-1]

#         previous_4H_ROW = df_4h.iloc[-1]
#         previous_5M_ROW = df_stf.iloc[-1]

#         # OPTION 1: vector compare + any()
#         sell_condition_range = (recent_highs >= last_high_4h).any()
#         buy_condition_range  = (recent_lows  <= last_low_4h).any()

#         signal_data = {
#             'pair_info': pair_info,
#             'last_rows': previous_row.to_dict(),
#             'prior_rows': prior_row.to_dict(),
#             'previous_1H_ROW' : previous_row_htf.to_dict(),
#             'previous_4H_ROW' : previous_4H_ROW.to_dict(),
#             'previous_5M_ROW' : previous_5M_ROW.to_dict(),
#         }


#         # Log that we evaluated this candle (CHECKING stage)
#         log_signal_processing(
#             candel_time=current_candle_time,
#             symbol=symbol,
#             interval=TF,
#             signal_type='CHECKING',
#             signal_source=SIGNAL_SRC,
#             signal_data=signal_data,
#             processing_time_ms=(time.time() - start_time) * 1000.0,
#             machine_id=MAIN_SIGNAL_DETECTOR_ID
#         )



#         # ------------------ Conditions (spelling fix + clarity) ------------------
#         buy_condition  = (
#                         #  ((prev_state == 'BULL' and prior_state == 'FLAT' ) ....
#                         #    or (prev_andean_oscillator == 'BULL' and prior_andean_oscillator == 'FLAT'))
#                         (prev_state_2_ema == 'BULL' and (prior_state_2_ema == 'FLAT' or prior_state_2_ema == 'BEAR'))
#                          and prev_macd_color == 'BUY' 
#                          and prev_lower_macd_color_signal == 'BUY'
#                         and prev_lower_htf_macd_color_signal == 'BUY'
#                         #  and prev_macd_200_up 
#                          and prev_htf_macd_13_21_9=='BUY'
#                          and  prev_cci_entry_state == 'BULL'
#                          and prev_RSI_9_stf < 70
#                          and prev_RSI_9 < 70
#                          and tdfi_4h_2_ema== 'BULL'
#                          and ((prev_cci_sma_9 == 'DECREASING' and prev_cci_entry_state == 'BEAR')
#                               or(prev_cci_sma_9 == 'INCREASING' and prev_cci_entry_state == 'BULL')
#                               or(prev_cci_exit_cross_9 == 'BUY'))
#                          and
#                          (
#                              (prev_cci_entry_state_stf == 'BULL' and prev_cci_sma_stf == 'INCREASING') or
#                              (prev_cci_entry_state_stf == 'BEAR' and prev_cci_sma_stf == 'DECREASING')
#                          )
#                         )
        
#         sell_condition = (
#                         # ((prev_state == 'BEAR' and prior_state == 'FLAT' ) 
#                         # or (prev_andean_oscillator == 'BEAR' and prior_andean_oscillator == 'FLAT'))
#                         (prev_state_2_ema == 'BEAR' and (prior_state_2_ema == 'FLAT' or prior_state_2_ema == 'BULL'))
#                         and prev_macd_color == 'SELL' 
#                         and prev_lower_macd_color_signal == 'SELL'
#                         and prev_lower_htf_macd_color_signal == 'SELL'
#                         # and prev_macd_200_down 
#                         and prev_htf_macd_13_21_9=='SELL'
#                         and  prev_cci_entry_state == 'BEAR'
#                         and prev_RSI_9_stf > 30
#                         and prev_RSI_9 > 30
#                         and tdfi_4h_2_ema== 'BEAR'
#                          and ((prev_cci_sma_9 == 'DECREASING' and prev_cci_entry_state == 'BULL')
#                               or(prev_cci_sma_9 == 'INCREASING' and prev_cci_entry_state == 'BEAR')
#                               or(prev_cci_exit_cross_9 == 'SELL'))
#                         and
#                         (
#                              (prev_cci_entry_state_stf == 'BEAR' and prev_cci_sma_stf == 'INCREASING') or
#                              (prev_cci_entry_state_stf == 'BULL' and prev_cci_sma_stf == 'DECREASING')
#                          )
#                         )


#         # buy_condition  = (
#         #                 prev_cci_exit_cross_9 == 'BUY'
#         #                 and prev_htf_macd_13_21_9=='BUY'
#         #                 and prev_1_macd_34_144_9 == 'BUY' 
#         #                 and prev_macd_color == 'BUY' 
#         #                 # and prev_htf_lower_macd_color_signal == 'BUY'                    
#         #                 and not prev_bb_flat and prev_RSI_9_stf < 70
#         #                 and prev_RSI_9 < 70 
#         #                 and tdfi_4h_2_ema!= 'FLAT'
                       
#         #                 #  and  prev_cci_entry_state == 'BULL'
#         #                 #  and
#         #                 #  (
#         #                 #      (prev_cci_entry_state_stf == 'BULL' and prev_cci_sma_stf == 'INCREASING') or
#         #                 #      (prev_cci_entry_state_stf == 'BEAR' and prev_cci_sma_stf == 'DECREASING')
#         #                 #  )
#         #                 )
        
#         # sell_condition = (prev_cci_exit_cross_9 == 'SELL'
#         #                 and prev_htf_macd_13_21_9=='SELL' 
#         #                 and prev_1_macd_34_144_9 == 'SELL' 
#         #                 and prev_macd_color == 'SELL'     
#         #                 # and prev_htf_lower_macd_color_signal == 'SELL'                    
#         #                 and not prev_bb_flat  and prev_RSI_9_stf > 30
#         #                 and prev_RSI_9 > 30
#         #                 and tdfi_4h_2_ema!= 'FLAT'
                       
#                         # and  prev_cci_entry_state == 'BEAR'
#                         # and
#                         # (
#                         #      (prev_cci_entry_state_stf == 'BEAR' and prev_cci_sma_stf == 'INCREASING') or
#                         #      (prev_cci_entry_state_stf == 'BULL' and prev_cci_sma_stf == 'DECREASING')
#                         #  )
#                         # )
        
#         print(f'{sell_condition}-sell-----------{buy_condition} buy')
        
#         bar_below_middle_band = previous_row['ha_low'] < prev_bb_middle_band and previous_row['ha_high'] < prev_bb_middle_band
#         bar_above_middle_band = previous_row['ha_high'] > prev_bb_middle_band and previous_row['ha_low'] > prev_bb_middle_band


#         bar_below_middle_band_stf = previous_row_stf['ha_low'] < prev_bb_middle_band_stf and previous_row_stf['ha_high'] < prev_bb_middle_band_stf
#         bar_above_middle_band_stf = previous_row_stf['ha_high'] > prev_bb_middle_band_stf and previous_row_stf['ha_low'] > prev_bb_middle_band_stf



        
#         # flat_buy_condition = (prev_macd_up and not buy_condition and prev_state == 'FLAT' and prev_state_htf == 'FLAT' and prev_bbw_percent > 0.8 and not prev_bb_flat and bar_below_middle_band 
#         #                       and prev_cci_exit_cross == 'BUY' and prev_cci_entry_state_stf == 'BULL')
        
#         # flat_sell_condition = (prev_macd_down and not sell_condition and prev_state == 'FLAT' and prev_state_htf == 'FLAT'  and  prev_bbw_percent > 0.8 and not prev_bb_flat and bar_above_middle_band 
#         #                        and prev_cci_exit_cross == 'SELL' and prev_cci_entry_state_stf == 'BEAR')

#         vol =  previous_row.get('Volume_Ratio', None)
#         price_direction =  previous_row.get('price_trend_direction', None)

#         flat_buy_condition = (
#                         (   tdfi_4h_2_ema== 'FLAT' and
#                             prev_cci_entry_state == 'BULL' 
#                             and (prev_state == 'BEAR' or prior_state == 'BEAR')
#                             and prev_bbw_percent > 0.8 and not prev_bb_flat and bar_below_middle_band
#                             and prev_lower_macd_color_signal == 'BUY' and   prev_RSI_9 < 30
#                             and vol > 1.2 and previous_candle_color == 'GREEN' 
#                         )
#                         # or
#                         # (
#                         #     prev_macd_up and not buy_condition
#                         #     and prior_state == 'BEAR' and prev_state == 'FLAT' and not  prev_bb_flat 
#                         #     and prev_cci_exit_cross == 'BUY'  and prev_macd_color == 'BUY'
#                         # )
#                     )
        
#         flat_sell_condition = (   tdfi_4h_2_ema== 'FLAT' and
#                             prev_cci_entry_state == 'BEAR' 
#                             and (prev_state == 'BULL' or prior_state == 'BULL')
#                             and prev_bbw_percent > 0.8 and not prev_bb_flat and bar_above_middle_band
#                             and prev_lower_macd_color_signal == 'BUY' and   prev_RSI_9 > 70
#                             and vol > 1.2 and previous_candle_color == 'RED' 
#                         )
        

#         breakout_buy_condition = (prev_bb_flat and vol > 2 
#                                   and price_direction == 'UPTREND'
#                                   and prev_1_macd_5_8_9 == 'BUY'
#                                   and prev_1_macd_13_21_9 == 'BUY'
#                                   and prev_1_macd_34_144_9 == 'BUY'
#                                   and previous_candle_color == 'GREEN' )
        
#         breakout_sell_condition =  (prev_bb_flat and vol > 2 
#                                   and price_direction == 'DOWNTREND'
#                                   and prev_1_macd_5_8_9 == 'SELL'
#                                   and prev_1_macd_13_21_9 == 'SELL'
#                                   and prev_1_macd_34_144_9 == 'SELL'
#                                   and previous_candle_color == 'RED')
#             # or
#             # (
#             #     prev_macd_down and not sell_condition
#             #     and prior_state == 'BULL' and prev_state == 'FLAT' and not prev_bb_flat 
#             #     and prev_cci_exit_cross == 'SELL' and prev_macd_color == 'SELL'
#             # )
       

#         # trend_buy_condition =  (
#         #                     prev_cci_entry_state == 'BULL' 
#         #                     and prior_state == 'BEAR' and prev_state == 'FLAT' and not  prev_bb_flat 
#         #                     and  prev_macd_200_up and prev_cci_entry_state_stf == 'BULL'
#         #                 )
#         # trend_sell_condition = (
#         #         prev_cci_entry_state == 'BEAR' 
#         #         and prior_state == 'BULL' and prev_state == 'FLAT' and not prev_bb_flat 
#         #         and prev_macd_200_down and prev_cci_entry_state_stf == 'BEAR'

#         #     )

#         trend_buy_condition =  (
#                             prev_stf_cci_exit_cross_9 == 'BUY'
#                             and prev_htf_macd_13_21_9=='BUY' 
#                             and prev_1_macd_34_144_9 == 'BUY'
#                             and prev_macd_color =='BUY'
#                             and prev_htf_lower_macd_color_signal == 'BUY'                    
#                             and prev_stf_macd_13_21_9 == 'BUY' and not prev_bb_flat
#                             and prev_RSI_9 < 70
#                             and prev_RSI_9_stf < 70
#                             and tdfi_4h_2_ema== 'BULL'
#                         )
#         trend_sell_condition = (
#                 prev_stf_cci_exit_cross_9 == 'SELL'
#                 and prev_htf_macd_13_21_9=='SELL' 
#                 and prev_1_macd_34_144_9 == 'SELL'
#                 and prev_macd_color =='SELL'
#                 and prev_htf_lower_macd_color_signal == 'SELL'                    
#                 and prev_stf_macd_13_21_9 == 'SELL' and not prev_bb_flat
#                 and prev_RSI_9 > 30
#                 and prev_RSI_9_stf > 30
#                 and tdfi_4h_2_ema== 'BEAR'

#             )
        
#           # reference levels from 4H
#         last_high_4h = df_4h['ha_high'].iloc[-1]
#         last_low_4h  = df_4h['ha_low'].iloc[-1]

#         median_4h = (last_high_4h + last_low_4h) / 2.0



#         recent_close_stf = df_stf['ha_close'].iloc[-1]

#         candle_color_stf = df_stf['ha_color'].iloc[-1]
#         price_direction_stf = df_stf['price_trend_direction'].iloc[-1]

#         bb_flat_stf = df_stf['bb_flat_market'].iloc[-1]

#         # OPTION 1: vector compare + any()
#         # sell_condition_range = (recent_highs >= last_high_4h).any()
#         # buy_condition_range  = (recent_lows  <= last_low_4h).any()

#         sell_condition_range = (recent_close_stf > median_4h and recent_close_stf < last_high_4h and not bb_flat_stf)
#         buy_condition_range  = (recent_close_stf < median_4h and recent_close_stf > last_low_4h and not bb_flat_stf)


        


         
#         range_buy_condition =  ( buy_condition_range
#                                 and prev_stf_cci_exit_cross_9 == 'BUY'
#                                 and candle_color_stf == 'GREEN'                                       
#                                 and tdfi_4h_2_ema== 'FLAT' 
#                                 and prev_state == 'FLAT' 
#                                 and prev_state_2_ema == 'FLAT' 
#                                 and prior_state == 'FLAT'
#                                 and ( prev_state_stf == 'FLAT' or prev_state_stf == 'BULL')
#                                 and (prev_state_2_ema_stf == 'FLAT' or prev_state_2_ema_stf == 'BULL')
#                                 and bar_below_middle_band_stf)
        
#         range_sell_condition = ( sell_condition_range
#                                 and prev_stf_cci_exit_cross_9 == 'SELL'
#                                 and candle_color_stf == 'RED'
#                                 and tdfi_4h_2_ema== 'FLAT'
#                                 and prev_state == 'FLAT' 
#                                 and prev_state_2_ema == 'FLAT' 
#                                 and ( prev_state_stf == 'FLAT' or prev_state_stf == 'BEAR')
#                                 and (prev_state_2_ema_stf == 'FLAT' or prev_state_2_ema_stf == 'BEAR')
#                                 and prior_state == 'FLAT'
#                                 and bar_above_middle_band_stf)

#         print(f"Buy Condition: {buy_condition}, Sell Condition: {sell_condition} for {symbol} on {TF}")

#         if  buy_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, SIGNAL_FAMILY)
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for {SIGNAL_FAMILY}.")
#                     return RETURN_NONE6

#             return df, 'BUY',  signal_data, 'heiken', SIGNAL_FAMILY, '1h'
#         if  sell_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, SIGNAL_FAMILY)
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for {SIGNAL_FAMILY}.")
#                     return RETURN_NONE6

#             return df, 'SELL', signal_data, 'heiken', SIGNAL_FAMILY, '1h'
        

#         if  trend_buy_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, 'CrossOver')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for CrossOver.")
#                     return RETURN_NONE6

#             return df, 'BUY',  signal_data, 'heiken', 'CrossOver', '15m'
        
#         if  trend_sell_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, 'CrossOver')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for CrossOver.")
#                     return RETURN_NONE6

#             return df, 'SELL', signal_data, 'heiken', 'CrossOver', '15m'        
#         if  flat_buy_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, 'ProGap')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for ProGap.")
#                     return RETURN_NONE6

#             return df, 'BUY',  signal_data, 'heiken', 'ProGap', '15m'
#         if  flat_sell_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, 'ProGap')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for ProGap.")
#                     return RETURN_NONE6

#             return df, 'SELL', signal_data, 'heiken', 'ProGap', '15m'
#         if  range_buy_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, '5m', 'Spike')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for Spike.")
#                     return RETURN_NONE6

#             return df, 'BUY',  signal_data, 'heiken', 'Spike', '5m'
#         if  range_sell_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, '5m', 'Spike')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for Spike.")
#                     return RETURN_NONE6

#             return df, 'SELL', signal_data, 'heiken', 'Spike', '5m'
#         if  breakout_buy_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, '15m', 'Kicker')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for Spike.")
#                     return RETURN_NONE6

#             return df, 'BUY',  signal_data, 'heiken', 'Kicker', '15m'
#         if  breakout_sell_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, '15m', 'Kicker')
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for Spike.")
#                     return RETURN_NONE6

#             return df, 'SELL', signal_data, 'heiken', 'Kicker', '15m'

#         # No signal this bar
#         return RETURN_NONE6

#     except Exception as e:
#         print(f"❌ Error processing {symbol} in {SIGNAL_SRC}: {e}")
#         # Keep your existing logger contract (includes machine_id)
#         log_error(e, SIGNAL_SRC, symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
#         return RETURN_NONE6


# def tdfi_breakout(pair_info, check_exists: bool = False):
#     """
#     Returns one of:
#         (df, 'BUY'|'SELL', signal_data, 'regular', 'IMACD', '15m')  OR  (None, None, None, None, None, None)
#     Logic: BUY when TDFI flips FLAT -> BULL on the last closed bar; SELL when FLAT -> BEAR.
#     Timeframe: 15m
#     """
#     # ------------------ Imports (kept local to avoid polluting module namespace) ------------------
#     import time
#     from datetime import datetime, timezone
#     import pandas as pd

#     # ------------------ Constants ------------------
#     TF = '15m'
#     TF_2H = '2h'
#     TF_4H = '4h'
#     SIGNAL_SRC = 'tdfi_breakout'
#     SIGNAL_FAMILY = 'IMACD'
#     RETURN_NONE6 = (None, None, None, None, None, None)

#     # ------------------ Basic input validation ------------------
#     if not pair_info or not isinstance(pair_info, dict):
#         print("❌ Invalid pair_info provided to tdfi_breakout")
#         return RETURN_NONE6

#     symbol = pair_info.get('pair')
#     if not symbol:
#         print("❌ Missing symbol in pair_info for tdfi_breakout")
#         return RETURN_NONE6

#     # ------------------ Helper: safe UTC timestamp ------------------
#     def to_utc_ts(x):
#         if x is None or (isinstance(x, float) and pd.isna(x)):
#             return datetime.now(timezone.utc)
#         ts = pd.to_datetime(x, utc=True, errors='coerce')
#         return ts.to_pydatetime() if ts is not None else datetime.now(timezone.utc)

#     try:
      
#         start_time = time.time()

#         df_15m = CalculateSignals(symbol, TF,'heiken')
#         if df_15m is None or getattr(df_15m, "empty", True):
#             print(f"❌ No data for {symbol} on {TF} timeframe.")
#             return RETURN_NONE6
        
      
        
#         df_2h = CalculateSignals(symbol, TF_2H,'heiken')

#         if df_2h is  None or getattr(df_2h, "empty", True):
#             print(f"❌ No data for {symbol} on {TF_2H} timeframe.")
#             return RETURN_NONE6
        
#         # df_4h = CalculateSignals(symbol, TF_4H,'heiken')

#         # if df_4h is  None or getattr(df_4h, "empty", True):
#         #     print(f"❌ No data for {symbol} on {TF_4H} timeframe.")
#         #     return RETURN_NONE6
        
        
      
#         # a= get_low_swings_zones(df_4h)
#         # b = get_high_swings_zones(df_4h)

#         # # print(f'{symbol}lowwwwwwwwwwwwwwwwwwwwwwwwwww-- {a}')
#         # # print(f'{symbol}highggggggggggggggggggggggggggg {b}')
        
#         # tdfi_4h_2_ema = df_4h['tdfi_state_2_ema'].iloc[-1]





#         previous_row_15m = df_15m.iloc[-1]

#         previous_row_2h = df_2h.iloc[-1]

#         prior_row_2h = df_2h.iloc[-2]


#         last_2h_tdfi = previous_row_2h['tdfi_state_2_ema']
#         last_2h_tdfi_3_ema = previous_row_2h['tdfi_state_3_ema']


#         prior_2h_tdfi = prior_row_2h['tdfi_state_2_ema']
#         prior_2h_tdfi_3_ema = prior_row_2h['tdfi_state_3_ema']

#         # previous_row_4h = df_4h.iloc[-1]
        
#         # last_tdfi_15m =  previous_row_15m['tdfi_state_2_ema']
#         # prior_tdfi_15m =  prior_row_15m['tdfi_state_2_ema']

#         # cci_value_9_15m =  previous_row_15m['cci_value_9']

#         # tdfi_state_2_ema_4h = previous_row_4h['tdfi_state_2_ema']
#         # tdfi_state_3_ema_4h = previous_row_4h['tdfi_state_3_ema']


#         # cci_entry_state_9_2h = previous_row_2h['cci_entry_state_9']
#         # cci_sma_9_2h = previous_row_2h['cci_sma_9']


#         # buy_condition   = ( cci_value_9_15m < 100 and
#         #         last_tdfi_15m == 'BULL' and (prior_tdfi_15m == 'FLAT' or prior_tdfi_15m == 'BEAR')
                
#         #         and tdfi_state_2_ema_4h == 'BULL' and tdfi_state_3_ema_4h == 'BULL' 
#         #                         and 
#         #         (
#         #         ( cci_entry_state_9_2h == 'BULL' and cci_sma_9_2h == 'INCREASING') 
#         #         or
#         #         ( cci_entry_state_9_2h == 'BEAR' and cci_sma_9_2h == 'DECREASING') 
#         #         ))
#         # sell_condition = ( cci_value_9_15m > -100 and
#         #         last_tdfi_15m == 'BEAR' and (prior_tdfi_15m == 'FLAT' or prior_tdfi_15m == 'BULL')
#         #         and tdfi_state_2_ema_4h == 'BEAR' and tdfi_state_3_ema_4h == 'BEAR' 
#         #                         and 
#         #         (
#         #         ( cci_entry_state_9_2h == 'BEAR' and cci_sma_9_2h == 'INCREASING') 
#         #         or
#         #         ( cci_entry_state_9_2h == 'BULL' and cci_sma_9_2h == 'DECREASING') 
#         #         ))
#         current_candle_time = to_utc_ts(previous_row_2h.get('time', None))
#         print(f'---------------------------{symbol}----------------------------------')
#         print(f'Candle Time = {current_candle_time}')
#         print(f'last tdfi = {last_2h_tdfi} | last 3 ema tdfi = {last_2h_tdfi_3_ema}')
#         print(f'prior tdfi = {prior_2h_tdfi} | prior ema tdfi = {prior_2h_tdfi_3_ema}')
#         print('======================================================================')





#         last_buy_signal =  ( last_2h_tdfi == 'BULL' and last_2h_tdfi_3_ema == 'BULL')
#         prior_buy_signal = (prior_2h_tdfi=='BULL' and prior_2h_tdfi_3_ema=='BULL')  

        

#         last_sell_signal =  ( last_2h_tdfi == 'BEAR' and last_2h_tdfi_3_ema == 'BEAR')
#         prior_sell_signal = (prior_2h_tdfi=='BEAR' and prior_2h_tdfi_3_ema=='BEAR')


#         buy_condition = last_buy_signal and not prior_buy_signal
#         sell_condition = last_sell_signal and not prior_sell_signal

#         buy_exit = not last_buy_signal and prior_buy_signal
#         sell_exit = not last_sell_signal and prior_sell_signal


#         # buy_condition = (
#         # ( last_2h_tdfi == 'BULL' and last_2h_tdfi_3_ema == 'BULL')
#         # and
#         # (prior_2h_tdfi!='BULL' and prior_2h_tdfi_3_ema!='BULL')
#         # )


#         # sell_condition = (
#         # ( last_2h_tdfi == 'BEAR' and last_2h_tdfi_3_ema == 'BEAR')
#         # and
#         # (prior_2h_tdfi!='BEAR' and prior_2h_tdfi_3_ema!='BEAR')
#         # )


#            # sell_signal = (
#             #     ( last_2h_tdfi == 'BEAR' and last_2h_tdfi_3_ema == 'BEAR')
#             #     and
#             #         (prior_2h_tdfi!='BEAR' and prior_2h_tdfi_3_ema!='BEAR')
#             #      )

     


#         # Safe timestamp extraction
#         current_candle_time = to_utc_ts(previous_row_15m.get('time', None))

#         # Idempotency: if we already processed this closed candle, exit quietly
#         record_exists = olab_check_signal_processing_log_exists(symbol, TF, 'heiken', current_candle_time)
#         if record_exists:
#             return RETURN_NONE6

#         # Pull states safely (default to None; a missing key won't crash)


        


#         signal_data = {
#             'pair_info': pair_info,
#             'previous_row_15m': previous_row_15m.to_dict(),
#             # 'prior_row_15m': prior_row_15m.to_dict(),
#             'previous_row_2h' : previous_row_2h.to_dict(),
#             'previous_row_2h' : prior_row_2h.to_dict(),
#             # 'previous_row_4h' : previous_row_4h.to_dict()
#         }


#         # Log that we evaluated this candle (CHECKING stage)
#         log_signal_processing(
#             candel_time=current_candle_time,
#             symbol=symbol,
#             interval=TF,
#             signal_type='CHECKING',
#             signal_source=SIGNAL_SRC,
#             signal_data=signal_data,
#             processing_time_ms=(time.time() - start_time) * 1000.0,
#             machine_id=MAIN_SIGNAL_DETECTOR_ID
#         )


#         if  buy_condition:
#               # If asked, skip symbols that already have an active record

#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, SIGNAL_FAMILY)
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for {SIGNAL_FAMILY}.")
#                     return RETURN_NONE6
                
#             # df_api = fetch_ohlcv( symbol, TF, limit=500)
#             # df_api = calculate_all_indicators_optimized(df_api, 'heiken')

#             # if df_api is None or getattr(df_api, "empty", True):
#             #     print(f"❌ No data from API for {symbol} on {TF} timeframe.")

#             # if(df_api['tdfi_state_2_ema'].iloc[-1] == 'BULL' 
#             #    and (df_api['tdfi_state_2_ema'].iloc[-2] == 'FLAT' or df_api['tdfi_state_2_ema'].iloc[-2] == 'BEAR')):
#             # if confirmWithAPI(symbol,  'BUY'):

#             #     return df_15m, 'BUY',  signal_data, 'heiken', SIGNAL_FAMILY, TF
            
#             # else:
#             #     message = f"rejected by api for symbol = {symbol}, action = 'BUY' , candle_time = {current_candle_time} "
#             #     log_to_file_reject_from_api(message,'api_reject')
#             #     return RETURN_NONE6

#             return df_2h, 'BUY',  signal_data, 'heiken', SIGNAL_FAMILY, '2h'
            

#         if  sell_condition:
#               # If asked, skip symbols that already have an active record
#             if check_exists:
#                 result = check_if_record_exists(symbol, TF, SIGNAL_FAMILY)
#                 if result:
#                     # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
#                     print(f"⏭️ Skipping {symbol} on {TF} — record already exists for {SIGNAL_FAMILY}.")
#                     return RETURN_NONE6
                
#                 # df_api = fetch_ohlcv( symbol, TF, limit=500)
#                 # df_api = calculate_all_indicators_optimized(df_api, 'heiken')
#                 # if df_api is None or getattr(df_api, "empty", True):
#                 #     print(f"❌ No data from API for {symbol} on {TF} timeframe.")   
#                 # if(df_api['tdfi_state_2_ema'].iloc[-1] == 'BEAR' 
#                 #    and (df_api['tdfi_state_2_ema'].iloc[-2] == 'FLAT' or df_api['tdfi_state_2_ema'].iloc[-2] == 'BULL')):

#             # if confirmWithAPI(symbol,  'SELL'):
                    
#             #         return df_15m, 'SELL', signal_data, 'heiken', SIGNAL_FAMILY, TF
            
#             # else:      
#             #     message = f"rejected by api for symbol = {symbol}, action = 'SELL' , candle_time = {current_candle_time} "
#             #     log_to_file_reject_from_api(message,'api_reject')                           
#             #     return RETURN_NONE6
#             return df_2h, 'SELL', signal_data, 'heiken', SIGNAL_FAMILY, '2h'

#         # No signal this bar
#         return RETURN_NONE6

#     except Exception as e:
#         print(f"❌ Error processing {symbol} in {SIGNAL_SRC}: {e}")
#         # Keep your existing logger contract (includes machine_id)
#         log_error(e, SIGNAL_SRC, symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
#         return RETURN_NONE6

def _normalize_timestamp(ts):
            """
            Convert a timestamp (possibly timezone-aware) to a naive pd.Timestamp.
            """
            if ts is None:
                return None
            try:
                if pd.isna(ts):
                    return None
            except TypeError:
                pass
            try:
                ts_obj = pd.Timestamp(ts)
            except (ValueError, TypeError):
                return None
            if ts_obj.tzinfo is not None:
                return ts_obj.tz_convert(None)
            return ts_obj

def tdfi_breakout(pair_info, check_exists: bool = False):
    """
    Returns one of:
        (df, 'BUY'|'SELL', signal_data, 'regular', 'IMACD', '15m')  OR  (None, None, None, None, None, None)
    Logic: BUY when TDFI flips FLAT -> BULL on the last closed bar; SELL when FLAT -> BEAR.
    Timeframe: 15m
    """
    # ------------------ Imports (kept local to avoid polluting module namespace) ------------------
    import time
    from datetime import datetime, timezone
    import pandas as pd

    # ------------------ Constants ------------------
    TF = '15m'
    TF_30M = '30m'
    TF_1H = '1h'
    TF_2H = '2h'
    TF_4H = '4h'
    invest = 500
    SIGNAL_SRC = 'tdfi_breakout'
    SIGNAL_FAMILY = 'IMACD'
    RETURN_NONE7 = (None, None, None, None, None, None,None)

    # ------------------ Basic input validation ------------------
    if not pair_info or not isinstance(pair_info, dict):
        print("❌ Invalid pair_info provided to tdfi_breakout")
        return RETURN_NONE7

    symbol = pair_info.get('pair')
    if not symbol:
        print("❌ Missing symbol in pair_info for tdfi_breakout")
        return RETURN_NONE7

    # ------------------ Helper: safe UTC timestamp ------------------
    def to_utc_ts(x):
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return datetime.now(timezone.utc)
        ts = pd.to_datetime(x, utc=True, errors='coerce')
        return ts.to_pydatetime() if ts is not None else datetime.now(timezone.utc)

    try:
      
        start_time = time.time()

        df_15m = CalculateSignals(symbol, TF,'regular')
        if df_15m is None or getattr(df_15m, "empty", True):
            print(f"❌ No data for {symbol} on {TF} timeframe.")
            return RETURN_NONE7
        
      


        df_4h = CalculateSignals(symbol, TF_4H,'regular')

        if df_4h is  None or getattr(df_4h, "empty", True):
            print(f"❌ No data for {symbol} on {TF_4H} timeframe.")
            return RETURN_NONE7
        
        # df_2h = CalculateSignals(symbol, TF_2H,'heiken')

        # if df_2h is  None or getattr(df_2h, "empty", True):
        #     print(f"❌ No data for {symbol} on {TF_2H} timeframe.")
        #     return RETURN_NONE7
        
        df_1h = CalculateSignals(symbol, TF_1H,'heiken')

        if df_1h is  None or getattr(df_1h, "empty", True):
            print(f"❌ No data for {symbol} on {TF_1H} timeframe.")
            return RETURN_NONE7
        
        # df_30m = CalculateSignals(symbol, TF_30M,'heiken')

        # if df_30m is  None or getattr(df_30m, "empty", True):
        #     print(f"❌ No data for {symbol} on {TF_30M} timeframe.")
        #     return RETURN_NONE7
        
        

        previous_row_15m = df_15m.iloc[-1]
        # previous_row_30m = df_30m.iloc[-1]
        previous_row_1h = df_1h.iloc[-1]
        # previous_row_2h = df_2h.iloc[-1]
        previous_row_4h = df_4h.iloc[-1]

        last_ha_close_4h = previous_row_4h['ha_close']
        last_ema_100_4h = previous_row_4h['ema_100']
        last_RSI_9_4h = previous_row_4h['RSI_9']


        last_ema_5_8_buy_signal_15m = previous_row_15m['ema_5_8_buy_signal']
        last_ema_5_8_sell_signal_15m = previous_row_15m['ema_5_8_sell_signal']

        last_ema_5_8_buy_rank_15m = previous_row_15m['ema_5_8_buy_rank']
        last_ema_5_8_sell_rank_15m = previous_row_15m['ema_5_8_sell_rank']

        last_bb_flat_market_15m = previous_row_15m['bb_flat_market']
        

        buy_signal_4h =last_ha_close_4h > last_ema_100_4h and last_RSI_9_4h < 70
        sell_signal_4h = last_ha_close_4h < last_ema_100_4h and last_RSI_9_4h > 30



        buy_signal =   last_ema_5_8_buy_signal_15m == 'BUY' and (last_ema_5_8_buy_rank_15m == 1 or last_ema_5_8_buy_rank_15m == 2 ) and  not last_bb_flat_market_15m 
        sell_signal = last_ema_5_8_sell_signal_15m == 'SELL' and (last_ema_5_8_sell_rank_15m == 1 or last_ema_5_8_sell_rank_15m == 2 ) and not last_bb_flat_market_15m  


        buy_condition = buy_signal_4h and buy_signal  

        sell_condition =  sell_signal_4h and sell_signal

        current_candle_time = to_utc_ts(previous_row_15m.get('time', None))

        min_profit = 100

        # Safe timestamp extraction

        # Idempotency: if we already processed this closed candle, exit quietly
        record_exists = olab_check_signal_processing_log_exists(symbol, TF, 'regular', current_candle_time)
        if record_exists:
            return RETURN_NONE7


        signal_data = {
            'pair_info': pair_info,
            'previous_row_15m': previous_row_15m.to_dict(),
            'previous_row_1h': previous_row_1h.to_dict(),            
            'previous_row_4h': previous_row_4h.to_dict()
        }


        # Log that we evaluated this candle (CHECKING stage)
        log_signal_processing(
            candel_time=current_candle_time,
            symbol=symbol,
            interval=TF,
            signal_type='CHECKING',
            signal_source=SIGNAL_SRC,
            signal_data=signal_data,
            processing_time_ms=(time.time() - start_time) * 1000.0,
            machine_id=MAIN_SIGNAL_DETECTOR_ID
        )


        last_open_15m =  previous_row_15m['open']    
        last_low_15m = previous_row_15m['low']       
        last_high_15m =  previous_row_15m['high']  
        last_close_15m = previous_row_15m['close']
        last_atr_15m  = previous_row_15m['ATR_OB']

        last_swing_high_zone_15m = previous_row_15m['swing_high_zone']
        last_swing_low_zone_15m = previous_row_15m['swing_low_zone']

        lower_wick_15m = min(last_open_15m, last_close_15m) - last_low_15m
        upper_wick_15m = last_high_15m - max(last_open_15m, last_close_15m)
        
        candle_body_15m  = abs(last_close_15m - last_open_15m)
        last_Volume_Ratio_15m = previous_row_15m['Volume_Ratio']
        vol_ok = (last_Volume_Ratio_15m >= 1.5)
        
        last_OB_BULL_BOTTOM_4h    = previous_row_4h["OB_BULL_BOTTOM"]
        last_OB_BEAR_TOP_4h = previous_row_4h["OB_BEAR_TOP"]

        sweep_buy_15m = (
                    (last_low_15m < (last_OB_BULL_BOTTOM_4h - 0.15 * last_atr_15m)) and
                    (last_close_15m > last_OB_BULL_BOTTOM_4h) and
                    (lower_wick_15m >= 1.6 * max(candle_body_15m, 1e-9)) and
                    vol_ok
                )

                # For SELL: spike above OB top then close back below OB top/mid
        sweep_sell_15m = (
            (last_high_15m > (last_OB_BEAR_TOP_4h + 0.15 * last_atr_15m)) and
            (last_close_15m < last_OB_BEAR_TOP_4h) and
            (upper_wick_15m >= 1.6 * max(candle_body_15m, 1e-9)) and
            vol_ok
        )



        sweep_event = sweep_buy_15m or sweep_sell_15m

        buy_signal_sweep  = sweep_event and (last_close_15m > last_swing_high_zone_15m) 
        sell_signal_sweep = sweep_event and (last_close_15m < last_swing_low_zone_15m) 


        if  buy_signal_sweep:
              # If asked, skip symbols that already have an active record
            
            min_profit = 100

            if check_exists:
                result = check_if_record_exists(symbol, TF, 'CrossOver')
                if result:
                    # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
                    print(f"⏭️ Skipping {symbol} on {TF} — record already exists for CrossOver.")
                    return RETURN_NONE7
                
            log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=TF,
                        signal_type='BUY_ORDER',
                        signal_source='CrossOver',
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000.0,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )
            
            placeOrder(symbol, '15m', 'BUY', 'CrossOver', df_4h, signal_data,min_profit,invest, 'heiken')  
            return df_4h, 'BUY',  signal_data, 'heiken', 'CrossOver', '15m',min_profit
            

        elif  sell_signal_sweep:
              # If asked, skip symbols that already have an active record
            min_profit = 100

            if check_exists:
                result = check_if_record_exists(symbol, TF, 'CrossOver')
                if result:
                    # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
                    print(f"⏭️ Skipping {symbol} on {TF} — record already exists for CrossOver.")
                    return RETURN_NONE7

                log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=TF,
                        signal_type='SELL_ORDER',
                        signal_source='CrossOver',
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000.0,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )                
            placeOrder(symbol, '15m', 'SELL', 'CrossOver', df_4h, signal_data,min_profit,invest, 'heiken')  
            return df_4h, 'SELL', signal_data, 'heiken', 'CrossOver', '15m',min_profit







        if  buy_condition and vol_ok:
              # If asked, skip symbols that already have an active record
            if last_ema_5_8_buy_rank_15m == 2:
                min_profit = 60

            if check_exists:
                result = check_if_record_exists(symbol, TF, SIGNAL_FAMILY)
                if result:
                    # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
                    print(f"⏭️ Skipping {symbol} on {TF} — record already exists for {SIGNAL_FAMILY}.")
                    return RETURN_NONE7
                
            log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=TF,
                        signal_type='BUY_ORDER',
                        signal_source=SIGNAL_FAMILY,
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000.0,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )
            placeOrder(symbol, '15m', 'BUY', 'IMACD', df_4h, signal_data,min_profit,invest, 'heiken') 
            return df_4h, 'BUY',  signal_data, 'heiken', SIGNAL_FAMILY, '15m',min_profit
            

        elif  sell_condition and vol_ok:
              # If asked, skip symbols that already have an active record
            if last_ema_5_8_sell_rank_15m == 2:
                min_profit = 60

            if check_exists:
                result = check_if_record_exists(symbol, TF, SIGNAL_FAMILY)
                if result:
                    # Fixed the message to reflect the actual timeframe (15m), and clearer reason.
                    print(f"⏭️ Skipping {symbol} on {TF} — record already exists for {SIGNAL_FAMILY}.")
                    return RETURN_NONE7

                log_signal_processing(
                        candel_time=current_candle_time,
                        symbol=symbol,
                        interval=TF,
                        signal_type='SELL_ORDER',
                        signal_source=SIGNAL_FAMILY,
                        signal_data=signal_data,
                        processing_time_ms=(time.time() - start_time) * 1000.0,
                        machine_id=MAIN_SIGNAL_DETECTOR_ID
                    )                
            placeOrder(symbol, '15m', 'SELL', 'IMACD', df_4h, signal_data,min_profit,invest, 'heiken') 
            return df_4h, 'SELL', signal_data, 'heiken', SIGNAL_FAMILY, '15m',min_profit

        # No signal this bar
        return RETURN_NONE7

    except Exception as e:
        print(f"❌ Error processing {symbol} in {SIGNAL_SRC}: {e}")
        # Keep your existing logger contract (includes machine_id)
        log_error(e, SIGNAL_SRC, symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return RETURN_NONE7



# def confirmWithAPI(symbol,  expected_action):
    
#     try:
#         df_api_15m = fetch_ohlcv( symbol, '15m', limit=500)
#         df_api_15m = calculate_all_indicators_optimized(df_api_15m, 'heiken')

#         df_api_2h = fetch_ohlcv( symbol, '2h', limit=500)
#         df_api_2h = calculate_all_indicators_optimized(df_api_2h, 'heiken')

#         df_api_4h = fetch_ohlcv( symbol, '4h', limit=500)
#         df_api_4h = calculate_all_indicators_optimized(df_api_4h, 'heiken') 

#         if df_api_15m is None or getattr(df_api_15m, "empty", True):
#             print(f"❌ No data from API for {symbol} on 15m timeframe.")
#             return False
#         if df_api_2h is None or getattr(df_api_2h, "empty", True):
#             print(f"❌ No data from API for {symbol} on 2h timeframe.")
#             return False
#         if df_api_4h is None or getattr(df_api_4h, "empty", True):
#             print(f"❌ No data from API for {symbol} on 4h timeframe.")
#             return False
        

#         previous_row_15m = df_api_15m.iloc[-1]
#         prior_row_15m = df_api_15m.iloc[-2]

#         previous_row_2h = df_api_2h.iloc[-1]
#         previous_row_4h = df_api_4h.iloc[-1]
        
#         last_tdfi_15m =  previous_row_15m['tdfi_state_2_ema']
#         prior_tdfi_15m =  prior_row_15m['tdfi_state_2_ema']

#         cci_value_9_15m =  previous_row_15m['cci_value_9']

#         tdfi_state_2_ema_4h = previous_row_4h['tdfi_state_2_ema']
#         tdfi_state_3_ema_4h = previous_row_4h['tdfi_state_3_ema']


#         cci_entry_state_9_2h = previous_row_2h['cci_entry_state_9']
#         cci_sma_9_2h = previous_row_2h['cci_sma_9']


#         buy_condition   = ( cci_value_9_15m < 100 and
#                 last_tdfi_15m == 'BULL' and (prior_tdfi_15m == 'FLAT' or prior_tdfi_15m == 'BEAR')
                
#                 and tdfi_state_2_ema_4h == 'BULL' and tdfi_state_3_ema_4h == 'BULL' 
#                                 and 
#                 (
#                 ( cci_entry_state_9_2h == 'BULL' and cci_sma_9_2h == 'INCREASING') 
#                 or
#                 ( cci_entry_state_9_2h == 'BEAR' and cci_sma_9_2h == 'DECREASING') 
#                 ))

#         sell_condition = (  cci_value_9_15m > -100 and
#                 last_tdfi_15m == 'BEAR' and (prior_tdfi_15m == 'FLAT' or prior_tdfi_15m == 'BULL')
#                 and tdfi_state_2_ema_4h == 'BEAR' and tdfi_state_3_ema_4h == 'BEAR' 
#                                 and 
#                 (
#                 ( cci_entry_state_9_2h == 'BEAR' and cci_sma_9_2h == 'INCREASING') 
#                 or
#                 ( cci_entry_state_9_2h == 'BULL' and cci_sma_9_2h == 'DECREASING') 
#                 ))
        
#         if expected_action == 'BUY' and buy_condition:
#             return True
        
#         elif expected_action == 'SELL' and sell_condition:
#             return True

#         return False     

#     except Exception as e:
#         print(f"❌ Error in confirmWithAPI for {symbol} on : {e}")
#         log_error(e, "confirmWithAPI", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
#         return False


def fetch_ohlcv(symbol, timeframe, limit=500, retries=3, delay=1.0):
    import time, pandas as pd
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            klines = client.klines(symbol=symbol, interval=timeframe, limit=limit)
            if not klines:
                raise ValueError("Empty response from API")

            df = pd.DataFrame(
                klines,
                columns=['time','open','high','low','close','volume',
                         'close_time','quote_av','trades','tb_base_av',
                         'tb_quote_av','ignore']
            )
            # keep 'time' AS A COLUMN
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            df = df[['time','open','high','low','close','volume']].astype(float, errors='ignore')
            # sort and also set index, but DO NOT drop the 'time' column
            return df
        except Exception as e:
            last_err = e
            print(f"Attempt {attempt}/{retries} failed for {symbol} {timeframe}: {e}")
            if attempt < retries:
                time.sleep(delay)

    print(f"❌ Error fetching OHLCV after {retries} attempts for {symbol} {timeframe}: {last_err}")
    return pd.DataFrame(columns=['time','open','high','low','close','volume'])


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



def tdfi_Strategy(pair_info):
    try:
        symbol = pair_info['pair']

        print(f"🎯 Processing squeezed pair with signals: {symbol}")
        df,action,signal_data,candle_type,signalFrom,interval,min_profit = tdfi_breakout(pair_info,check_exists = True)
        return df,action,signal_data,candle_type,signalFrom,interval,min_profit
    except Exception as e:
        print(f"❌ Error processing squeezed pair {symbol}: {e}")
        log_error(e, "tdfi_Strategy", symbol, machine_id=MAIN_SIGNAL_DETECTOR_ID)
        return None,None,None,None,None,None,None

def process_non_squeezed_pair_with_signal(pair_info):
    try:
        symbol = pair_info['pair']     
        result = tdfi_Strategy(pair_info)
        # if result is not None and isinstance(result, tuple) and len(result) == 7:
        #     df, action, signal_data, candle_type, signalFrom, interval,min_profit   = result
        #     if action == 'BUY' or action =='SELL':              
        #         placeOrder(symbol, interval, action, signalFrom, df, signal_data,min_profit, candle_type)       
        
    except Exception as e:
        print(f"❌ Error processing squeezed pair {pair_info.get('pair', 'unknown')}: {e}")
        log_error(e, "process_squeezed_pair_with_signal", pair_info.get('pair', 'unknown'), machine_id=MAIN_SIGNAL_DETECTOR_ID)


def setSuperTrend():
    global   superTrend,superTrendPercent,superTrendLong,superTrendShort 
    try: 
        superTrend = getSuperTrend(2400)
        superTrendPercent = getSuperTrendPercent(30)

        superTrendLong = ( superTrend == 'BUY' and superTrendPercent )
        superTrendShort = ( superTrend == 'SELL' and superTrendPercent )
        print(f"SuperTrend: {superTrend} with Percent: {superTrendPercent}")
    except Exception as e:
        print(f"❌ Error in setSuperTrend: {e}")
        log_error(e, "setSuperTrend", "N/A", machine_id=MAIN_SIGNAL_DETECTOR_ID)
    

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

        # print(f"🧠 Running PriceAction for {len(pairs_info)} non-squeezed pairs...")

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
    
    # df_api = fetch_ohlcv( 'XRPUSDT', '15m', limit=500)
    # df_api = calculate_all_indicators_optimized(df_api, 'heiken')
    # print(df_api.tail(5))
    # asyncio.run(send_message_to_users(f"hello from olab_M2"))
    main() 
