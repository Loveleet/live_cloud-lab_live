# utils/logger.py

import os
import datetime
from datetime import timezone
import traceback

import numpy as np
from machine_id import get_machine_id
# from utils.FinalVersionTradingDB_PostgreSQL import (    
#     insert_bot_event_log, 
#     update_tmux_log,
#     # Enhanced logging system database functions
#     insert_enhanced_error_log,
#     insert_signal_processing_log,
#     insert_signal_validation_log,
#     insert_performance_metric,
#     insert_batch_processing_log,
#     insert_system_health_log,
#     insert_cache_performance_log,
#     sql_helper
# )

from utils.Final_olab_database import (    
    olab_insert_bot_event_log, 
    olab_update_tmux_log,
    # Enhanced logging system database functions
    olab_insert_enhanced_error_log,
    olab_insert_signal_processing_log,
    olab_insert_signal_validation_log,
    olab_insert_performance_metric,
    olab_insert_batch_processing_log,
    olab_insert_system_health_log,
    olab_insert_cache_performance_log
)


import json
from utils.global_store import log_lock, analysis_tracker,all_pairs
from decimal import Decimal

# Custom JSON encoder to handle Decimal objects
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)
import re
import psutil
import pandas as pd
import time
import threading
from functools import wraps

print_lock = threading.Lock()

# Path to save local log files
ERROR_LOG_DIR = "logs_error"
os.makedirs(ERROR_LOG_DIR, exist_ok=True)

EVENT_LOG = "log_event"
os.makedirs(EVENT_LOG, exist_ok=True)

SIGNAL_LOG_DIR = "signal_logs"
os.makedirs(SIGNAL_LOG_DIR, exist_ok=True)

PERFORMANCE_LOG_DIR = "performance_logs"
os.makedirs(PERFORMANCE_LOG_DIR, exist_ok=True)

# Add this at top of logger.py
_last_errors = {}  # {(uid, source): (message, timestamp)}

# =====================================================
# ENHANCED ERROR LOGGING FUNCTIONS
# =====================================================

def log_to_file(message, filename, uid=None):
    """
    Write message to a log file with timestamp. If uid is provided, log to a per-UID file.
    """
    import os
    if uid is not None:
        safe_uid = sanitize_filename(str(uid))
        filename = f"info_{safe_uid}"
    filepath = os.path.join(ERROR_LOG_DIR, f"{filename}.log")
    timestamp = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
#    with open(filepath, "a", encoding="utf-8") as f:
#        f.write(f"[{timestamp}] {message}\n")


def log_to_file_reject_from_api(message, filename, uid=None):
    """
    Write message to a log file with timestamp. If uid is provided, log to a per-UID file.
    """
    import os
    if uid is not None:
        safe_uid = sanitize_filename(str(uid))
        filename = f"info_{safe_uid}"
    filepath = os.path.join(ERROR_LOG_DIR, f"{filename}.log")
    timestamp = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

def log_info(message, filename="info", uid=None):
    """
    Log general information to file. If uid is provided, log to a per-UID file.
    """
    log_to_file(f"ℹ️ {message}", filename, uid=uid)

def utc_now():
    return datetime.datetime.now(timezone.utc)

def log_error(e, source, uid=None, error_level="ERROR", error_category="SYSTEM", machine_id=None):
    """
    Enhanced error logging with categorization and database storage
    """
    timestamp = utc_now()
    message = str(e)
    key = (uid, source)
    now_ts = timestamp.timestamp()

    # ✅ Deduplication Check (repeat error within 60s)
    last_msg, last_ts = _last_errors.get(key, ("", 0))
    if message == last_msg and now_ts - last_ts < 60:
        return  # Skip repeated error

    _last_errors[key] = (message, now_ts)  # Update tracker

    # ✅ Extract traceback and line number
    line_number = traceback.extract_tb(e.__traceback__)[-1].lineno if e.__traceback__ else -1
    full_trace = traceback.format_exc()

    # ✅ Plain file log
    try:
        filepath = os.path.join(ERROR_LOG_DIR, f"enhanced_error.log")
        with open(filepath, "a", encoding="utf-8") as f:
            f.write("Enhanced Error Log:\n")
            f.write(f"Time: {timestamp}\n")
            f.write(f"{'='*40}\n")
            f.write(f"Level: {error_level}\n")
            f.write(f"Category: {error_category}\n")
            f.write(f"Pair: {uid}\n")
            f.write(f"Context: {source}\n")
            f.write(f"Error: {message}\n")
            f.write(f"Line Number: {line_number}\n")
            f.write("Traceback:\n")
            f.write(full_trace)
            f.write(f"{'='*40}\n\n")
    except Exception as file_err:
        print(f"❌ File Log Error: {file_err}")

    # ✅ Prepare JSON object
    json_error_obj = {
        "timestamp": str(timestamp),
        "error_level": error_level,
        "error_category": error_category,
        "uid": uid,
        "context": source,
        "error": message,
        "line_number": line_number,
        "traceback": full_trace
    }

    # ✅ Insert into enhanced error logs table (only if machine_id is provided)
    if machine_id is not None:
        try:
            with log_lock:
                json_str = json.dumps(json_error_obj) if json_error_obj else None
                olab_insert_enhanced_error_log(
                    error_level=error_level,
                    error_category=error_category,
                    symbol=uid,
                    source_function=source,
                    error_message=message,
                    line_number=line_number,
                    stack_trace=full_trace,
                    machine_id=machine_id,
                    timestamp=timestamp,
                    json_context=json_str
                )
        except Exception as db_err:
            print(f"❌ DB Error Logging Failed: {db_err}")
            print(f"❌ ERROR at {source} | UID: {uid} | {db_err}\n{traceback.format_exc()}")

def log_critical_error(e, source, uid=None):
    """Log critical errors that require immediate attention"""
    log_error(e, source, uid, "CRITICAL", "SYSTEM")

def log_api_error(e, source, uid=None):
    """Log API-related errors"""
    log_error(e, source, uid, "ERROR", "API")

def log_database_error(e, source, uid=None):
    """Log database-related errors"""
    log_error(e, source, uid, "ERROR", "DATABASE")

def log_signal_processing_error(e, source, uid=None):
    """Log signal processing errors"""
    log_error(e, source, uid, "ERROR", "SIGNAL_PROCESSING")

# =====================================================
# SIGNAL PROCESSING LOGGING FUNCTIONS
# =====================================================

def log_signal_processing(candel_time, symbol, interval, signal_type, signal_source, signal_data, processing_time_ms, machine_id=None,uid=None):
    """
    Log signal processing activities with comprehensive data. processing_time_ms is now required.
    """
    try:
        timestamp = utc_now()
        
        # Extract signal data
        def _to_bool(value):
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("1", "true", "t", "yes", "y", "on"):
                    return True
                if v in ("0", "false", "f", "no", "n", "off"):
                    return False
            return bool(value)

        price = signal_data.get('price')
        candle_pattern = signal_data.get('candle_pattern', 'regular')
        squeeze_status = _to_bool(signal_data.get('squeeze_status', False))
        active_squeeze = _to_bool(signal_data.get('active_squeeze', False))

        print(f"Squeeze status: {squeeze_status}")
        
        # Prepare JSON data with signal_data (which already contains df_15m_last_row and timeframe data)
        json_data = {
            "signal_data": signal_data,
            "processing_time_ms": processing_time_ms,
            "timestamp": str(timestamp)
        }
        
        # Log to file
        # log_filename = os.path.join(SIGNAL_LOG_DIR, f"{symbol}_{interval}_signals.log")
        # with open(log_filename, "a", encoding="utf-8") as f:
        #     f.write(f"Signal Processing Log:\n")
        #     f.write(f"UID: {uid}\n")
        #     f.write(f"Machine ID: {machine_id}\n")
        #     f.write(f"Candle Time: {candel_time}\n")
        #     f.write(f"Time: {timestamp}\n")
        #     f.write(f"Symbol: {symbol} | Interval: {interval}\n")
        #     f.write(f"Signal Type: {signal_type} | Source: {signal_source}\n")
        #     f.write(f"Candle Pattern: {candle_pattern}\n")
        #     f.write(f"Price: {price}\n")
        #     f.write(f"Squeeze Status: {squeeze_status} | Active Squeeze: {active_squeeze}\n")
        #     f.write(f"json_data: {json_data}\n")
        #     f.write(f"{'='*50}\n\n")
        

        # Clean JSON data to remove NaN values for PostgreSQL compatibility
        from utils.fix_json_nan_issue import safe_json_dumps
        olab_update_tmux_log('FinalTrading')
        olab_insert_signal_processing_log(
            candle_time=candel_time,
            symbol=symbol,
            interval=interval,
            signal_type=signal_type,
            signal_source=signal_source,
            candle_pattern=candle_pattern,
            price=price,
            squeeze_status=squeeze_status,
            active_squeeze=active_squeeze,
            processing_time_ms=processing_time_ms,
            machine_id=machine_id,
            timestamp=timestamp,           
            json_data=safe_json_dumps(json_data),
            unique_id=uid
        )
        
    except Exception as e:
        print(f"❌ Error logging signal processing: {e}")
        log_error(e, "log_signal_processing", symbol)

def calculate_signal_strength(signal_data):
    """Calculate signal strength based on various indicators"""
    try:
        strength = 0.0
        
        # RSI contribution (0-30 or 70-100 is stronger)
        rsi = signal_data.get('rsi_value', 50)
        if rsi <= 30 or rsi >= 70:
            strength += 0.3
        elif rsi <= 40 or rsi >= 60:
            strength += 0.2
        else:
            strength += 0.1
        
        # MACD contribution
        macd = signal_data.get('macd_value', 0)
        if abs(macd) > 0.001:
            strength += 0.2
        
        # BBW contribution (lower BBW = stronger signal)
        bbw = signal_data.get('bbw_value', 1.0)
        if bbw < 0.05:
            strength += 0.3
        elif bbw < 0.1:
            strength += 0.2
        else:
            strength += 0.1
        
        # Trend contribution
        trend = signal_data.get('trend_direction', 'NEUTRAL')
        if trend in ['UPTREND', 'DOWNTREND']:
            strength += 0.2
        
        return min(strength, 1.0)  # Cap at 1.0
        
    except Exception as e:
        return 0.5  # Default strength

def log_signal_validation(symbol, interval, validation_step, validation_result, 
                         validation_value=None, validation_threshold=None, 
                         validation_message=None, json_data=None, machine_id=None):
    """
    Log signal validation steps
    """
    try:
        timestamp = utc_now()
        
        # Log to file
        # log_filename = os.path.join(SIGNAL_LOG_DIR, f"{symbol}_{interval}_validation.log")
        # with open(log_filename, "a", encoding="utf-8") as f:
        #     f.write(f"Signal Validation Log:\n")
        #     f.write(f"Time: {timestamp}\n")
        #     f.write(f"Symbol: {symbol} | Interval: {interval}\n")
        #     f.write(f"Step: {validation_step} | Result: {'PASS' if validation_result else 'FAIL'}\n")
        #     f.write(f"Value: {validation_value} | Threshold: {validation_threshold}\n")
        #     f.write(f"Message: {validation_message}\n")
        #     f.write(f"{'='*50}\n\n")
        
        # Insert into database (only if machine_id is provided)
        if machine_id is not None:
            olab_insert_signal_validation_log(
                symbol=symbol,
                interval=interval,
                validation_step=validation_step,
                validation_result=validation_result,
                validation_value=validation_value,
                validation_threshold=validation_threshold,
                validation_message=validation_message,
                machine_id=machine_id,
                timestamp=timestamp,
                json_data=json.dumps(json_data, cls=DecimalEncoder) if json_data else None
            )
        
    except Exception as e:
        print(f"❌ Error logging signal validation: {e}")
        log_error(e, "log_signal_validation", symbol)

# =====================================================
# PERFORMANCE METRICS LOGGING FUNCTIONS
# =====================================================

def log_performance_metric(metric_type, metric_name, metric_value, metric_unit=None, 
                          symbol=None, interval=None, batch_size=None, additional_data=None, machine_id=None):
    """
    Log performance metrics for monitoring and optimization
    """
    try:
        timestamp = utc_now()
        
        # Log to file
        # log_filename = os.path.join(PERFORMANCE_LOG_DIR, f"{metric_type}_{metric_name}.log")
        # with open(log_filename, "a", encoding="utf-8") as f:
        #     f.write(f"Performance Metric:\n")
        #     f.write(f"Time: {timestamp}\n")
        #     f.write(f"Type: {metric_type} | Name: {metric_name}\n")
        #     f.write(f"Value: {metric_value} {metric_unit or ''}\n")
        #     f.write(f"Symbol: {symbol} | Interval: {interval}\n")
        #     f.write(f"Batch Size: {batch_size}\n")
        #     f.write(f"{'='*50}\n\n")
        
        # Insert into database (only if machine_id is provided)
        if machine_id is not None:
            olab_insert_performance_metric(
                metric_type=metric_type,
                metric_name=metric_name,
                metric_value=metric_value,
                metric_unit=metric_unit,
                symbol=symbol,
                interval=interval,
                batch_size=batch_size,
                machine_id=machine_id,
                timestamp=timestamp,
                additional_data=json.dumps(additional_data, cls=DecimalEncoder) if additional_data else None
            )
        
    except Exception as e:
        print(f"❌ Error logging performance metric: {e}")
        log_error(e, "log_performance_metric", symbol)

def performance_monitor(metric_type, metric_name, metric_unit=None, machine_id=None):
    """
    Decorator to monitor function performance
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                processing_time = (time.time() - start_time) * 1000  # Convert to ms
                
                # Extract symbol from args if available
                symbol = None
                if args and isinstance(args[0], str):
                    symbol = args[0]
                
                log_performance_metric(
                    metric_type=metric_type,
                    metric_name=metric_name,
                    metric_value=processing_time,
                    metric_unit="ms",
                    symbol=symbol,
                    machine_id=machine_id
                )
                
                return result
            except Exception as e:
                processing_time = (time.time() - start_time) * 1000
                log_performance_metric(
                    metric_type=metric_type,
                    metric_name=f"{metric_name}_error",
                    metric_value=processing_time,
                    metric_unit="ms",
                    symbol=symbol,
                    machine_id=machine_id
                )
                raise
        return wrapper
    return decorator

# =====================================================
# BATCH PROCESSING LOGGING FUNCTIONS
# =====================================================

def log_batch_processing(batch_type, batch_size, successful_count, error_count, 
                        crash_count, total_processing_time_ms, executor_type, 
                        worker_count, json_details=None, machine_id=None):
    """
    Log batch processing performance and results
    """
    try:
        timestamp = utc_now()
        average_time_per_item_ms = total_processing_time_ms / batch_size if batch_size > 0 else 0
        
        # Log to file
        # log_filename = os.path.join(PERFORMANCE_LOG_DIR, f"batch_processing_{batch_type}.log")
        # with open(log_filename, "a", encoding="utf-8") as f:
        #     f.write(f"Batch Processing Log:\n")
        #     f.write(f"Time: {timestamp}\n")
        #     f.write(f"Type: {batch_type} | Size: {batch_size}\n")
        #     f.write(f"Success: {successful_count} | Errors: {error_count} | Crashes: {crash_count}\n")
        #     f.write(f"Total Time: {total_processing_time_ms}ms | Avg per Item: {average_time_per_item_ms:.2f}ms\n")
        #     f.write(f"Executor: {executor_type} | Workers: {worker_count}\n")
        #     f.write(f"{'='*50}\n\n")
        
        # Insert into database (only if machine_id is provided)
        if machine_id is not None:
            olab_insert_batch_processing_log(
                batch_type=batch_type,
                batch_size=batch_size,
                successful_count=successful_count,
                error_count=error_count,
                crash_count=crash_count,
                total_processing_time_ms=total_processing_time_ms,
                average_time_per_item_ms=average_time_per_item_ms,
                machine_id=machine_id,
                timestamp=timestamp,
                executor_type=executor_type,
                worker_count=worker_count,
                json_details=json.dumps(json_details, cls=DecimalEncoder) if json_details else None
            )
        
    except Exception as e:
        print(f"❌ Error logging batch processing: {e}")
        log_error(e, "log_batch_processing", batch_type)

# =====================================================
# SYSTEM HEALTH LOGGING FUNCTIONS
# =====================================================

def log_system_health(machine_id=None):
    """
    Enhanced system health monitoring with comprehensive metrics
    """
    try:
        timestamp = utc_now()
        # Get system metrics
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        memory_available_mb = memory.available / (1024 * 1024)
        # Get disk usage
        disk_usage = psutil.disk_usage('/') if os.name != 'nt' else psutil.disk_usage('C:\\')
        disk_usage = disk_usage.percent
        # Get network latency (simplified)
        network_latency_ms = 0  # Could implement actual ping test
        # Get process/thread counts
        active_threads = threading.active_count()
        active_processes = len(psutil.pids())
        # Get database connections (approximate)
        database_connections = 0  # Could implement actual DB connection count
        # Calculate error rate (simplified)
        error_rate_percent = 0.0  # Could implement actual error rate calculation
        # Determine health status
        if cpu_usage > 90 or memory_usage > 90:
            health_status = "CRITICAL"
        elif cpu_usage > 70 or memory_usage > 70:
            health_status = "WARNING"
        else:
            health_status = "HEALTHY"
        # Log to file
        # log_filename = os.path.join(PERFORMANCE_LOG_DIR, "system_health.log")
        # with open(log_filename, "a", encoding="utf-8") as f:
        #     f.write(f"System Health Log:\n")
        #     f.write(f"Time: {timestamp}\n")
        #     f.write(f"CPU: {cpu_usage}% | Memory: {memory_usage}% | Available: {memory_available_mb:.2f}MB\n")
        #     f.write(f"Disk: {disk_usage}% | Network Latency: {network_latency_ms}ms\n")
        #     f.write(f"Threads: {active_threads} | Processes: {active_processes}\n")
        #     f.write(f"DB Connections: {database_connections} | Error Rate: {error_rate_percent}%\n")
        #     f.write(f"Health Status: {health_status}\n")
        #     f.write(f"{'='*50}\n\n")
        # Insert into database (only if machine_id is provided)
        if machine_id is not None:
            olab_insert_system_health_log(
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                memory_available_mb=memory_available_mb,
                disk_usage=disk_usage,
                network_latency_ms=network_latency_ms,
                active_threads=active_threads,
                active_processes=active_processes,
                database_connections=database_connections,
                api_calls_per_minute=0,  # Could implement actual API call tracking
                error_rate_percent=error_rate_percent,
                machine_id=machine_id,
                timestamp=timestamp,
                health_status=health_status
            )
        try:
            print(f"🧠 CPU: {cpu_usage}% | 🧵 Threads: {active_threads} | 💾 Memory: {memory_usage}% | Status: {health_status}")
        except OSError as e:
            # Fallback: log to a file if print fails
            fallback_log = os.path.join(PERFORMANCE_LOG_DIR, "system_health_fallback.log")
            with open(fallback_log, "a", encoding="utf-8") as f:
                f.write(f"[PRINT FAIL] {timestamp}: 🧠 CPU: {cpu_usage}% | 🧵 Threads: {active_threads} | 💾 Memory: {memory_usage}% | Status: {health_status}\n")
                f.write(f"[PRINT FAIL] {timestamp}: {e}\n")
    except Exception as e:
        try:
            print(f"❌ System health logging failed: {e}")
        except OSError:
            fallback_log = os.path.join(PERFORMANCE_LOG_DIR, "system_health_fallback.log")
            with open(fallback_log, "a", encoding="utf-8") as f:
                f.write(f"[PRINT FAIL] {timestamp}: ❌ System health logging failed: {e}\n")
        log_error(e, "log_system_health", "SYSTEM")

# =====================================================
# CACHE PERFORMANCE LOGGING FUNCTIONS
# =====================================================

def log_cache_performance(cache_type, operation_type, symbol=None, interval=None, 
                         cache_key=None, response_time_ms=None, cache_size_mb=None, 
                         hit_rate_percent=None, machine_id=None):
    """
    Log cache performance metrics
    """
    try:
        timestamp = utc_now()
        
        # Log to file
        # log_filename = os.path.join(PERFORMANCE_LOG_DIR, f"cache_{cache_type}.log")
        # with open(log_filename, "a", encoding="utf-8") as f:
        #     f.write(f"Cache Performance Log:\n")
        #     f.write(f"Time: {timestamp}\n")
        #     f.write(f"Type: {cache_type} | Operation: {operation_type}\n")
        #     f.write(f"Symbol: {symbol} | Interval: {interval}\n")
        #     f.write(f"Key: {cache_key} | Response Time: {response_time_ms}ms\n")
        #     f.write(f"Size: {cache_size_mb}MB | Hit Rate: {hit_rate_percent}%\n")
        #     f.write(f"{'='*50}\n\n")
        
        # Insert into database (only if machine_id is provided)
        if machine_id is not None:
            olab_insert_cache_performance_log(
                cache_type=cache_type,
                operation_type=operation_type,
                symbol=symbol,
                interval=interval,
                cache_key=cache_key,
                response_time_ms=response_time_ms,
                cache_size_mb=cache_size_mb,
                hit_rate_percent=hit_rate_percent,
                machine_id=machine_id,
                timestamp=timestamp
            )
        
    except Exception as e:
        print(f"❌ Error logging cache performance: {e}")
        log_error(e, "log_cache_performance", symbol)

# =====================================================
# LEGACY FUNCTIONS (for backward compatibility)
# =====================================================



def log_event(uid, source, message, Pl_after_comm, json_data=None):
    timestamp = utc_now()

    # Always use the full tracker as default if json_data is not provided
    if json_data is None:
        json_data = analysis_tracker.get(uid, {}).copy()
        json_data.update(all_pairs.get(uid, {}))

    json_str = safe_json_dumps(json_data)

    # ✅ Save to file named after UID
    # try:
    #     uid_file_name = sanitize_filename(uid)
    #     log_filename = os.path.join(EVENT_LOG, f"{uid_file_name}_event_log.txt")

    #     with open(log_filename, "a", encoding="utf-8") as f:
    #         f.write(f"------------------Start----------------------\n")
    #         f.write(f"[{timestamp}] [{source}] {message}\n")
    #         f.write(f"JSON:\n{json_str}\n\n")
    #         f.write(f"------------------End----------------------\n")
    # except Exception as file_err:
    #     print(f"❌ Event File Log Error: {file_err}")
    #     print(f"❌ ERROR at {source} | UID: {uid} | {file_err}\n{traceback.format_exc()}")

    # ✅ Save to database (only if machine_id is available)
    try:
        with log_lock:
            machine_id = get_machine_id()
            olab_insert_bot_event_log(
                uid,
                source,
                Pl_after_comm,
                message,
                json_str,
                timestamp,
                machine_id
            )
    except Exception as db_err:
        log_error(db_err, "log_event", "SYSTEM")
        print(f"❌ DB Event Logging Failed: {db_err}")
        print(f"❌ ERROR at {source} | UID: {uid} | {db_err}\n{traceback.format_exc()}")      

def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs)  

def sanitize_filename(name):
    """Remove invalid characters for filenames (Windows-safe)."""
    return re.sub(r'[:\\/*?"<>|]', '_', name)

def default_serializer(obj):
    if isinstance(obj, (datetime.datetime, pd.Timestamp)):
        return obj.isoformat()
    elif isinstance(obj, (float, int)) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return str(obj)

def safe_json_dumps(data):
    try:
        # Convert NaN, inf, etc. before serializing
        clean_data = clean_invalid_json_values(data)
        json_str = json.dumps(clean_data, indent=2, default=default_serializer, ensure_ascii=False)
        json.loads(json_str)  # Validate for SQL Server ISJSON()
        return json_str
    except Exception as e:
        log_error(e, "safe_json_dumps", "SYSTEM")
        print(f"❌ Invalid JSON for DB insert: {e}")
        return '{}'

def clean_invalid_json_values(obj):
    if isinstance(obj, dict):
        return {k: clean_invalid_json_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_invalid_json_values(item) for item in obj]
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    return obj
