import os
from urllib.parse import quote_plus
import threading
import traceback
import numpy as np
import pandas as pd
import time
from binance.um_futures import UMFutures
from sqlalchemy import create_engine, text, pool
from sqlalchemy.pool import QueuePool, NullPool
from datetime import datetime, timezone, timedelta
from threading import Semaphore
import queue
from dateutil import parser
import sys
import logging
import re
from psycopg2.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
import platform


# from main_binance import CandleColor  # Importing the CandleColor function

# --- DB Insert Queue and Worker Threads (REMOVED - Using immediate insertion) ---
# insert_queue = queue.Queue()
# NUM_DB_WORKERS = 10

# def db_insert_worker():
#     while True:
#         symbol, interval, klines = insert_queue.get()
#         try:
#             olab_insert_klines(symbol, interval, klines)
#         except Exception as e:
#             print(f"❌ DB insert failed for {symbol}-{interval}: {e}")
#         finally:
#             insert_queue.task_done()

# for _ in range(NUM_DB_WORKERS):
#     t = threading.Thread(target=db_insert_worker, daemon=True)
#     t.start()

# --- Global Weight Tracking for Binance API ---
from datetime import datetime, timezone


# Global weight tracking dictionary
weight_tracker = {
    'current_weight': 0,
    'last_reset_time': None,
    'weight_threshold': 1800,  # 75% of 2400
    'max_weight_1m': 2400
}

# Cache for tracking when data was last successfully fetched from DB
data_cache = {}

# Create logs_error directory if it doesn't exist
logs_error_dir = "logs_error"
if not os.path.exists(logs_error_dir):
    os.makedirs(logs_error_dir)

def olab_log_weight_limit_reached(symbol, interval, current_weight):
    """Log when weight limit is reached"""
    try:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        log_message = f"[{timestamp}] Weight limit reached: {current_weight}/{weight_tracker['max_weight_1m']} for {symbol}-{interval}\n"
        
        log_file = os.path.join(logs_error_dir, "weight_limit_reached.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_message)
        
        print(f"📝 Weight limit logged: {current_weight}/{weight_tracker['max_weight_1m']} for {symbol}-{interval}")
        
    except Exception as e:
        print(f"❌ Failed to log weight limit: {e}")

def olab_log_api_limit_error(symbol, interval, error_message):
    """Log API limit errors"""
    try:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        log_message = f"[{timestamp}] API Limit Error for {symbol}-{interval}: {error_message}\n"
        
        log_file = os.path.join(logs_error_dir, "api_limit_error.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_message)
        
        print(f"📝 API limit error logged for {symbol}-{interval}")
        
    except Exception as e:
        print(f"❌ Failed to log API limit error: {e}")

def olab_can_make_api_call():
    """Check if we can make an API call based on weight usage"""
    now_utc = datetime.now(timezone.utc)
    
    # Check if 1 minute has passed - reset weight
    if (weight_tracker['last_reset_time'] is None or 
        (now_utc - weight_tracker['last_reset_time']).total_seconds() >= 60):
        
        weight_tracker['current_weight'] = 0
        weight_tracker['last_reset_time'] = now_utc
        print(f"🔄 Weight reset at {now_utc.strftime('%H:%M:%S')} UTC")
    
    # Check if weight exceeds threshold
    if weight_tracker['current_weight'] >= weight_tracker['weight_threshold']:
        print(f"⚠️ Weight limit reached: {weight_tracker['current_weight']}/{weight_tracker['max_weight_1m']}")
        return False
    
    return True

def olab_update_weight_from_headers(symbol,interval):
    """Update weight from Binance response headers"""
    try:
        if hasattr(client, '_last_response'):
            headers = client._last_response.headers
            weight = headers.get("X-MBX-USED-WEIGHT-1M")
            if weight:
                weight_tracker['current_weight'] = int(weight)
                percentage = (weight_tracker['current_weight'] / weight_tracker['max_weight_1m']) * 100
                print(f"📊 Weight updated: {symbol}-{interval} -> {weight_tracker['current_weight']}/{weight_tracker['max_weight_1m']} ({percentage:.1f}%)")
                
                # Log if weight limit is reached
                if weight_tracker['current_weight'] >= weight_tracker['weight_threshold']:
                    olab_log_weight_limit_reached("GLOBAL", "ALL", weight_tracker['current_weight'])
                    
    except Exception as e:
        print(f"⚠️ Failed to update weight from headers: {e}")

# Simple rate limiter for basic request limiting
class SimpleRateLimiter:
    def __init__(self, max_per_sec=3):
        self.max_per_sec = max_per_sec
        self.lock = threading.Lock()
        self.timestamps = []

    def acquire(self):
        with self.lock:
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < 1]
            if len(self.timestamps) >= self.max_per_sec:
                sleep_time = 1 - (now - self.timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self.timestamps.append(time.time())

# Global simple rate limiter
binance_limiter = SimpleRateLimiter(3)

# 🚨 Controls concurrent DB connections globally - Ultra Conservative
DB_SEMAPHORE = Semaphore(12)  # Balanced - allows reasonable concurrent database operations

INTERVAL_MS = {
    '1m': 60_000,
    '3m': 180_000,
    '5m': 300_000,
    '15m': 900_000,
    '30m': 1_800_000,
    '1h': 3_600_000,
    '2h': 7_200_000,
    '4h': 14_400_000,
    '1d': 86_400_000
}

API_KEYS = [
    {"api_key": "d8d0107edbc3794599efcbd9ae6b640bf46241b48d866edc806df65f0b6dbc22", "api_secret": "476a347161016506113c608fdd621a502e3e72b786f126f4da10af2a9f9335c2"},
    {"api_key": "3i2ZW2WqaU3bckPJN6E6JwBewelLOGDImNNA4z5PrcT3TZXvha4VwDYPr6z8xMOn", "api_secret": "hSVSyIDVNzpbyKAVPq8X4AJQ8NAkiUQMhT2UZDnw76rBUFDgJnXIA435J9KAXUC8"},
    {"api_key": "seSpIhGqzKPaDMQSX2fBkj5HfOyss1dUPyhwN6zfqTmUQLYSOsvtzBZ6uWN0svgV", "api_secret": "GQ3sn0TjR9VEDn3lBipDRmaGxoU9BercHNVZYOEaleneTVsd1gFZMv7FiIwa4iO9"},
    {"api_key": "eIWajxTqaT8l7LkoyNUQBbTV447ZwfZh2lSbS9wQTn2TEtHnEjIBbARZtU8twQnj", "api_secret": "HKXTKyiqDsvblmkzBiQ1s2D4CUh2hHJIjzxu4Y6DM4M5hz2Kbs2xmowXVZrP1LdD"},
    {"api_key": "Pi1VQWPhUiNUVigmHepoaOKG53NhroN0stwqYcTnLDosz8G9SrWJTxlOHzTD5LHr", "api_secret": "nGk5dOAYTnAaxVnRDhXxegaCdGYEyzGAxx53ryeWDIob1XXAMlazDQGO8mFEIYJS"},
    # Add more keys as needed
]

# PostgreSQL Connection String - Update these values for your PostgreSQL server
# Format: postgresql://username:password@host:port/database
# If running on Ubuntu/Linux (cloud), use localhost; otherwise use LAN IP.
if platform.system().lower() == "linux":
    # Ubuntu / cloud server: PostgreSQL on same machine
    connection_string_postgresql = "postgresql://lab:IndiaNepal1-@127.0.0.1:5432/olab"
else:
    # Windows / other: connect to LAN database server
    connection_string_postgresql = "postgresql://lab:IndiaNepal1-@192.168.18.14:5432/olab"

def olab_create_new_engine():
    return create_engine(
        connection_string_postgresql,
        connect_args={
            'connect_timeout': 30,
            'application_name': 'TradingBot',
            'sslmode': 'disable'
        },
        pool_size=50,          # number of persistent connections
        max_overflow=80,       # allow up to 100 concurrent
        pool_timeout=30,       # wait before giving up
        pool_recycle=1800,     # recycle every 30 min
        pool_pre_ping=True,    # test before use
        echo=False
    )


# Initialize an engine for the main process; child processes will re-create their own
engine = olab_create_new_engine()

pd.set_option('display.float_format', '{:.8f}'.format)  # disable scientific notation globally

current_api_index = 0
client = UMFutures(key=API_KEYS[current_api_index]['api_key'], secret=API_KEYS[current_api_index]['api_secret'])

# Setup header capture for weight tracking
def olab_setup_header_capture(client):
    """Setup monkey patching to capture Binance response headers"""
    try:
        # Store original request method
        original_request = client.session.request
        
        # Create a wrapper to capture headers
        def request_with_headers(*args, **kwargs):
            response = original_request(*args, **kwargs)
            # Store the response for later access
            client._last_response = response
            return response
        
        # Monkey patch the request method
        client.session.request = request_with_headers
        print("✅ Header capture setup complete")
        
    except Exception as e:
        print(f"⚠️ Header capture setup failed: {e}")

# Setup header capture for the main client
olab_setup_header_capture(client)

# --- Enhanced SQL Access Helper for PostgreSQL ---
class SQLAccessHelper:
    def __init__(self, engine):
        self.engine = engine
        self._pid = os.getpid()
        self.connection_lock = threading.Lock()
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5 minutes
        
    def _ensure_engine(self):
        """Ensure the helper holds an engine created in the current process.
        If a fork occurred, dispose the inherited engine and create a fresh one.
        """
        current_pid = os.getpid()
        if current_pid != self._pid:
            try:
                # Dispose inherited connections safely
                self.engine.dispose()
            except Exception:
                pass
            # Recreate a brand-new engine for this process
            self.engine = olab_create_new_engine()
            self._pid = current_pid
    
    def _cleanup_connections(self):
        """Clean up idle connections"""
        current_time = time.time()
        if current_time - self.last_cleanup > self.cleanup_interval:
            try:
                import gc
                gc.collect()
                self.last_cleanup = current_time
            except Exception as e:
                logging.error(f"Connection cleanup error: {e}")
    
    def _get_connection_with_retry(self, max_retries=3, retry_delay=1):
        """Get database connection with retry logic"""
        for attempt in range(max_retries):
            try:
                self._ensure_engine()
                self._cleanup_connections()
                return self.engine.connect()
            except Exception as e:
                if "too many clients" in str(e).lower():
                    print(f"🔄 Connection pool exhausted, attempt {attempt + 1}/{max_retries}")
                    self._cleanup_connections()
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    raise e
        raise Exception("Failed to get database connection after retries")

    def fetch_dataframe(self, sql_query, params=None):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                with self._get_connection_with_retry() as conn:
                    return pd.read_sql(text(optimized_query), conn, params=params)
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Fetch Error", 'fetch_dataframe')
            print(f"❌ SQL Fetch Error: {e}")
            return pd.DataFrame()

    def execute(self, sql_query, params=None, autocommit=False):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                cleaned_params = olab_clean_timestamp_values(params or {})
                with self._get_connection_with_retry() as conn:
                    if autocommit:
                        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                    result = conn.execute(text(optimized_query), cleaned_params)
                    return result.rowcount
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Execute Error", 'execute')
            print(f"❌ SQL Execute Error: {e}")
            return 0

    def execute_many(self, sql_query, param_list, autocommit=False):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                cleaned_param_list = [olab_clean_timestamp_values(params) for params in param_list]
                with self._get_connection_with_retry() as conn:
                    if autocommit:
                        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                    conn.execute(text(optimized_query), cleaned_param_list)
            return True
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Executemany Error", 'execute_many')
            print(f"❌ SQL Executemany Error: {e}")
            return False

    def fetch_one(self, sql_query, params=None):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                with self._get_connection_with_retry() as conn:
                    return conn.execute(text(optimized_query), params or {}).fetchone()
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Fetch One Error", 'fetch_one')
            print(f"❌ SQL Fetch One Error: {e}")
            return None

    def fetch_all(self, sql_query, params=None):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                with self._get_connection_with_retry() as conn:
                    return conn.execute(text(optimized_query), params or {}).fetchall()
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Fetch All Error", 'fetch_all')
            print(f"❌ SQL Fetch All Error: {e}")
            return []

    def fetch_all_safe(self, sql_query, params=None, timeout=5, retries=3, delay=1, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    with self._get_connection_with_retry() as conn:
                        result = conn.execution_options(timeout=timeout).execute(text(optimized_query), params or {}).fetchall()
                        if attempt > 1:
                            print(f"✅ SQL FetchAll succeeded on attempt {attempt} | Tag: {tag}")
                        return result
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL FetchAll Error Try {attempt}", tag)
                print(f"❌ SQL FetchAll Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                if attempt < retries:
                    print(f"⏳ Waiting {delay} seconds before retry...")
                    time.sleep(delay)
                    delay *= 1.5
        print(f"🛑 SQL FetchAll FAILED after {retries} tries | Tag: {tag}")
        return []

    def fetch_one_safe(self, sql_query, params=None, timeout=5, retries=1, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    with self._get_connection_with_retry() as conn:
                        return conn.execution_options(timeout=timeout).execute(text(optimized_query), params or {}).fetchone()
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL FetchOne Error Try {attempt}", tag)
                print(f"❌ SQL FetchOne Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                time.sleep(delay)
        print(f"🛑 SQL FetchOne FAILED after {retries} tries | Tag: {tag}")
        return None

    def execute_safe(self, sql_query, params=None, autocommit=False, timeout=5, retries=3, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    # Clean parameters including boolean conversion
                    cleaned_params = olab_clean_timestamp_values(params) if params else {}
                    with self._get_connection_with_retry() as conn:
                        if autocommit:
                            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                        conn.execution_options(timeout=timeout).execute(text(optimized_query), cleaned_params)
                return True
            except Exception as e:
                # olab_log_db_error(e, f"❌ SQL Execute Error Try {attempt}", tag)
                print(f"❌ SQL Execute Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                time.sleep(delay)
        print(f"🛑 SQL Execute FAILED after {retries} tries | Tag: {tag}")
        return False

    def execute_in_transaction(self, steps, timeout=10, retries=2, delay=1, tag="transaction"):
        """Run multiple (sql_query, params) steps in one transaction. Commit only if all succeed; rollback on any failure."""
        for attempt in range(1, retries + 1):
            conn = None
            trans = None
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    conn = self._get_connection_with_retry()
                    trans = conn.begin()
                    for sql_query, params in steps:
                        optimized = olab_optimize_sql_query(sql_query)
                        cleaned = olab_clean_timestamp_values(params or {})
                        conn.execute(text(optimized), cleaned)
                    trans.commit()
                    return True
            except Exception as e:
                if trans is not None:
                    try:
                        trans.rollback()
                    except Exception:
                        pass
                print(f"❌ Transaction error (attempt {attempt}/{retries}) | Tag: {tag} | Error: {e}")
                olab_log_db_error(e, f"execute_in_transaction attempt {attempt}", tag)
                if attempt < retries:
                    time.sleep(delay)
                    delay *= 1.5
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        print(f"🛑 Transaction FAILED after {retries} tries | Tag: {tag}")
        return False

    def execute_many_safe(self, sql_query, param_list, autocommit=False, timeout=5, retries=2, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    # Clean parameters including boolean conversion
                    cleaned_param_list = [olab_clean_timestamp_values(params) for params in param_list]
                    with self._get_connection_with_retry() as conn:
                        if autocommit:
                            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                        conn.execution_options(timeout=timeout).execute(text(optimized_query), cleaned_param_list)
                return True
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL ExecuteMany Error Try {attempt}", tag)
                print(f"❌ SQL ExecuteMany Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                time.sleep(delay)
        print(f"🛑 SQL ExecuteMany FAILED after {retries} tries | Tag: {tag}")
        return False

sql_helper = SQLAccessHelper(engine)

def olab_switch_api_key():
    global current_api_index, client
    current_api_index = (current_api_index + 1) % len(API_KEYS)
    creds = API_KEYS[current_api_index]
    client = UMFutures(key=creds['api_key'], secret=creds['api_secret'])
    
    # Setup header capture for the new client
    olab_setup_header_capture(client)
    
    print(f"🔁 Switched API key to {current_api_index}")

# --- Logger ---
def olab_log_db_error(error, context, pair):
    error_message = f"Error in {context}: {error}"
    # Safely extract line number from traceback, handle missing/empty traceback
    if error.__traceback__:
        tb_list = traceback.extract_tb(error.__traceback__)
        if tb_list:
            line_number = tb_list[-1].lineno
        else:
            line_number = None
    else:
        line_number = None
    # Use 'N/A' if line_number is None
    line_number_str = str(line_number) if line_number is not None else 'N/A'
    full_trace = traceback.format_exc()

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    log_dir = "logs_error"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "db_error_log.txt")

    with open(log_file, 'a', encoding="utf-8") as f:
        f.write("Main Machine--Error:\n")
        f.write(f"Time: {current_time}\n")
        f.write(f"{'='*40}\n")
        f.write(f"Pair: {pair}\n")
        f.write(f"Context: {context}\n")
        f.write(f"Error: {error}\n")
        f.write(f"Line Number: {line_number_str}\n")
        f.write("Traceback:\n")
        f.write(full_trace)
        f.write(f"{'='*40}\n\n")

def olab_write_db_insert_debug_log(message):
    """Write DB insert debug info to log_event/db_insert_debug.log with UTC timestamp."""
    log_file = os.path.join(os.path.dirname(__file__), '..', 'log_event', 'db_insert_debug.log')
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")

# --- Utility Functions ---
def olab_table_exists(symbol, interval):
    try:
        # PostgreSQL syntax for checking table existence
        sql = f"""
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_name = 'kline_{symbol.lower()}_{interval}'
        """
        result = sql_helper.fetch_one(sql)
        return result[0] > 0 if result else False
    except Exception as e:
        olab_log_db_error(e, "❌  olab_table_exists Error for", symbol)            
        print(f"❌ olab_table_exists Error for {symbol}-{interval}: {e}")
        return False

def olab_is_data_up_to_date(symbol, interval):
    cache_key = f"{symbol}-{interval}"

    try:
        if not olab_table_exists(symbol, interval):
            return False

        sql = f"SELECT MAX(time) FROM kline_{symbol.lower()}_{interval}"
        row = sql_helper.fetch_one(sql)
        latest_time_db = row[0] if row and row[0] else None
        if not latest_time_db:
            return False

        now = int(time.time() * 1000)
        interval_ms = INTERVAL_MS[interval]
        expected_time = now - (now % interval_ms)

        # Convert latest_time_db to milliseconds if it's a datetime object
        if hasattr(latest_time_db, 'timestamp'):
            latest_time_ms = int(latest_time_db.timestamp() * 1000)
        else:
            latest_time_ms = latest_time_db

        result = latest_time_ms >= expected_time - interval_ms

        # Update cache when database is accessible
        if result:
            data_cache[cache_key] = {
                'last_updated': now,
                'is_up_to_date': True
            }

        return result

    except Exception as e:
        olab_log_db_error(e, "❌  olab_is_data_up_to_date Error for", symbol)
        print(f"❌ olab_is_data_up_to_date Error for {symbol}-{interval}: {e}")

        # Use cache as fallback when database is down
        if cache_key in data_cache:
            cached_data = data_cache[cache_key]
            cache_age = now - cached_data['last_updated']
            # Use cached data if it's less than 5 minutes old
            if cache_age < 5 * 60 * 1000:  # 5 minutes in milliseconds
                print(f"📋 Using cached data for {symbol}-{interval} (age: {cache_age/1000:.1f}s)")
                return cached_data['is_up_to_date']

        return False

def olab_fetch_data_from_db(symbol, interval, limit):
    try:
        # PostgreSQL syntax: LIMIT instead of TOP
        sql = f"SELECT * FROM kline_{symbol.lower()}_{interval} ORDER BY time DESC LIMIT {limit}"
        df = sql_helper.fetch_dataframe(sql)

        if df.empty:
            return df

        # The time column is already a proper timestamp, no need to convert from milliseconds
        df['time'] = pd.to_datetime(df['time'], utc=True)
        df = df.rename(columns={
            'open': 'open', 'high': 'high', 'low': 'low',
            'close': 'close', 'volume': 'volume', 'quotevolume': 'quote_volume',
            'numtrades': 'num_trades', 'takerbuybasevolume': 'taker_base_vol', 'takerbuyquotevolume': 'taker_quote_vol'
        })
        return df[::-1]

    except Exception as e:
        olab_log_db_error(e, "❌  olab_fetch_data_from_db Error for", symbol)   
        print(f"❌ olab_fetch_data_from_db Error for {symbol}-{interval}: {e}")
        return pd.DataFrame()

# --- INSERT KLINES (PostgreSQL compatible) ---
def olab_insert_klines(symbol, interval, klines):
    try:
        table_name = f"kline_{symbol.lower()}_{interval}"
        records = []
        for k in klines:
            records.append({
                "time": k[0], "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                "close": float(k[4]), "volume": float(k[5]), "closetime": k[6], "quotevolume": float(k[7]),
                "numtrades": int(k[8]), "takerbuybasevolume": float(k[9]), "takerbuyquotevolume": float(k[10])
            })

        # PostgreSQL syntax: INSERT ... ON CONFLICT instead of WHERE NOT EXISTS
        sql = f"""
        INSERT INTO {table_name} (time, open, high, low, close, volume, closetime, quotevolume, numtrades, takerbuybasevolume, takerbuyquotevolume)
        VALUES (to_timestamp(:time/1000.0), :open, :high, :low, :close, :volume, :closetime, :quotevolume, :numtrades, :takerbuybasevolume, :takerbuyquotevolume)
        ON CONFLICT (time) DO NOTHING
        """

        sql_helper.execute_many(sql, records, autocommit=True)
        # print(f"✅ Successfully inserted klines for {symbol}-{interval}")
    except Exception as e:
        olab_log_db_error(e, "❌ Insert Klines Error for", symbol)
        print(f"❌ Insert Klines Error for {symbol}-{interval}: {e}")

def olab_insert_or_update_pair_status(pair_status_data):
    try:
        # PostgreSQL syntax: INSERT ... ON CONFLICT instead of MERGE
        sql = """
        INSERT INTO pairstatus (pair, tf_1d_trend, tf_4h_trend, tf_1h_trend, daily_change, henkin_daily_change, fourh_change, status1d_4h, 
                status4h_1h, candle_time, last_updated, Last_day_close_price, squeeze, squeeze_value, active_squeeze, active_squeeze_trend)
        VALUES (:pair, :tf_1d_trend, :tf_4h_trend, :tf_1h_trend, :daily_change, :henkin_daily_change, :fourh_change, :status1d_4h, 
        :status4h_1h, :candle_time, :last_updated, :last_day_close_price, :squeeze, :squeeze_value, :active_squeeze, :active_squeeze_trend)
        ON CONFLICT (pair) DO UPDATE SET
            tf_1d_trend = EXCLUDED.tf_1d_trend,
            tf_4h_trend = EXCLUDED.tf_4h_trend,
            tf_1h_trend = EXCLUDED.tf_1h_trend,
            daily_change = EXCLUDED.daily_change,
            henkin_daily_change = EXCLUDED.henkin_daily_change,
            fourh_change = EXCLUDED.fourh_change,
            status1d_4h = EXCLUDED.status1d_4h,
            status4h_1h = EXCLUDED.status4h_1h,
            candle_time = EXCLUDED.candle_time,
            last_updated = EXCLUDED.last_updated,
            Last_day_close_price = EXCLUDED.Last_day_close_price,
            squeeze = EXCLUDED.squeeze,
            squeeze_value = EXCLUDED.squeeze_value,
            active_squeeze = EXCLUDED.active_squeeze,
            active_squeeze_trend = EXCLUDED.active_squeeze_trend
        """

        sql_helper.execute_many(sql, pair_status_data, autocommit=True)
    except Exception as e:
        olab_log_db_error(e, "❌ Insert PairStatus Error", "n/a")
        print(f"❌ Insert PairStatus Error: {e}")

def olab_get_existing_pair_symbols():
    try:
        sql = "SELECT pair, active_squeeze_trend FROM pairstatus ORDER BY volume_1h DESC "
        rows = sql_helper.fetch_all(sql)  # Ensure this returns a list of tuples
        return {row[0]:row[1] for row in rows if row and row[0]}  # Safeguard against None
    except Exception as e:
        olab_log_db_error(e, "❌ Select olab_get_existing_pair_symbols Error", "n/a")
        return set()

def olab_tradeexistdb(symbol, tf):
    """
    Check if a running trade exists in the database for the given symbol and timeframe.
    
    Parameters:
    - symbol: Trading symbol (e.g., 'BTCUSDT')
    - tf: Timeframe (e.g., '1m', '5m')
    
    Returns:
    - True if a running trade exists; False otherwise.
    """
    try:
        # Use named parameters (:Pair, :Interval) in SQL query
        sql = "SELECT pair FROM alltraderecords WHERE type = 'running' AND pair = :Pair AND interval = :Interval"
        
        # Fetch one row; returns None if no result
        result = sql_helper.fetch_one(sql, {'Pair': symbol, 'Interval': tf})
        
        # Check if a result was found
        if result:
            return True
        else:
            return False

    except Exception as e:
        # Log error and return False
        olab_log_db_error(e, "❌ olab_get_running_symbols Error", 'vv')
        print(f"❌ olab_get_running_symbols Error: {e}")
        return False

def olab_fetch_active_pairs_from_db():
    try:
        sql = """
            SELECT pair, status1d_4h, status4h_1h, Last_day_close_price, tf_1d_trend
            FROM pairstatus 
            WHERE status1d_4h IN ('bullish', 'bearish') 
               OR status4h_1h IN ('bullish', 'bearish')
        """
        results = sql_helper.fetch_all(sql)
        # Return a list of dictionaries with fields accessed by index
        return [{'pair': row[0], 'status1d_4h': row[1], 'status4h_1h': row[2], 'Last_day_close_price': row[3], 'tf_1d_trend': row[4]} for row in results]
    except Exception as e:
        olab_log_db_error(e, "olab_fetch_active_pairs_from_db", "DB Query")
        return []

def olab_fetch_price_precision_from_db(pair):
    try:
        sql = """
            SELECT price_precision
            FROM pairstatus 
            WHERE pair = :pair
        """
        result = sql_helper.fetch_one(sql, {'pair': pair})
        if result:
            return result[0]  # Or adjust if fetch_one returns dict: result['price_precision']
        else:
            olab_log_db_error(Exception(f"No price_precision found for {pair}"), 'olab_fetch_price_precision_from_db', f"Fallback to default precision")
            return 4
    except Exception as e:
        olab_log_db_error(e, "olab_fetch_price_precision_from_db", pair)
        return 4

def olab_fetch_qty_precision_from_db(pair):
    try:
        sql = """
            SELECT quantity_precision
            FROM pairstatus
            WHERE pair = :pair
        """

        # Make sure the pair is uppercase and properly passed
        result = sql_helper.fetch_one(sql, {'pair': pair.upper()})

        if result:
            return result[0]
        else:
            olab_log_db_error(Exception(f"No quantity_precision found for {pair}"), 'olab_fetch_qty_precision_from_db', f"Fallback to default")
            return 0
    except Exception as e:
        olab_log_db_error(e, "olab_fetch_qty_precision_from_db", pair)
        return 0

def olab_fetch_single_pair_from_db(pair):
    """
    Fetch a single pair from the PairStatus table.
    Returns a dictionary with all relevant fields, including active_squeeze_trend.
    """
    try:
        sql = """
            SELECT pair, status1d_4h, status4h_1h, Last_day_close_price, tf_1d_trend, squeeze_value, 
            active_squeeze, active_squeeze_trend, squeeze, overall_trend_RC, overall_trend_percentage_RC, 
            overall_trend_HC, overall_trend_percentage_HC, overall_trend_4h, overall_trend_percentage_4h,
            overall_trend_1h, overall_trend_percentage_1h, volume_1h
            FROM pairstatus WHERE pair = :pair
        """
        result = sql_helper.fetch_one(sql, {'pair': pair})
        if result:
            return {
                'pair': result[0],
                'status1d_4h': result[1],
                'status4h_1h': result[2],
                'Last_day_close_price': result[3],
                'tf_1d_trend': result[4],
                'squeeze_value': result[5],
                'active_squeeze': result[6],
                'active_squeeze_trend': result[7],
                'squeeze': result[8],
                'overall_trend_RC': result[9],
                'overall_trend_percentage_RC': result[10],
                'overall_trend_HC': result[11],
                'overall_trend_percentage_HC': result[12],
                'overall_trend_4h': result[13],
                'overall_trend_percentage_4h': result[14],
                'overall_trend_1h': result[15],
                'overall_trend_percentage_1h': result[16],
                'volume_1h': result[17]
            }
        return None
    except Exception as e:
        olab_log_db_error(e, "olab_fetch_single_pair_from_db", pair)
        return None

# --- Fetch Data Safe (From DB or Binance if outdated) ---
def olab_fetch_data_safe(symbol, interval, limit):
    """
    Fetch data with smart weight tracking that monitors Binance usage
    """
    try:
        # 1. Check if data is up to date in DB first
        if olab_is_data_up_to_date(symbol, interval):
            # print(f"✅ Fetching {symbol}-{interval} from database")
            df = olab_fetch_data_from_db(symbol, interval, limit)
            # Update cache on successful database fetch
            if df is not None and not df.empty:
                cache_key = f"{symbol}-{interval}"
                data_cache[cache_key] = {
                    'last_updated': int(time.time() * 1000),
                    'is_up_to_date': True
                }
            return df

        # 2. Check weight usage before making API call
        if not olab_can_make_api_call():
            print(f"⚠️ Weight limit reached, returning None for {symbol}-{interval}")
            olab_log_weight_limit_reached(symbol, interval, weight_tracker['current_weight'])
            return None

        # 3. Apply basic rate limiting
        binance_limiter.acquire()

        # 4. Make API call
        print(f"🌐 Making API call for {symbol}-{interval}")
        klines = client.klines(symbol=symbol, interval=interval, limit=limit)
        
        # 5. Update weight from response headers
        olab_update_weight_from_headers(symbol,interval)
        
        # 6. Process the data
        clean_klines = [k[:-1] for k in klines]
        closed_klines = clean_klines[:-1] if len(clean_klines) > 1 else []

        if not closed_klines:
            print(f"⛔ No candles fetched for {symbol}-{interval}")
            return None

        df = pd.DataFrame(closed_klines, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'num_trades', 'taker_base_vol', 'taker_quote_vol'
        ])

        for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_base_vol', 'taker_quote_vol']:
            df[col] = pd.to_numeric(df[col])

        df['num_trades'] = df['num_trades'].astype(int)
        df['time'] = pd.to_datetime(df['time'], unit='ms', utc=True)

        result_df = df[['time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'num_trades', 'taker_base_vol', 'taker_quote_vol']]
        
        # ✅ Immediate database insertion (no queue)
        try:
            olab_insert_klines(symbol, interval, closed_klines)
        except Exception as e:
            print(f"❌ Immediate insert failed for {symbol}-{interval}: {e}")

        return result_df

    except Exception as e:
        error_str = str(e)
        
        # Handle 429 errors specifically
        if "429" in error_str or "Too many requests" in error_str:
            print(f"🚨 429 error in olab_fetch_data_safe for {symbol}-{interval}: {e}")
            olab_log_api_limit_error(symbol, interval, error_str)
            return None
        else:
            # Other errors
            olab_log_db_error(e, "❌ olab_fetch_data_safe Error for", symbol)
            print(f"❌ olab_fetch_data_safe Error for {symbol}-{interval}: {e}")
            olab_switch_api_key()
            return None

def olab_fetch_data_safe_for_machines(symbol, interval, limit):
    try:
        # 1. Check if data is up to date in DB first
        if olab_is_data_up_to_date(symbol, interval):
            # print(f"✅ Fetching {symbol}-{interval} from database (machines)")
            return olab_fetch_data_from_db(symbol, interval, limit)

        # 2. Check weight usage before making API call
        if not olab_can_make_api_call():
            print(f"⚠️ Weight limit reached, returning None for {symbol}-{interval}")
            olab_log_weight_limit_reached(symbol, interval, weight_tracker['current_weight'])
            return None

        # 3. Apply basic rate limiting
        binance_limiter.acquire()

        # 4. Make API call
        print(f"🌐 Making API call for {symbol}-{interval} (machines)")
        klines = client.klines(symbol=symbol, interval=interval, limit=limit)

        # 5. Update weight from response headers
        olab_update_weight_from_headers(symbol,interval)

        # 6. Process the data
        clean_klines = [k[:-1] for k in klines]
        closed_klines = clean_klines[:-1] if len(clean_klines) > 1 else []

        if not closed_klines:
            print(f"⛔ No candles fetched for {symbol}-{interval}")
            return None

        df = pd.DataFrame(closed_klines, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'num_trades', 'taker_base_vol', 'taker_quote_vol'
        ])

        for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_base_vol', 'taker_quote_vol']:
            df[col] = pd.to_numeric(df[col])

        df['num_trades'] = df['num_trades'].astype(int)
        df['time'] = pd.to_datetime(df['time'], unit='ms', utc=True)

        result_df = df[['time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'num_trades', 'taker_base_vol', 'taker_quote_vol']]
        
        # ✅ Immediate database insertion (no queue)
        try:
            olab_insert_klines(symbol, interval, closed_klines)
        except Exception as e:
            print(f"❌ Immediate insert failed for {symbol}-{interval}: {e}")

        return result_df

    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "Too many requests" in error_str:
            print(f"🚨 429 error in olab_fetch_data_safe_for_machines for {symbol}-{interval}: {e}")
            olab_log_api_limit_error(symbol, interval, error_str)
            return None
        else:
            olab_log_db_error(e, "❌ olab_fetch_data_safe_for_machines Error for", symbol)
            print(f"❌ olab_fetch_data_safe_for_machines Error for {symbol}-{interval}: {e}")
            olab_switch_api_key()
            return None

# --- Fetch Running Symbols ---
def olab_get_running_symbols():
    try:
        sql = "SELECT pair FROM alltraderecords WHERE type = 'running'"
        rows = sql_helper.fetch_all(sql)
        return [row[0] for row in rows]
    except Exception as e:
        olab_log_db_error(e, "❌ olab_get_running_symbols Error", 'vv')   
        print(f"❌ olab_get_running_symbols Error: {e}")
        return []

# --- Fetch Data From Machine ---
def olab_fetch_data_from_machine(machine_id, app_start):
    try:
  
        # query = f"SELECT * FROM {machine_id.lower()} WHERE (type = 'assign' OR type = 'running') and hedge = '0' "
        # if not app_start:
        #     query = f"SELECT * FROM {machine_id.lower()} WHERE (type = 'assign' OR type = 'running') and hedge = '0' "
        #     print(f'query: {query}')

        query = f"SELECT * FROM {machine_id.lower()} WHERE (type = 'assign' OR type = 'running' \
              OR type = 'hedge_close'  OR type = 'hedge_hold') and hedge = '0' "
        if not app_start:
            query = f"SELECT * FROM {machine_id.lower()} WHERE (type = 'assign' OR type = 'running'  \
                OR type = 'hedge_close'  OR type = 'hedge_hold') and hedge = '0' "        

        rows = sql_helper.fetch_all_safe(query, tag=machine_id)

        # If no rows, return empty list
        if not rows:
            return []

        # Get columns dynamically
        columns_query = f"SELECT column_name FROM information_schema.columns WHERE table_name = '{machine_id.lower()}'"
        columns_data = sql_helper.fetch_all(columns_query)
        columns = [col[0] for col in columns_data]

        # Convert rows to list of dicts
        result = [dict(zip(columns, row)) for row in rows]
        return result

    except Exception as e:
        olab_log_db_error(e, "❌ olab_fetch_data_from_machine Error for", machine_id)   
        print(f"❌ olab_fetch_data_from_machine Error for {machine_id}: {e}")
        return []

def olab_fetch_hedge_data_from_machine(machine_id, app_start):
    try:
        #print(f"🔍 olab_fetch_hedge_data_from_machine called for {machine_id}, app_start={app_start}")
        
        # First check if table exists
        table_check_query = f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{machine_id.lower()} "
        olab_table_exists_result = sql_helper.fetch_one_safe(table_check_query, tag=f"{machine_id}_table_check")
        
        if not olab_table_exists_result or olab_table_exists_result[0] == 0:
            print(f"⚠️ Table {machine_id} does not exist")
            return []

        # Test different query variations to handle data type issues
        queries_to_try = []
        
        if not app_start:
            # For non-app_start, try different variations
            queries_to_try = [f"SELECT * FROM {machine_id.lower()} WHERE (type = 'running' or type = 'hedge_release') AND hedge = 1 AND hedge_1_1_bool = 0 "]
        else:
            # For app_start, try different variations
            queries_to_try = [f"SELECT * FROM {machine_id.lower()} WHERE type = 'hedge_release'"]

        rows = None
        successful_query = None
        
        # Try each query variation
        for i, query in enumerate(queries_to_try):
            try:
                #print(f"🔍 Trying query variation {i+1}: {query}")
                rows = sql_helper.fetch_all_safe(query, tag=f"{machine_id}_variation_{i}")
                
                if rows is not None and len(rows) > 0:
                    successful_query = query
                 #   print(f"✅ Query variation {i+1} successful: {len(rows)} rows")
                    break
                    
            except Exception as query_error:
                print(f"❌ Query variation {i+1} failed: {query_error}")
                continue

        if not rows:
            
            return []

      #  print(f"📊 Final query returned {len(rows)} rows for {machine_id}")
       # print(f"📋 Successful query: {successful_query}")

        # Get columns dynamically
        columns_query = f"SELECT column_name FROM information_schema.columns WHERE table_name = '{machine_id.lower()}'"
        columns_data = sql_helper.fetch_all(columns_query)
        
        if not columns_data:
            print(f"⚠️ Could not get column information for table {machine_id}")
            return []
            
        columns = [col[0] for col in columns_data]
       # print(f"📋 Columns found for {machine_id}: {columns}")

        # Convert rows to list of dicts with better error handling
        result = []
        for i, row in enumerate(rows):
            try:
                row_dict = dict(zip(columns, row))
                
                # Log the first few rows for debugging
                if i < 3:
                    print(f"📋 Sample row {i+1}: Type={row_dict.get('type')}, hedge={row_dict.get('hedge')}, hedge_1_1_bool={row_dict.get('hedge_1_1_bool')}")
                
                result.append(row_dict)
            except Exception as row_error:
                print(f"⚠️ Error processing row {i} for {machine_id}: {row_error}")
                print(f"📋 Row data: {row}")
                continue

       # print(f"✅ Successfully processed {len(result)} records for {machine_id}")
        return result

    except Exception as e:
        olab_log_db_error(e, "❌ olab_fetch_hedge_data_from_machine Error for", machine_id)   
        print(f"❌ olab_fetch_hedge_data_from_machine Error for {machine_id}: {e}")
        print(f"📋 Full traceback: {traceback.format_exc()}")
        return []

# --- Assign Trade To Machine ---
def _olab_assign_trade_to_machine(df, symbol, interval, stopPrice, action, signalFrom, closes3,min_profit,invest, candle_type=None):
    try:
        if closes3 is None:
            closes3 = []
        rows = sql_helper.fetch_all("""
            SELECT m.machineid, mtc.totaltradecounter
            FROM machines m
            INNER JOIN machinetradecount mtc ON m.machineid = mtc.machineid
            WHERE m.active = 1 AND mtc.declinecounter < 5
            ORDER BY mtc.totaltradecounter ASC, m.machineid ASC
            LIMIT 1
        """)

        if not rows:
            return None, "No active machine available"

        for row in rows:
            _machineId = row[0]
            if candle_type == 'BT':
                _machineId = 'M9'
            time_now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            candel_time = str(df.index[-1])
            unique_id_parts = [symbol, action, candel_time, str(signalFrom)]
            if candle_type:
                unique_id_parts.append(str(candle_type))
            unique_id_parts = [str(x) if x is not None else 'UNKNOWN' for x in unique_id_parts]
            unique_id = "".join(unique_id_parts)

            try:
                dt = parser.parse(candel_time)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc)
                else:
                    dt = dt.replace(tzinfo=timezone.utc)
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                olab_log_db_error(e, f"Error parsing timestamp for {candel_time}", symbol)
                return unique_id, f"Error parsing timestamp: {e}"

            try:
                exists_query = """
                    SELECT pair FROM alltraderecords
                    WHERE pair = :pair AND action = :action AND signalfrom = :signalFrom
                          AND interval = :interval AND type NOT IN ('close', 'hedge_close','hedge_hold','hedge_release') AND hedge = 0
                """
                check_params = {"pair": symbol, "action": action, "signalFrom": signalFrom, "interval": interval}
                result = sql_helper.fetch_all(exists_query, check_params)

                exists_uid = """
                    SELECT pair FROM alltraderecords
                    WHERE unique_id = :unique_id
                """
                check_params = {"unique_id": unique_id}
                result_uid = sql_helper.fetch_all(exists_uid, check_params)

                if result or result_uid:
                    msg = f"Record already found for {unique_id}. Skipping insert."
                    print(msg)
                    return unique_id, msg
            except Exception as e:
                olab_log_db_error(e, f"Error checking for existing records: {e}", symbol)
                return unique_id, f"Error checking for existing records: {e}"

            _tradeCounter = (row[1] or 0) + 1
            last_close = df['close'].iloc[-1]

            swing_multiplier = 1 if action == "BUY" else -1

                        # Normalize closes3 so it is always a list (length 0..3)
            if closes3 is None:
                closes3 = []
            elif isinstance(closes3, (int, float)):
                closes3 = [closes3]
            else:
                # if it's something iterable like list/tuple/np array, make it a list
                try:
                    closes3 = list(closes3)
                except TypeError:
                    closes3 = [closes3]

            swing1 = closes3[0] if len(closes3) >= 1 and closes3[0] is not None else last_close + (last_close * 0.00015 * swing_multiplier)
            swing2 = closes3[1] if len(closes3) >= 2 and closes3[1] is not None else swing1 + (swing1 * 0.0002 * swing_multiplier)
            swing3 = closes3[2] if len(closes3) >= 3 and closes3[2] is not None else swing2 + (swing2 * 0.0003 * swing_multiplier)

            document = {
                "machineid": _machineId, "unique_id": unique_id, "candel_time": formatted_time,
                "fetcher_trade_time": time_now, "operator_trade_time": "NONE", "operator_close_time": "NONE",
                "pair": symbol, "investment": invest, "interval": interval, "stop_price": stopPrice,
                "save_price": 0, "min_comm": 0, "hedge": 0, "action": action, "buy_qty": 0,
                "buy_price": 0, "buy_pl": 0, "sell_qty": 0, "sell_price": 0, "sell_pl": 0,
                "commission": 0, "pl_after_comm": 0, "close_price": 0, "commision_journey": 0,
                "profit_journey": 0, "min_profit": min_profit, "hedge_order_size": 0, "hedge_1_1_bool": 0,
                "added_qty": 0, "min_comm_after_hedge": 0, "type": "assign", "min_close": "NOT_ACTIVE",
                "signalfrom": signalFrom, "macd_action": 'Active', "swing1": swing1, "swing2": swing2,
                "swing3": swing3, "hedge_swing_high_point": 0, "hedge_swing_low_point": 0,
                "hedge_buy_pl": 0, "hedge_sell_pl": 0, "temp_high_point": 0, "temp_low_point": 0
            }

            columns = list(document.keys())
            success = False
            last_error = None
            
            # Import and apply comprehensive timestamp fix
            from utils.timestamp_fix import apply_timestamp_fix_to_document
            
            # Clean the document data to fix timestamp issues
            cleaned_document = olab_clean_timestamp_values(document)
            # Apply additional timestamp NONE → NULL fix
            fixed_document = apply_timestamp_fix_to_document(cleaned_document)
            
            for attempt in range(1, 2):
                try:
                    # Use the enhanced SQLAccessHelper for better error handling
                    insert_query1 = f"INSERT INTO {_machineId.lower()} ({', '.join(columns)}) VALUES ({', '.join([':' + c for c in columns])})"
                    insert_query2 = f"INSERT INTO alltraderecords ({', '.join(columns)}) VALUES ({', '.join([':' + c for c in columns])})"
                    update_query = "UPDATE machinetradecount SET totaltradecounter = :counter WHERE machineid = :machineId"
                    
                    # Execute all operations with proper error handling using fixed document
                    result1 = sql_helper.execute_safe(insert_query1, fixed_document, autocommit=True, tag=f"insert_{_machineId.lower()}")
                    result2 = sql_helper.execute_safe(insert_query2, fixed_document, autocommit=True, tag="insert_alltraderecords")
                    result3 = sql_helper.execute_safe(update_query, {"counter": _tradeCounter, "machineId": _machineId}, autocommit=True, tag="update_machinetradecount")
                    
                    if result1 and result2 and result3:
                        success = True
                        break
                    else:
                        raise Exception("One or more database operations failed")
                    
                except (IntegrityError, UniqueViolation) as e:
                    # ✅ Duplicate found → exit early, no more retries
                    # olab_log_db_error(e, f"Duplicate detected for {unique_id}, skipping insert", symbol)
                    return unique_id, "Already exists"                    
                        
                except Exception as e:
                    olab_log_db_error(e, f" Attempt : Insert failed for {unique_id}. Error: {e}", symbol)
                    time.sleep(1)
                    last_error = str(e)

            if success:
                return unique_id, None
            else:
                olab_log_db_error(Exception(f"Failed to insert after 100 attempts for {unique_id}"), f"Failed to insert after 100 attempts for {unique_id}", symbol)
                return unique_id, f"Failed to insert after 100 attempts: {last_error if last_error else 'Unknown error'}"

        return None, "No machine row processed"

    except Exception as e:
        olab_log_db_error(e, f"Unhandled error in _olab_assign_trade_to_machine: {e}", symbol)
        return None, f"Unhandled error: {e}"

def olab_AssignTradeToMachineLAB(df, symbol, interval, stopPrice, action, signalFrom, closes3,min_profit,invest, candle_type):
    return _olab_assign_trade_to_machine(df, symbol, interval, stopPrice, action, signalFrom, closes3,min_profit,invest, candle_type)



def _olab_BackTest_assign_trade_to_machine(current_time_4h,exetime,entry_price,quantity,stopPrice,df, symbol, interval,  action, signalFrom, closes3,min_profit, candle_type=None):
    try:
        if closes3 is None:
            closes3 = []
        rows = sql_helper.fetch_all("""
            SELECT m.machineid, mtc.totaltradecounter
            FROM machines m
            INNER JOIN machinetradecount mtc ON m.machineid = mtc.machineid
            WHERE m.active = 1 AND mtc.declinecounter < 5
            ORDER BY mtc.totaltradecounter ASC, m.machineid ASC
            LIMIT 1
        """)

        if not rows:
            return None, "No active machine available"

        for row in rows:
            _machineId = row[0]
            if candle_type == 'BT':
                _machineId = 'M9'
            time_now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            # candel_time = str(df.index[-1])
            time_now = exetime
            candel_time = str(current_time_4h)
            unique_id_parts = [symbol, action, candel_time, str(signalFrom)]
            if candle_type:
                unique_id_parts.append(str(candle_type))
            unique_id_parts = [str(x) if x is not None else 'UNKNOWN' for x in unique_id_parts]
            unique_id = "".join(unique_id_parts)

            try:
                dt = parser.parse(candel_time)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc)
                else:
                    dt = dt.replace(tzinfo=timezone.utc)
                formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                olab_log_db_error(e, f"Error parsing timestamp for {candel_time}", symbol)
                return unique_id, f"Error parsing timestamp: {e}"

            try:
                exists_query = """
                    SELECT pair FROM alltraderecords
                    WHERE pair = :pair AND action = :action AND signalfrom = :signalFrom
                          AND interval = :interval AND type NOT IN ('close', 'hedge_close','hedge_hold','hedge_release') AND hedge = 0
                """
                check_params = {"pair": symbol, "action": action, "signalFrom": signalFrom, "interval": interval}
                result = sql_helper.fetch_all(exists_query, check_params)

                exists_uid = """
                    SELECT pair FROM alltraderecords
                    WHERE unique_id = :unique_id
                """
                check_params = {"unique_id": unique_id}
                result_uid = sql_helper.fetch_all(exists_uid, check_params)

                if result or result_uid:
                    msg = f"Record already found for {unique_id}. Skipping insert."
                    print(msg)
                    return unique_id, msg
            except Exception as e:
                olab_log_db_error(e, f"Error checking for existing records: {e}", symbol)
                return unique_id, f"Error checking for existing records: {e}"

            _tradeCounter = (row[1] or 0) + 1
            last_close = df['close'].iloc[-1]

            swing_multiplier = 1 if action == "BUY" else -1
            # Normalize closes3 so it is always a list (length 0..3)
            if closes3 is None:
                closes3 = []
            elif isinstance(closes3, (int, float)):
                closes3 = [closes3]
            else:
                # if it's something iterable like list/tuple/np array, make it a list
                try:
                    closes3 = list(closes3)
                except TypeError:
                    closes3 = [closes3]
            swing1 = closes3[0] if len(closes3) >= 1 and closes3[0] is not None else last_close + (last_close * 0.00015 * swing_multiplier)
            swing2 = closes3[1] if len(closes3) >= 2 and closes3[1] is not None else swing1 + (swing1 * 0.0002 * swing_multiplier)
            swing3 = closes3[2] if len(closes3) >= 3 and closes3[2] is not None else swing2 + (swing2 * 0.0003 * swing_multiplier)

            if action == 'BUY':

                document = {
                    "machineid": _machineId, "unique_id": unique_id, "candel_time": formatted_time,
                    "fetcher_trade_time": time_now, "operator_trade_time": "NONE", "operator_close_time": "NONE",
                    "pair": symbol, "investment": 500, "interval": interval, "stop_price": stopPrice,
                    "save_price": 0, "min_comm": 0, "hedge": 0, "action": action, "buy_qty": quantity,
                    "buy_price": entry_price, "buy_pl": 0, "sell_qty": 0, "sell_price": 0, "sell_pl": 0,
                    "commission": 0, "pl_after_comm": 0, "close_price": 0, "commision_journey": 0,
                    "profit_journey": 0, "min_profit": min_profit, "hedge_order_size": 0, "hedge_1_1_bool": 0,
                    "added_qty": 0, "min_comm_after_hedge": 0, "type": "assign", "min_close": "NOT_ACTIVE",
                    "signalfrom": signalFrom, "macd_action": 'Active', "swing1": swing1, "swing2": swing2,
                    "swing3": swing3, "hedge_swing_high_point": 0, "hedge_swing_low_point": 0,
                    "hedge_buy_pl": 0, "hedge_sell_pl": 0, "temp_high_point": 0, "temp_low_point": 0
                }

            elif action == 'SELL':

                document = {
                    "machineid": _machineId, "unique_id": unique_id, "candel_time": formatted_time,
                    "fetcher_trade_time": time_now, "operator_trade_time": "NONE", "operator_close_time": "NONE",
                    "pair": symbol, "investment": 500, "interval": interval, "stop_price": stopPrice,
                    "save_price": 0, "min_comm": 0, "hedge": 0, "action": action, "buy_qty": 0,
                    "buy_price": 0, "buy_pl": 0, "sell_qty": quantity, "sell_price": entry_price, "sell_pl": 0,
                    "commission": 0, "pl_after_comm": 0, "close_price": 0, "commision_journey": 0,
                    "profit_journey": 0, "min_profit": min_profit, "hedge_order_size": 0, "hedge_1_1_bool": 0,
                    "added_qty": 0, "min_comm_after_hedge": 0, "type": "assign", "min_close": "NOT_ACTIVE",
                    "signalfrom": signalFrom, "macd_action": 'Active', "swing1": swing1, "swing2": swing2,
                    "swing3": swing3, "hedge_swing_high_point": 0, "hedge_swing_low_point": 0,
                    "hedge_buy_pl": 0, "hedge_sell_pl": 0, "temp_high_point": 0, "temp_low_point": 0
                }

            columns = list(document.keys())
            success = False
            last_error = None
            
            # Import and apply comprehensive timestamp fix
            from utils.timestamp_fix import apply_timestamp_fix_to_document
            
            # Clean the document data to fix timestamp issues
            cleaned_document = olab_clean_timestamp_values(document)
            # Apply additional timestamp NONE → NULL fix
            fixed_document = apply_timestamp_fix_to_document(cleaned_document)
            
            for attempt in range(1, 2):
                try:
                    # Use the enhanced SQLAccessHelper for better error handling
                    insert_query1 = f"INSERT INTO {_machineId.lower()} ({', '.join(columns)}) VALUES ({', '.join([':' + c for c in columns])})"
                    insert_query2 = f"INSERT INTO alltraderecords ({', '.join(columns)}) VALUES ({', '.join([':' + c for c in columns])})"
                    update_query = "UPDATE machinetradecount SET totaltradecounter = :counter WHERE machineid = :machineId"
                    
                    # Execute all operations with proper error handling using fixed document
                    result1 = sql_helper.execute_safe(insert_query1, fixed_document, autocommit=True, tag=f"insert_{_machineId.lower()}")
                    result2 = sql_helper.execute_safe(insert_query2, fixed_document, autocommit=True, tag="insert_alltraderecords")
                    result3 = sql_helper.execute_safe(update_query, {"counter": _tradeCounter, "machineId": _machineId}, autocommit=True, tag="update_machinetradecount")
                    
                    if result1 and result2 and result3:
                        success = True
                        break
                    else:
                        raise Exception("One or more database operations failed")
                    
                except (IntegrityError, UniqueViolation) as e:
                    # ✅ Duplicate found → exit early, no more retries
                    # olab_log_db_error(e, f"Duplicate detected for {unique_id}, skipping insert", symbol)
                    return unique_id, "Already exists"                    
                        
                except Exception as e:
                    olab_log_db_error(e, f" Attempt : Insert failed for {unique_id}. Error: {e}", symbol)
                    time.sleep(1)
                    last_error = str(e)

            if success:
                return unique_id, None
            else:
                olab_log_db_error(Exception(f"Failed to insert after 100 attempts for {unique_id}"), f"Failed to insert after 100 attempts for {unique_id}", symbol)
                return unique_id, f"Failed to insert after 100 attempts: {last_error if last_error else 'Unknown error'}"

        return None, "No machine row processed"

    except Exception as e:
        olab_log_db_error(e, f"Unhandled error in _olab_assign_trade_to_machine: {e}", symbol)
        return None, f"Unhandled error: {e}"

def olab_update_table_BackTest(
    unique_id,
    entry_price,
    quantity,
    invest,
    pl,
    close_time,
    exit_interval,
    close_price,
    tot_comm
):
    try:
        update_query = """
        UPDATE alltraderecords SET 
            buy_qty = :quantity,
            buy_price = :entry_price,
            investment = :invest,
            pl_after_comm = :pl,
            operator_close_time = :close_time,
            interval = :exit_interval,
            close_price = :close_price,
            commission = :tot_comm,
            type = 'back_close'
        WHERE unique_id = :unique_id
        """

        params = {
            "unique_id": unique_id,
            "quantity": quantity,
            "entry_price": entry_price,
            "invest": invest,
            "pl": pl,
            "close_time": close_time,
            "exit_interval": exit_interval,
            "close_price": close_price,
            "tot_comm": tot_comm,
        }

        sql_helper.execute(update_query, params, autocommit=True)

    except Exception as outer_e:
        olab_log_db_error(outer_e, "olab_update_table_BackTest", unique_id)
        print(f"❌ olab_update_table_BackTest Global Error for {unique_id}: {outer_e}")

def get_unclose_back_data():
    try:
        sql = """
            SELECT pair
            FROM alltraderecords 
            where machineid = 'M9' AND
            type='assign'
        """

        rows = sql_helper.fetch_all(sql, )

        if rows:
            # rows could be list of dicts or tuples depending on your helper
            pairs = [r["pair"] if isinstance(r, dict) else r[0] for r in rows]
            return pairs

        return []

    except Exception as e:
        olab_log_db_error(e, "get_unmatch_data", "umatch")
        print(f"❌ get_unmatch_data Error: {e}")
        return []

# --- Update Machine Table From All Pairs ---
def olab_update_table_from_all_pairs(all_pairs, machine_id):
    try:
        if not all_pairs:
            return
        
        # Pre-filter pairs that need updates to avoid unnecessary DB calls
        pairs_to_update = {}
        for uid, item in all_pairs.items():
            if item and item.get('unique_id'):
                # Convert boolean values to integers for PostgreSQL
                converted_item = olab_convert_boolean_to_int(item)
                pairs_to_update[uid] = converted_item
        
        if not pairs_to_update:
            return
        
        # Batch the updates for better performance
        batch_size = 20
        total_updated = 0
        total_errors = 0
        
        pairs_list = list(pairs_to_update.items())
        
        for i in range(0, len(pairs_list), batch_size):
            batch = pairs_list[i:i + batch_size]
            
            try:
                # Process batch with timeout
                batch_start = time.time()
                batch_updated = 0
                batch_errors = 0
                
                for uid, item in batch:
                    try:
                        # Use a more efficient check - only check if we need to update
                        check_query = f"SELECT COUNT(*) FROM {machine_id.lower()} WHERE unique_id = :uid"
                        result = sql_helper.fetch_one(check_query, {"uid": item.get('unique_id')})

                        if result and result[0] > 0:
                            update_query = f"""
                            UPDATE {machine_id.lower()} SET 
                                operator_trade_time=:operator_trade_time, 
                                investment=:investment, 
                                interval=:interval,
                                stop_price=:stop_price, 
                                save_price=:save_price, 
                                min_comm=:min_comm, 
                                hedge=:hedge, 
                                action=:action,
                                buy_qty=:buy_qty, 
                                buy_price=:buy_price, 
                                buy_pl=:buy_pl, 
                                sell_qty=:sell_qty, 
                                sell_price=:sell_price,
                                sell_pl=:sell_pl, 
                                commission=:commission, 
                                pl_after_comm=:pl_after_comm, 
                                commision_journey=:commision_journey,
                                profit_journey=:profit_journey, 
                                min_profit=:min_profit, 
                                hedge_order_size=:hedge_order_size, 
                                hedge_1_1_bool=:hedge_1_1_bool,
                                added_qty=:added_qty, 
                                min_comm_after_hedge=:min_comm_after_hedge, 
                                type=:type, 
                                signalfrom=:signalfrom,
                                operator_close_time=:operator_close_time, 
                                min_close=:min_close, 
                                close_price=:close_price,
                                hedge_swing_high_point =:hedge_swing_high_point,
                                hedge_swing_low_point =:hedge_swing_low_point,
                                hedge_buy_pl =:hedge_buy_pl,
                                hedge_sell_pl =:hedge_sell_pl,
                                temp_high_point =:temp_high_point,
                                temp_low_point =:temp_low_point,
                                updated_at =:updated_at
                            WHERE unique_id=:unique_id AND pair=:pair AND type NOT IN ('close', 'hedge_close')
                            """
                            rows_updated = sql_helper.execute(update_query, item, autocommit=True)
                            if rows_updated > 0:
                                batch_updated += 1
                            else:
                                batch_errors += 1
                                # Only log errors to file for debugging, not console spam
                                with open('log_event/updatedb-error.txt', 'a', encoding="utf-8") as f:  
                                    f.write(f"No update occurred for UID: {uid}\n")
                        else:
                            batch_errors += 1
                            
                    except Exception as e:
                        batch_errors += 1
                        olab_log_db_error(e, "olab_update_table_from_all_pairs", f"UID: {uid}")
                
                batch_time = time.time() - batch_start
                total_updated += batch_updated
                total_errors += batch_errors
                
                # Check for timeout - if batch takes too long, abort
                if batch_time > 60:  # 10 second timeout per batch
                    olab_log_db_error(Exception(f"Batch timeout after {batch_time:.2f}s"), "olab_update_table_from_all_pairs", "batch_timeout")
                    break
                    
            except Exception as batch_e:
                olab_log_db_error(batch_e, "olab_update_table_from_all_pairs", f"Batch {i//batch_size + 1}")
                total_errors += len(batch)
        
        # Final summary
        # if total_updated > 0:
        #     print(f"✅ Update complete: {total_updated} updated, {total_errors} errors")
        # else:
        #     try:
        #         raise Exception(f"Batch timeout after {batch_time:.2f}s")
        #     except Exception as e:
        #         olab_log_db_error(e, "olab_update_table_from_all_pairs", "batch_timeout")

    except Exception as outer_e:
        olab_log_db_error(outer_e, "olab_update_table_from_all_pairs", machine_id)
        print(f"❌ olab_update_table_from_all_pairs Global Error for {machine_id}: {outer_e}")

def olab_convert_boolean_to_int(data_dict):
    """
    Convert boolean values to integers for PostgreSQL compatibility.
    PostgreSQL expects INTEGER (0/1) for boolean columns, not BOOLEAN (True/False).
    """
    converted = {}
    for key, value in data_dict.items():
        if isinstance(value, bool):
            converted[key] = 1 if value else 0
        else:
            converted[key] = value
    return converted

def olab_update_single_uid_in_table(uid, all_pairs, machine_id):
    try:
        item = all_pairs.get(uid)
        if not item:
            print(f"⚠️ UID: {uid} not found in all_pairs")
            return

        # Convert boolean values to integers for PostgreSQL
        converted_item = olab_convert_boolean_to_int(item)

        check_query = f"SELECT COUNT(*) FROM {machine_id.lower()} WHERE unique_id = :uid"
        result = sql_helper.fetch_one(check_query, {"uid": converted_item.get('unique_id')})

        if result and result[0] > 0:
            update_query = f"""
            UPDATE {machine_id.lower()} SET 
                operator_trade_time=:operator_trade_time, 
                investment=:investment, 
                interval=:interval,
                stop_price=:stop_price, 
                save_price=:save_price, 
                min_comm=:min_comm, 
                hedge=:hedge, 
                action=:action,
                buy_qty=:buy_qty, 
                buy_price=:buy_price, 
                buy_pl=:buy_pl, 
                sell_qty=:sell_qty, 
                sell_price=:sell_price,
                sell_pl=:sell_pl, 
                commission=:commission, 
                pl_after_comm=:pl_after_comm, 
                commision_journey=:commision_journey,
                profit_journey=:profit_journey, 
                min_profit=:min_profit, 
                hedge_order_size=:hedge_order_size, 
                hedge_1_1_bool=:hedge_1_1_bool,
                added_qty=:added_qty, 
                min_comm_after_hedge=:min_comm_after_hedge, 
                type=:type, 
                signalfrom=:signalfrom,
                operator_close_time=:operator_close_time, 
                min_close=:min_close, 
                macd_action =:macd_action,
                close_price=:close_price,
                hedge_swing_high_point =:hedge_swing_high_point,
                hedge_swing_low_point =:hedge_swing_low_point,
                hedge_buy_pl =:hedge_buy_pl,
                hedge_sell_pl =:hedge_sell_pl,
                temp_high_point =:temp_high_point,
                temp_low_point =:temp_low_point,
                updated_at =:updated_at
            WHERE unique_id=:unique_id AND pair=:pair AND type NOT IN ('close', 'hedge_close')
            """
            rows_updated = sql_helper.execute(update_query, converted_item, autocommit=True)

            if rows_updated == 0:
                with open('log_event/updatedb-error-single.txt', 'a', encoding="utf-8") as f:
                    f.write(f"No update occurred for UID: {uid}\n")
            else:
                with open('log_event/updatedb.txt', 'a', encoding="utf-8") as f:
                    f.write(f"Updated UID: {uid} | Rows affected: {rows_updated}\n")

        else:
            print(f"⚠️ UID {uid} not found in DB table '{machine_id}'")
            with open('log_event/updatedb-error-single.txt', 'a', encoding="utf-8") as f:
                f.write(f"UID {uid} not found in DB table '{machine_id}'\n")

    except Exception as e:
        olab_log_db_error(e, "olab_update_single_uid_in_table", f"UID: {uid}")
        print(f"❌ Exception during update for UID {uid}: {str(e)}")

        
def olab_update_tmux_log(code):
    try:
        time_now = datetime.now(timezone.utc)
        #print(f"🔄 Updating tmux_log for {code} at {time_now}")

        query = """
            UPDATE tmux_log
            SET last_timestamp = :time_now
            WHERE code = :code
        """
        sql_helper.execute(query, {"time_now": time_now, "code": code}, autocommit=True)

    except Exception as e:
        olab_log_db_error(e, "olab_update_tmux_log", "SQL execution issue")
        print(f"❌ Error updating tmux_log: {e}")

# --- Update All Trade Table ---
def olab_update_all_trade_table():
    try:
        # Dynamically get all active machine tables
        machine_tables_query = "SELECT machineid FROM machines WHERE active = 1"
        machine_rows = sql_helper.fetch_all(machine_tables_query)
        if not machine_rows:
            print("No active machines found. Skipping update.")
            return

        machine_tables = [row[0].lower() for row in machine_rows]
        
        # Construct the UNION ALL part of the query dynamically
        union_all_query = " UNION ALL ".join([f"SELECT * FROM {table}" for table in machine_tables])

        update_query = f"""
        UPDATE alltraderecords AS target
        SET
            operator_trade_time = src.operator_trade_time,
            candel_time = src.candel_time,
            fetcher_trade_time = src.fetcher_trade_time,
            operator_close_time = src.operator_close_time,
            investment = src.investment,
            interval = src.interval,
            stop_price = src.stop_price,
            save_price = src.save_price,
            min_comm = src.min_comm,
            hedge = src.hedge,
            action = src.action,
            buy_qty = src.buy_qty,
            buy_price = src.buy_price,
            buy_pl = src.buy_pl,
            sell_qty = src.sell_qty,
            sell_price = src.sell_price,
            sell_pl = src.sell_pl,
            commission = src.commission,
            pl_after_comm = src.pl_after_comm,
            close_price = src.close_price,
            commision_journey = src.commision_journey,
            profit_journey = src.profit_journey,
            min_profit = src.min_profit,
            hedge_order_size = src.hedge_order_size,
            hedge_1_1_bool = src.hedge_1_1_bool,
            added_qty = src.added_qty,
            min_comm_after_hedge = src.min_comm_after_hedge,
            type = src.type,
            min_close = src.min_close,
            signalfrom = src.signalfrom,
            macd_action = src.macd_action,
            swing1 = src.swing1,
            swing2 = src.swing2,
            swing3 = src.swing3,
            hedge_swing_high_point = src.hedge_swing_high_point,
            hedge_swing_low_point = src.hedge_swing_low_point,
            hedge_buy_pl = src.hedge_buy_pl,
            hedge_sell_pl = src.hedge_sell_pl,
            temp_high_point = src.temp_high_point,
            temp_low_point = src.temp_low_point,
            updated_at = src.updated_at
        FROM alltraderecords AS source
        INNER JOIN (
            {union_all_query}
        ) AS src
        ON source.unique_id = src.unique_id
        WHERE target.unique_id = source.unique_id;
        """

        result = sql_helper.execute(update_query, autocommit=True)
        if result:
            print("✅ Successfully Updated All Trade Table")
        else:
            print("❌ Update failed while updating All Trade Table")

    except Exception as e:
        print(f"❌ Error updating AllTradeRecords: {e}")
        olab_log_db_error(e, "olab_update_all_trade_table", "SQL execution issue")

def olab_insert_bot_error_log(uid, source, message, timestamp, machine_id, json_error=None):
    try:
        query = """
        INSERT INTO boterrorlogs (uid, source, message, timestamp, machineid, json_message)
        VALUES (:uid, :source, :message, :timestamp, :machine_id, :json_message)
        """
        sql_helper.execute(query, {
            "uid": uid,
            "source": source,
            "message": message,
            "timestamp": timestamp,
            "machine_id": machine_id,
            "json_message": json_error
        }, autocommit=True)
    except Exception as e:
        print(f"❌ Failed to insert error log to DB: {e}")
        olab_log_db_error(e, "olab_insert_bot_error_log", "SQL execution issue")

def olab_insert_bot_event_log(uid, source, Pl_after_comm, plain_message, json_message, timestamp, machine_id):
    try:
        if Pl_after_comm is None:
            Pl_after_comm = 0

        query = """
            INSERT INTO bot_event_log (uid, source, pl_after_comm, plain_message, json_message, timestamp, machine_id)
            VALUES (:uid, :source, :pl_after_comm, :plain_message, :json_message, :timestamp, :machine_id)
        """
        sql_helper.execute(query, {
            "uid": uid,
            "source": source,
            "pl_after_comm": Pl_after_comm,
            "plain_message": plain_message,
            "json_message": json_message,
            "timestamp": timestamp,
            "machine_id": machine_id
        }, autocommit=True)
    except Exception as e:
        olab_log_db_error(e, "olab_insert_bot_event_log", "olab_insert_bot_event_log")
        print(f"❌ Failed to insert bot_event_log: {e}")

def olab_insert_system_metrics(cpu_usage, memory_usage, thread_count, machine_id):
    try:
        query = """
            INSERT INTO system_metrics (cpu_usage, memory_usage, thread_count, machine_id)
            VALUES (:cpu, :mem, :threads, :machine)
        """
        sql_helper.execute(query, {
            "cpu": cpu_usage,
            "mem": memory_usage,
            "threads": thread_count,
            "machine": machine_id
        }, autocommit=True)
    except Exception as e:
        olab_log_db_error(e, "olab_insert_system_metrics", "olab_insert_system_metrics")
        print(f"❌ Failed to insert system metrics: {e}")

def olab_update_squeeze_status(pair, squeeze_status, squeeze_value, active_squeeze, active_squeeze_trend):
    """
    Update the squeeze status for a pair in the PairStatus table.
    
    Parameters:
    - pair: Trading pair symbol (e.g., 'BTCUSDT')
    - squeeze_status: Boolean indicating if the pair is in squeeze
    """
    try:
        sql = """
        UPDATE pairstatus 
        SET squeeze = :squeeze_status, squeeze_value = :squeeze_value, last_updated = :last_updated, active_squeeze = :active_squeeze, active_squeeze_trend = :active_squeeze_trend
        WHERE pair = :pair
        """
        
        current_time = datetime.now(timezone.utc)
        params = {
            'pair': pair,
            'squeeze_status': squeeze_status,
            'squeeze_value': squeeze_value,
            'last_updated': current_time,
            'active_squeeze': active_squeeze,
            'active_squeeze_trend': active_squeeze_trend
        }
        
        sql_helper.execute(sql, params, autocommit=True)
        # print(f"✅ Updated squeeze status for {pair}: {squeeze_status}")
        
    except Exception as e:
        olab_log_db_error(e, "❌ Update squeeze status error", pair)
        print(f"❌ Error updating squeeze status for {pair}: {e}")



def olab_fetch_squeezed_pairs_from_db_paginated(offset=0, limit=10):
    """
    Fetch squeezed pairs with pagination support.

    Args:
        offset: Number of records to skip (for pagination)
        limit: Maximum number of records to return

    Returns:
        List of dictionaries containing pair information for squeezed pairs
    """
    try:
        sql = """
            SELECT *
            FROM pairstatus 
            WHERE squeeze = TRUE
            ORDER BY volume_4h DESC
            LIMIT :limit OFFSET :offset
        """
        results = sql_helper.fetch_all_safe(sql, {"offset": offset, "limit": limit})
        if not results:
            return []
        
        # Get columns dynamically
        columns_query = "SELECT column_name FROM information_schema.columns WHERE table_name = 'pairstatus'"
        columns_data = sql_helper.fetch_all_safe(columns_query, tag="pairstatus")
        columns = [col[0] for col in columns_data]

        return [dict(zip(columns, row)) for row in results]        
        
    except Exception as e:
        olab_log_db_error(e, "olab_fetch_squeezed_pairs_from_db_paginated", "DB Query")
        return []


def olab_fetch_non_squeezed_pairs_from_db():
    try:
        sql = "SELECT * FROM pairstatus WHERE squeeze = FALSE OR squeeze IS NULL and pair='anish'  LIMIT 1"
        #sql = "SELECT * FROM pairstatus WHERE squeeze = FALSE  and pair='anish'  LIMIT 1"

        rows = sql_helper.fetch_all_safe(sql, tag="pairstatus")
        if not rows:
            return []

        # Get columns dynamically
        columns_query = "SELECT column_name FROM information_schema.columns WHERE table_name = 'pairstatus'"
        columns_data = sql_helper.fetch_all_safe(columns_query, tag="pairstatus")
        columns = [col[0] for col in columns_data]

        return [dict(zip(columns, row)) for row in rows]

    except Exception as e:
        olab_log_db_error(e, "olab_fetch_non_squeezed_pairs_from_db", "DB Query")
        return []


def olab_fetch_squeezed_pairs_from_db():
    try:
        sql = "SELECT * FROM pairstatus WHERE squeeze = TRUE "
        rows = sql_helper.fetch_all_safe(sql, tag="pairstatus")
        if not rows:
            return []

        # Get columns dynamically
        columns_query = "SELECT column_name FROM information_schema.columns WHERE table_name = 'pairstatus'"
        columns_data = sql_helper.fetch_all_safe(columns_query, tag="pairstatus")
        columns = [col[0] for col in columns_data]

        return [dict(zip(columns, row)) for row in rows]

    except Exception as e:
        olab_log_db_error(e, "fetch_squeezed_pairs_from_db", "DB Query")
        return []



        
def olab_fetch_non_squeezed_pairs_from_db_paginated(offset=0, limit=10):
    """
    Fetch non-squeezed pairs with pagination support.
    
    Args:
        offset: Number of records to skip (for pagination)
        limit: Maximum number of records to return
        
    Returns:
    - List of dictionaries containing pair information for non-squeezed pairs
    """
    try:
        sql = """
            SELECT *
            FROM pairstatus             
            ORDER BY volume_1h ASC
            LIMIT :limit OFFSET :offset
        """
        results = sql_helper.fetch_all_safe(sql, {"offset": offset, "limit": limit})
        if not results:
            return []
        
        # Get columns dynamically
        columns_query = "SELECT column_name FROM information_schema.columns WHERE table_name = 'pairstatus'"
        columns_data = sql_helper.fetch_all_safe(columns_query, tag="pairstatus")
        columns = [col[0] for col in columns_data]

        return [dict(zip(columns, row)) for row in results]
        
    except Exception as e:
        olab_log_db_error(e, "olab_fetch_non_squeezed_pairs_from_db_paginated", "DB Query")
        return []

def olab_get_total_pairs_count():
    """
    Get the total count of pairs in the database.
    
    Returns:
    - Integer representing total number of pairs
    """
    try:
        sql = "SELECT COUNT(*) FROM pairstatus "
        result = sql_helper.fetch_one(sql)
        return result[0] if result else 0
    except Exception as e:
        olab_log_db_error(e, "olab_get_total_pairs_count", "DB Query")
        return 0
    
def olab_count_running_trades(action):
    """
    Get the total count of running trades for a given action.

    Args:
        action (str): The trade action type (e.g., 'BUY' or 'SELL').

    Returns:
        int: Total number of running trades for the specified action.
    """
    try:
        sql = """
            SELECT COUNT(*) 
            FROM alltraderecords 
            WHERE type = 'running' 
              AND hedge = 0 
              AND action = :action
        """
        result = sql_helper.fetch_one(sql, {'action': action})
        return result[0] if result else 0

    except Exception as e:
        olab_log_db_error(e, "olab_count_running_trades", "DB Query")
        return 0
    

def olab_count_running_trades_negative(action):
    """
    Get the total count of running trades for a given action.

    Args:
        action (str): The trade action type (e.g., 'BUY' or 'SELL').

    Returns:
        int: Total number of running trades for the specified action.
    """
    try:
        sql = """
            SELECT sum(pl_after_comm)
            FROM alltraderecords 
            WHERE type = 'running' 
              AND hedge = 0 
              AND pl_after_comm < 0
              AND action = :action
        """
        result = sql_helper.fetch_one(sql, {'action': action})
        return result[0] if result else 0

    except Exception as e:
        olab_log_db_error(e, "olab_count_running_trades_negative", "DB Query")
        return 0
 

# def olab_check_running_trade_exists(symbol, interval, signal_from, candle_type):
#     """
#     Check if a running trade exists in the database for the given symbol, interval, and signal source.
    
#     Args:
#         symbol: Trading symbol (e.g., 'BTCUSDT')
#         interval: Timeframe (e.g., '1h', '4h')
#         signal_from: Signal source (e.g., 'BBUpLowBand', 'MacdCrossOver', 'ZeroLag_Trend')
        
#     Returns:
#         bool: True if running trade exists, False otherwise
#     """
#     try:
#         sql = """
#             SELECT pair FROM alltraderecords 
#             WHERE  type NOT IN ('close', 'hedge_close')
#             AND pair = :Pair             
#             AND signalfrom in ('Spike','Kicker','ProGap','IMACD')
            
#         """
        
#         result = sql_helper.fetch_one(sql, {
#             'Pair': symbol
#         })
        
#         if result:
#             print(f"⏭️ Running trade found for {symbol} | {interval} | {signal_from}")
#             return True
#         else:
#             return False
            
#     except Exception as e:
#         olab_log_db_error(e, "olab_check_running_trade_exists Error", symbol)
#         print(f"❌ olab_check_running_trade_exists Error for {symbol}-{interval}: {e}")
#         return False

def olab_check_running_trade_exists(symbol, interval, signal_from, candle_type):
    """
    Check if a running trade exists in the database for the given symbol, interval, and signal source.
    
    Args:
        symbol (str): Trading symbol (e.g., 'BTCUSDT')
        interval (str): Timeframe (e.g., '1h', '4h')
        signal_from (str): Signal source (e.g., 'BBUpLowBand', 'MacdCrossOver', 'ZeroLag_Trend')
        candle_type (str): Type of candle (unused currently)
        
    Returns:
        bool: True if a running trade exists, False otherwise.
    """
    try:
        sql = """
            SELECT 1 
            FROM alltraderecords 
            WHERE type in ('running','assign')
              AND pair = :Pair
              AND signalfrom = :SignalFrom
            LIMIT 1
        """
        
        result = sql_helper.fetch_one(sql, {
            'Pair': symbol,
            'SignalFrom': signal_from
        })
        
        if result:
            print(f"⏭️ Running trade found for {symbol} | {interval} | {signal_from}")
            return True
        else:
            return False

    except Exception as e:
        olab_log_db_error(e, "olab_check_running_trade_exists Error", symbol)
        print(f"❌ olab_check_running_trade_exists Error for {symbol}-{interval}: {e}")
        return False


def get_active_count(action, cnt):
    query = """
            SELECT EXISTS (
                SELECT 1
                FROM alltraderecords
                WHERE type = 'running'
                AND hedge = 0
                AND action = :action
                AND min_close = 'ACTIVE'
                GROUP BY 1
                HAVING COUNT(*) > :cnt
            ) AS ok;
        """
    try:
        row = sql_helper.fetch_one(query, {"action": action, "cnt": cnt})
        return bool(row[0]) if row else False
    except Exception as e:
        olab_log_db_error(e, "❌ olab_fetch_data_from_db Error for", "min_pl_cnt")
        print(f"[SQL ERROR] {e}")
        return False
    
def get_cnt_pl_more_than_sixty(action, minpl,cnt):
    query = """
            SELECT EXISTS (
                SELECT 1
                FROM alltraderecords
                WHERE type = 'running'
                AND hedge = 0
                AND action = :action
                AND pl_after_comm > :minpl
                 GROUP BY 1
                HAVING COUNT(*) > :cnt
                
            ) AS ok;
        """
    try:
        row = sql_helper.fetch_one(query, {"action": action, "minpl": minpl, "cnt": cnt})
        return bool(row[0]) if row else False
    except Exception as e:
        olab_log_db_error(e, "❌ olab_fetch_data_from_db Error for", "min_pl_cnt")
        print(f"[SQL ERROR] {e}")
        return False    

def get_active_loss():
    query = "SELECT buy, sell FROM active_loss WHERE id = 1;"
    try:
        row = sql_helper.fetch_one(query)
        if not row:
            return {"buy": False, "sell": False}
        return {"buy": row[0], "sell": row[1]}
    except Exception as e:
        olab_log_db_error(e, "❌ olab_fetch_data_from_db Error for", "get_active_loss")
        print(f"[SQL ERROR] {e}")
        return False



def olab_buy_is_loss_exceeding_5_percent_with_min_trades():
    """
    Returns True if:
    - There are at least 20 running, non-hedged trades, and
    - Total loss exceeds 5% of total profit
    """
    query = """
        SELECT buy_pl FROM alltraderecords
        WHERE type = 'running' AND hedge = 0 AND action = 'BUY'
    """

    try:
        results = sql_helper.fetch_all(query)
        
    except Exception as e:
        olab_log_db_error(e, "❌  olab_fetch_data_from_db Error for", 'check20mintrades')  
        print(f"[SQL ERROR] {e}")
        return False
    
    both_cnt = False
    minactivecount = get_active_count('BUY',2)

    minplcnt = get_cnt_pl_more_than_sixty('BUY', 60,5)
    if minactivecount :
        olab_write_db_insert_debug_log(f'min active count passed for BUY')
        both_cnt = True
    elif minplcnt:
        olab_write_db_insert_debug_log(f'min pl more than 60 count passed for BUY')
        both_cnt = True
    
    

    if not results or len(results) < 25 or not both_cnt:
        return False  # Not enough trades

    # Flatten values and filter None
    pl_values = [row[0] for row in results if row[0] is not None]

    total_profit = sum(pl for pl in pl_values if pl > 0)
    total_loss = abs(sum(pl for pl in pl_values if pl < 0))  # convert to positive

    resultpl = float(total_loss) < (0.09 * float(total_profit))
    print((f'is_loss_exceeding_5_percent_with_min_trades - {total_profit} - {total_loss} - total_loss < (0.09 * total_profit) = {resultpl}'))
    
    olab_write_db_insert_debug_log(f'is_loss_exceeding_5_percent_with_min_trades - {total_profit} - {total_loss} - total_loss < (0.09 * total_profit) = {resultpl}')
    # if resultpl and olab_candle_color('BTCUSDT','1h') == 'GREEN':
    #     olab_update_super_trend('BUY')

    return resultpl

def olab_get_super_trend(minutes=15):
    try:
        # compute cutoff as an aware UTC datetime
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

        sql = """
            SELECT trend
            FROM supertrend
            WHERE active = TRUE
              AND timestamp >= :cutoff
            LIMIT 1;
        """
        result = sql_helper.fetch_one(sql, {'cutoff': cutoff})
        return result[0] if result else None
    except Exception as e:
        olab_log_db_error(e, "olab_get_super_trend Error", "DB Query")
        return None

def olab_get_super_trend_percent(percent=30):
    try:
        sql = "SELECT check_supertrend_activity(:threshold);"
        params = {'threshold': percent}

        # use autocommit
        with sql_helper.engine.begin() as conn:
            result = conn.execute(text(sql), params).fetchone()

        if result and result[0]:
            return True
        else:
            return False

    except Exception as e:
        olab_log_db_error(e, "olab_get_super_trend_percent Error", "DB Query")
        print(f"[SQL ERROR] {e}")
        return False
    

def olab_check_and_deactivate_supertrend(percent=5):
    try:
        sql = "SELECT * FROM check_and_deactivate_supertrend(:threshold);"
        params = {'threshold': percent}

        # use autocommit
        with sql_helper.engine.begin() as conn:
            result = conn.execute(text(sql), params).fetchone()

        if result:
                print("is_deactivated:", result[0])
                print("running_pct:", result[1])
                print("minutes_since_trend:", result[2])
                print("close_trade_count:", result[3])
                print("running_trade_count:", result[4])
                return result  # you can return the full tuple if needed
        else:
            return None

    except Exception as e:
        olab_log_db_error(e, "olab_check_and_deactivate_supertrend Error", "DB Query")
        print(f"[SQL ERROR] {e}")
        return None




def olab_sell_is_loss_exceeding_5_percent_with_min_trades():
    """
    Returns True if:
    - There are at least 20 running, non-hedged trades, and
    - Total loss exceeds 5% of total profit
    """
    query = """
        SELECT sell_pl FROM alltraderecords
        WHERE type = 'running' AND hedge = 0 AND action = 'SELL'
    """
    print('vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv')
    try:
        results = sql_helper.fetch_all(query)
        
    except Exception as e:
        olab_log_db_error(e, "❌  olab_fetch_data_from_db Error for", 'check20mintrades')  
        print(f"[SQL ERROR] {e}")
        return False
    
    both_cnt = False
    minactivecount = get_active_count('SELL',2)

    minplcnt = get_cnt_pl_more_than_sixty('SELL', 60,0)
    if minactivecount :
        olab_write_db_insert_debug_log(f'min active count passed for SELL')
        both_cnt = True
    elif minplcnt:
        olab_write_db_insert_debug_log(f'min pl more than 60 count passed for SELL')
        both_cnt = True
    
    

    if not results or len(results) < 25 or not both_cnt:
        print('anish suwal')
        return False  # Not enough trades



    # Flatten values and filter None
    pl_values = [row[0] for row in results if row[0] is not None]

    total_profit = sum(pl for pl in pl_values if pl > 0)
    total_loss = abs(sum(pl for pl in pl_values if pl < 0))  # convert to positive

    # if total_profit < 130:
    #     return False
    
    resultpl = float(total_loss) < (0.07 * float(total_profit))
    print((f'is_loss_exceeding_5_percent_with_min_trades - {total_profit} - {total_loss} - total_loss < (0.07 * total_profit) = {resultpl}'))
    
    olab_write_db_insert_debug_log(f'is_loss_exceeding_5_percent_with_min_trades - {total_profit} - {total_loss} - total_loss < (0.07 * total_profit) = {resultpl}')
    # if resultpl and olab_candle_color('BTCUSDT','1h') == 'RED':    
    #     olab_update_super_trend('SELL')

    return resultpl

def olab_update_active_loss(action: str, is_active: bool):
    try:
        now = datetime.now(timezone.utc)

        if action == "BUY":
            update_query = """
                UPDATE active_loss
                SET buy = :is_active,
                    sell = FALSE,
                    updated_at = :now
                WHERE id = 1;
            """
        elif action == "SELL":
            update_query = """
                UPDATE active_loss
                SET buy = FALSE,
                    sell = :is_active,
                    updated_at = :now
                WHERE id = 1;
            """
        else:
            update_query = """
                UPDATE active_loss
                SET buy = FALSE,
                    sell = FALSE,
                    updated_at = :now
                WHERE id = 1;
            """

        sql_helper.execute(update_query, {"now": now, "is_active": is_active}, autocommit=True)

        with open("log_event/superTrend.txt", "a", encoding="utf-8") as f:
            f.write(
                f"Trend Active Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')} "
                f"-- Trend: {action} -- Active: {is_active}\n"
            )

        return True

    except Exception as e:
        olab_log_db_error(e, "❌ olab_update_active_loss Error for", "olab_update_active_loss")
        print(f"[SQL ERROR] {e}")
        return False

def olab_deactivate_both_position():
    try:
        update_query = """
            UPDATE supertrend 
            SET both_position = FALSE 
            
        """
        sql_helper.execute(update_query, autocommit=True)
        with open('log_event/superTrend.txt', 'a', encoding="utf-8") as f:
                f.write(f"Both Trend Deactivated Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} -- Trend : BOTH --'\n")

    except Exception as e:
        olab_log_db_error(e, "❌ olab_deactivate_both_position Error for", 'olab_deactivate_both_position')  
        print(f"[SQL ERROR] {e}")
        return False
    
def olab_activate_both_position():
    try:
        update_query = """
            UPDATE supertrend 
            SET both_position = TRUE 
            
        """
        sql_helper.execute(update_query, autocommit=True)
        with open('log_event/superTrend.txt', 'a', encoding="utf-8") as f:
                f.write(f"Both Trend Deactivated Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} -- Trend : BOTH --'\n")

    except Exception as e:
        olab_log_db_error(e, "❌ olab_activate_both_position Error for", 'olab_activate_both_position')  
        print(f"[SQL ERROR] {e}")
        return False    

def olab_update_database_to_release_hedge(unique_id, commission, signal, pl_after_comm, new_stop_price, Hed_pl, profitLoss, machine_id):
    try:
        if signal == 'BUY':
            update_query = f"""
                UPDATE {machine_id.lower()} SET 
                    pl_after_comm = :pl_after_comm,
                    commission = :commission,
                    type = 'hedge_release',
                    hedge_sell_pl = :Hed_pl,
                    stop_price = :new_stop_price,
                    sell_qty = 0,
                    sell_price = 0,
                    sell_pl = 0,
                    buy_pl = :profitLoss,
                    action = 'BUY',
                    hedge_1_1_bool = 0
                WHERE unique_id = :unique_id
                """
        elif signal == 'SELL':
            update_query = f"""
                UPDATE {machine_id.lower()} SET 
                    pl_after_comm = :pl_after_comm,
                    commission = :commission,
                    type = 'hedge_release',
                    hedge_buy_pl = :Hed_pl,    
                    stop_price = :new_stop_price,                
                    buy_qty = 0,
                    buy_price = 0,
                    buy_pl = 0,
                    sell_pl = :profitLoss,
                    action = 'SELL',
                    hedge_1_1_bool = 0
                WHERE unique_id = :unique_id
                """
        else:
            raise Exception(f"Unsupported signal: {signal}")

        update_params = {
            'pl_after_comm': 0 if pl_after_comm is None else pl_after_comm,
            'commission': 0 if commission is None else commission,
            'Hed_pl': 0 if Hed_pl is None else Hed_pl,
            'unique_id': unique_id,
            'profitLoss': 0 if profitLoss is None else profitLoss,
            'new_stop_price': new_stop_price
        }

        rows_updated = sql_helper.execute(update_query, update_params, autocommit=True)
        return rows_updated

    except Exception as outer_e:
        olab_log_db_error(outer_e, "olab_update_database_to_release_hedge", machine_id)
        print(f"❌ olab_update_database_to_release_hedge Global Error for {machine_id}: {outer_e}")

def olab_bulk_fetch_kline_data(symbols, interval, limit):
    """
    Fetches the latest kline data for a list of symbols in a single bulk query.
    """
    if not symbols:
        return pd.DataFrame()
    
    try:
        # Reduce limit for squeeze calculation (only need ~25 candles for 20-period calculations)
        actual_limit = min(limit, 30)  # Squeeze only needs 20-25 candles max
        
        # Build more efficient query - fetch only essential columns
        union_queries = []
        for symbol in symbols:
            table_name = f"kline_{symbol.lower()}_{interval}"
            query_part = f"""
            (SELECT '{symbol}' as symbol, 
                    time, 
                    open as open,
                    high as high, 
                    low as low,
                    close as close,
                    volume
             FROM {table_name} 
             ORDER BY time DESC
             LIMIT {actual_limit})
            """
            union_queries.append(query_part)
        
        # Use simpler query structure
        full_query = " UNION ALL ".join(union_queries)
        sql = f"SELECT * FROM ({full_query}) AS bulkdata ORDER BY symbol, time ASC"
        
        df = sql_helper.fetch_dataframe(sql)
        if df.empty:
            return df
        
        # Convert time
        df['time'] = pd.to_datetime(df['time'], unit='ms', utc=True)
        
        return df[['symbol', 'time', 'open', 'high', 'low', 'close', 'volume']]
        
    except Exception as e:
        olab_log_db_error(e, "❌ olab_bulk_fetch_kline_data Error", f"Symbols: {','.join(symbols)}")
        print(f"❌ olab_bulk_fetch_kline_data Error for symbols: {e}")
        return pd.DataFrame()

def bulk_olab_update_squeeze_status(updates):
    """
    Perform a true set-based update of squeeze fields using a temp table and a single UPDATE JOIN.
    Expects each item in `updates` to contain keys:
      pair, squeeze, squeeze_value, active_squeeze, active_squeeze_trend
    """
    if not updates:
        return 0

    # Normalize keys and types
    rows = []
    for u in updates:
        rows.append({
            'pair': u['pair'],
            'squeeze': bool(u.get('squeeze', False)),
            'squeeze_value': float(u.get('squeeze_value', 0.0)),
            'active_squeeze': bool(u.get('active_squeeze', False)),
            'active_squeeze_trend': str(u.get('active_squeeze_trend', 'NEUTRAL'))
        })

    created = 0
    conn = None
    trans = None
    try:
        conn = engine.connect()
        trans = conn.begin()

        # Create temp table scoped to this connection/transaction
        create_sql = """
        CREATE TEMP TABLE squeeze_updates (
            pair VARCHAR(50) NOT NULL,
            squeeze BOOLEAN NULL,
            squeeze_value FLOAT NULL,
            active_squeeze BOOLEAN NULL,
            active_squeeze_trend VARCHAR(16) NULL
        );
        """
        conn.execute(text(create_sql))

        # Bulk insert into temp table (one execute with many parameter sets)
        insert_sql = (
            "INSERT INTO squeeze_updates (pair, squeeze, squeeze_value, active_squeeze, active_squeeze_trend) "
            "VALUES (:pair, :squeeze, :squeeze_value, :active_squeeze, :active_squeeze_trend)"
        )
        conn.execute(text(insert_sql), rows)

        # Single set-based update join
        update_sql = """
        UPDATE pairstatus ps
        SET squeeze = u.squeeze,
            squeeze_value = u.squeeze_value,
            active_squeeze = u.active_squeeze,
            active_squeeze_trend = u.active_squeeze_trend
        FROM squeeze_updates u 
        WHERE u.pair = ps.pair;
        """
        result = conn.execute(text(update_sql))
        created = result.rowcount if hasattr(result, 'rowcount') else None

        trans.commit()
        return created
    except Exception as e:
        if trans is not None:
            try:
                trans.rollback()
            except Exception:
                pass
        olab_log_db_error(e, "❌ bulk_olab_update_squeeze_status Error", "n/a")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

def olab_update_overall_4h_market_trends_db(overall_4h_trend, overall_4h_percentage):
    """
    Update overall 4H market trends in the database.
    """
    try:
        # Check if the table exists, if not create it with proper constraint
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS overall_market_trends (
            id SERIAL PRIMARY KEY,
            timeframe VARCHAR(10) NOT NULL,
            overall_trend VARCHAR(20) NOT NULL,
            percentage_uptrend FLOAT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timeframe)
        );
        """
        sql_helper.execute(create_table_sql, autocommit=True)

        # Insert or update the 4H trend
        upsert_sql = """
        INSERT INTO overall_market_trends (timeframe, overall_trend, percentage_uptrend, last_updated)
        VALUES ('4h', :overall_trend, :percentage, CURRENT_TIMESTAMP)
        ON CONFLICT (timeframe)
        DO UPDATE SET
            overall_trend = EXCLUDED.overall_trend,
            percentage_uptrend = EXCLUDED.percentage_uptrend,
            last_updated = CURRENT_TIMESTAMP;
        """

        params = {
            'overall_trend': overall_4h_trend,
            'percentage': overall_4h_percentage
        }

        sql_helper.execute(upsert_sql, params, autocommit=True)
        print(f"✅ Updated overall 4H market trend: {overall_4h_trend} ({overall_4h_percentage:.2f}%)")

    except Exception as e:
        olab_log_db_error(e, "olab_update_overall_4h_market_trends_db", "all_pairs")
        print(f"❌ Error updating overall 4H market trends: {e}")

def olab_update_overall_1h_market_trends_db(overall_1h_trend, overall_1h_percentage):
    """
    Update overall 1H market trends in the database.
    """
    try:
        # Check if the table exists, if not create it with proper constraint
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS overall_market_trends (
            id SERIAL PRIMARY KEY,
            timeframe VARCHAR(10) NOT NULL,
            overall_trend VARCHAR(20) NOT NULL,
            percentage_uptrend FLOAT NOT NULL,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timeframe)
        );
        """
        sql_helper.execute(create_table_sql, autocommit=True)

        # Insert or update the 1H trend
        upsert_sql = """
        INSERT INTO overall_market_trends (timeframe, overall_trend, percentage_uptrend, last_updated)
        VALUES ('1h', :overall_trend, :percentage, CURRENT_TIMESTAMP)
        ON CONFLICT (timeframe)
        DO UPDATE SET
            overall_trend = EXCLUDED.overall_trend,
            percentage_uptrend = EXCLUDED.percentage_uptrend,
            last_updated = CURRENT_TIMESTAMP;
        """

        params = {
            'overall_trend': overall_1h_trend,
            'percentage': overall_1h_percentage
        }

        sql_helper.execute(upsert_sql, params, autocommit=True)
        print(f"✅ Updated overall 1H market trend: {overall_1h_trend} ({overall_1h_percentage:.2f}%)")

    except Exception as e:
        olab_log_db_error(e, "olab_update_overall_1h_market_trends_db", "all_pairs")
        print(f"❌ Error updating overall 1H market trends: {e}")

def olab_check_signal_processing_log_exists(symbol, interval, candle_pattern, candle_time):
    """Check if a signal processing log record already exists for the given parameters"""
    try:
        query = """
        SELECT COUNT(*) FROM signalprocessinglogs 
        WHERE symbol = :symbol 
        AND interval = :interval  
        AND candle_time = :candle_time  
        """
        
        result = sql_helper.fetch_one(query, {
            "symbol": symbol,
            "interval": interval,
            "candle_pattern": candle_pattern,
            "candle_time": candle_time
        })
        
        return result[0] > 0 if result else False
        
    except Exception as e:
        print(f"❌ Failed to check signal processing log existence: {e}")
        return False

def olab_insert_signal_processing_log(candle_time, symbol, interval, signal_type, signal_source, 
                                candle_pattern, price, squeeze_status, active_squeeze, 
                                processing_time_ms, machine_id, timestamp, json_data=None, unique_id=None):    
    """Insert signal processing log with new table structure and robust retry logic"""
    try:
        query = """
        INSERT INTO signalprocessinglogs (candle_time, symbol, interval, signal_type, signal_source, 
                                         candle_pattern, price, squeeze_status, active_squeeze, 
                                         processing_time_ms, machine_id, timestamp, json_data, unique_id)
        VALUES (:candle_time, :symbol, :interval, :signal_type, :signal_source, :candle_pattern, :price, 
                :squeeze_status, :active_squeeze, :processing_time_ms, :machine_id, 
                :timestamp, :json_data, :unique_id)
        """
        sql_helper.execute(query, {
            "candle_time": candle_time,
            "symbol": symbol,
            "interval": interval,
            "signal_type": signal_type,
            "signal_source": signal_source,
            "candle_pattern": candle_pattern,
            "price": price,
            "squeeze_status": squeeze_status,
            "active_squeeze": active_squeeze,
            "processing_time_ms": processing_time_ms,
            "machine_id": machine_id,
            "timestamp": timestamp,
            "json_data": json_data,
            "unique_id": unique_id
        }, autocommit=True)
        return True
    except Exception as e:
        print(f"❌ Failed to insert signal processing log: {e}")
        return False

def olab_insert_signal_validation_log(symbol, interval, validation_step, validation_result, 
                                validation_value, validation_threshold, validation_message, 
                                machine_id, timestamp, json_data=None):
    """Insert signal validation log"""
    try:
        query = """
        INSERT INTO signalvalidationlogs (symbol, interval, validation_step, validation_result, 
                                         validation_value, validation_threshold, validation_message, 
                                         machine_id, timestamp, json_data)
        VALUES (:symbol, :interval, :validation_step, :validation_result, :validation_value, 
                :validation_threshold, :validation_message, :machine_id, :timestamp, :json_data)
        """
        sql_helper.execute(query, {
            "symbol": symbol,
            "interval": interval,
            "validation_step": validation_step,
            "validation_result": validation_result,
            "validation_value": validation_value,
            "validation_threshold": validation_threshold,
            "validation_message": validation_message,
            "machine_id": machine_id,
            "timestamp": timestamp,
            "json_data": json_data
        }, autocommit=True)
        return True
    except Exception as e:
        print(f"❌ Failed to insert signal validation log: {e}")
        return False

def olab_insert_performance_metric(metric_type, metric_name, metric_value, metric_unit, 
                             symbol, interval, batch_size, machine_id, timestamp, 
                             additional_data=None):
    """Insert performance metric"""
    try:
        query = """
        INSERT INTO performancemetrics (metric_type, metric_name, metric_value, metric_unit, 
                                       symbol, interval, batch_size, machine_id, timestamp, additional_data)
        VALUES (:metric_type, :metric_name, :metric_value, :metric_unit, :symbol, :interval, 
                :batch_size, :machine_id, :timestamp, :additional_data)
        """
        sql_helper.execute(query, {
            "metric_type": metric_type,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "metric_unit": metric_unit,
            "symbol": symbol,
            "interval": interval,
            "batch_size": batch_size,
            "machine_id": machine_id,
            "timestamp": timestamp,
            "additional_data": additional_data
        }, autocommit=True)
        return True
    except Exception as e:
        print(f"❌ Failed to insert performance metric: {e}")
        return False

def olab_insert_batch_processing_log(batch_type, batch_size, successful_count, error_count, 
                               crash_count, total_processing_time_ms, average_time_per_item_ms, 
                               machine_id, timestamp, executor_type, worker_count, json_details=None):
    """Insert batch processing log"""
    try:
        query = """
        INSERT INTO batchprocessinglogs (batch_type, batch_size, successful_count, error_count, 
                                        crash_count, total_processing_time_ms, average_time_per_item_ms, 
                                        machine_id, timestamp, executor_type, worker_count, json_details)
        VALUES (:batch_type, :batch_size, :successful_count, :error_count, :crash_count, 
                :total_processing_time_ms, :average_time_per_item_ms, :machine_id, :timestamp, 
                :executor_type, :worker_count, :json_details)
        """
        sql_helper.execute(query, {
            "batch_type": batch_type,
            "batch_size": batch_size,
            "successful_count": successful_count,
            "error_count": error_count,
            "crash_count": crash_count,
            "total_processing_time_ms": total_processing_time_ms,
            "average_time_per_item_ms": average_time_per_item_ms,
            "machine_id": machine_id,
            "timestamp": timestamp,
            "executor_type": executor_type,
            "worker_count": worker_count,
            "json_details": json_details
        }, autocommit=True)
        return True
    except Exception as e:
        print(f"❌ Failed to insert batch processing log: {e}")
        return False

def olab_insert_system_health_log(cpu_usage, memory_usage, memory_available_mb, disk_usage, 
                            network_latency_ms, active_threads, active_processes, 
                            database_connections, api_calls_per_minute, error_rate_percent, 
                            machine_id, timestamp, health_status):
    """Insert system health log"""
    try:
        query = """
        INSERT INTO systemhealthlogs (cpu_usage, memory_usage, memory_available_mb, disk_usage, 
                                     network_latency_ms, active_threads, active_processes, 
                                     database_connections, api_calls_per_minute, error_rate_percent, 
                                     machine_id, timestamp, health_status)
        VALUES (:cpu_usage, :memory_usage, :memory_available_mb, :disk_usage, :network_latency_ms, 
                :active_threads, :active_processes, :database_connections, :api_calls_per_minute, 
                :error_rate_percent, :machine_id, :timestamp, :health_status)
        """
        sql_helper.execute(query, {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "memory_available_mb": memory_available_mb,
            "disk_usage": disk_usage,
            "network_latency_ms": network_latency_ms,
            "active_threads": active_threads,
            "active_processes": active_processes,
            "database_connections": database_connections,
            "api_calls_per_minute": api_calls_per_minute,
            "error_rate_percent": error_rate_percent,
            "machine_id": machine_id,
            "timestamp": timestamp,
            "health_status": health_status
        }, autocommit=True)
        return True
    except Exception as e:
        print(f"❌ Failed to insert system health log: {e}")
        return False

def olab_insert_cache_performance_log(cache_type, operation_type, symbol, interval, cache_key, 
                                response_time_ms, cache_size_mb, hit_rate_percent, 
                                machine_id, timestamp):
    """Insert cache performance log"""
    try:
        query = """
        INSERT INTO cacheperformancelogs (cache_type, operation_type, symbol, interval, cache_key, 
                                         response_time_ms, cache_size_mb, hit_rate_percent, 
                                         machine_id, timestamp)
        VALUES (:cache_type, :operation_type, :symbol, :interval, :cache_key, :response_time_ms, 
                :cache_size_mb, :hit_rate_percent, :machine_id, :timestamp)
        """
        sql_helper.execute(query, {
            "cache_type": cache_type,
            "operation_type": operation_type,
            "symbol": symbol,
            "interval": interval,
            "cache_key": cache_key,
            "response_time_ms": response_time_ms,
            "cache_size_mb": cache_size_mb,
            "hit_rate_percent": hit_rate_percent,
            "machine_id": machine_id,
            "timestamp": timestamp
        }, autocommit=True)
        return True
    except Exception as e:
        print(f"❌ Failed to insert cache performance log: {e}")
        return False

def olab_log_error(error, context, symbol=None, machine_id=None):
    """Log error with context"""
    try:
        # Use the existing olab_log_db_error function
        olab_log_db_error(error, context, symbol)
        return True
    except Exception as e:
        print(f"❌ Failed to log error: {e}")
        return False

def olab_log_signal_processing(candle_time, symbol, interval, signal_type, signal_source, 
                         candle_pattern, price, squeeze_status, active_squeeze, 
                         processing_time_ms, machine_id, timestamp, json_data=None, unique_id=None):
    """Log signal processing"""
    try:
        return olab_insert_signal_processing_log(candle_time, symbol, interval, signal_type, signal_source, 
                                         candle_pattern, price, squeeze_status, active_squeeze, 
                                         processing_time_ms, machine_id, timestamp, json_data, unique_id)
    except Exception as e:
        print(f"❌ Failed to log signal processing: {e}")
        return False

def olab_log_signal_validation(symbol, interval, validation_step, validation_result, 
                         validation_value, validation_threshold, validation_message, 
                         machine_id, timestamp, json_data=None):
    """Log signal validation"""
    try:
        return olab_insert_signal_validation_log(symbol, interval, validation_step, validation_result, 
                                         validation_value, validation_threshold, validation_message, 
                                         machine_id, timestamp, json_data)
    except Exception as e:
        print(f"❌ Failed to log signal validation: {e}")
        return False

def olab_log_performance_metric(metric_type, metric_name, metric_value, metric_unit, 
                          symbol, interval, batch_size, machine_id, timestamp, 
                          additional_data=None):
    """Log performance metric"""
    try:
        return olab_insert_performance_metric(metric_type, metric_name, metric_value, metric_unit, 
                                      symbol, interval, batch_size, machine_id, timestamp, 
                                      additional_data)
    except Exception as e:
        print(f"❌ Failed to log performance metric: {e}")
        return False

def olab_log_batch_processing(batch_type, batch_size, successful_count, error_count, 
                        crash_count, total_processing_time_ms, average_time_per_item_ms, 
                        machine_id, timestamp, executor_type, worker_count, json_details=None):
    """Log batch processing"""
    try:
        return olab_insert_batch_processing_log(batch_type, batch_size, successful_count, error_count, 
                                        crash_count, total_processing_time_ms, average_time_per_item_ms, 
                                        machine_id, timestamp, executor_type, worker_count, json_details)
    except Exception as e:
        print(f"❌ Failed to log batch processing: {e}")
        return False

def olab_log_system_health(cpu_usage, memory_usage, memory_available_mb, disk_usage, 
                     network_latency_ms, active_threads, active_processes, 
                     database_connections, api_calls_per_minute, error_rate_percent, 
                     machine_id, timestamp, health_status):
    """Log system health"""
    try:
        return olab_insert_system_health_log(cpu_usage, memory_usage, memory_available_mb, disk_usage, 
                                     network_latency_ms, active_threads, active_processes, 
                                     database_connections, api_calls_per_minute, error_rate_percent, 
                                     machine_id, timestamp, health_status)
    except Exception as e:
        print(f"❌ Failed to log system health: {e}")
        return False

def olab_log_cache_performance(cache_type, operation_type, symbol, interval, cache_key, 
                         response_time_ms, cache_size_mb, hit_rate_percent, 
                         machine_id, timestamp):
    """Log cache performance"""
    try:
        return olab_insert_cache_performance_log(cache_type, operation_type, symbol, interval, cache_key, 
                                         response_time_ms, cache_size_mb, hit_rate_percent, 
                                         machine_id, timestamp)
    except Exception as e:
        print(f"❌ Failed to log cache performance: {e}")
        return False

def olab_performance_monitor(metric_type, function_name, machine_id=None):
    """Performance monitor decorator"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                processing_time_ms = int((time.time() - start_time) * 1000)
                print(f"📊 Performance: {function_name} completed in {processing_time_ms}ms")
                return result
            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                print(f"❌ Performance: {function_name} failed after {processing_time_ms}ms: {e}")
                raise
        return wrapper
    return decorator

def olab_insert_enhanced_error_log(error_level, error_category, symbol, source_function, 
                             error_message, line_number, stack_trace, machine_id, 
                             timestamp, json_context=None):
    """Insert error log into enhanced error logs table"""
    try:
        query = """
        INSERT INTO enhancederrorlogs (error_level, error_category, symbol, source_function, 
                                      error_message, line_number, stack_trace, machine_id, 
                                      timestamp, json_context)
        VALUES (:error_level, :error_category, :symbol, :source_function, :error_message, 
                :line_number, :stack_trace, :machine_id, :timestamp, :json_context)
        """
        sql_helper.execute(query, {
            "error_level": error_level,
            "error_category": error_category,
            "symbol": symbol,
            "source_function": source_function,
            "error_message": error_message,
            "line_number": line_number,
            "stack_trace": stack_trace,
            "machine_id": machine_id,
            "timestamp": timestamp,
            "json_context": json_context
        }, autocommit=True)
    except Exception as e:
        print(f"❌ Failed to insert enhanced error log: {e}")
        olab_log_db_error(e, "insert_enhanced_error_log", symbol)

def olab_update_overall_trends_for_all_pairs_db(overall_trend_RC, overall_trend_percentage_RC, overall_trend_HC, overall_trend_percentage_HC):
    """
    Update overall market trends for all pairs in the PairStatus table.
    """
    try:
        sql = """
        UPDATE pairstatus
        SET overall_trend_RC = :overall_trend_RC,
            overall_trend_percentage_RC = :overall_trend_percentage_RC,
            overall_trend_HC = :overall_trend_HC,
            overall_trend_percentage_HC = :overall_trend_percentage_HC,
            last_updated = :last_updated
        """
        current_time = datetime.now()
        params = {
            'overall_trend_RC': str(overall_trend_RC),
            'overall_trend_percentage_RC': float(overall_trend_percentage_RC),
            'overall_trend_HC': str(overall_trend_HC),
            'overall_trend_percentage_HC': float(overall_trend_percentage_HC),
            'last_updated': current_time
        }
        sql_helper.execute(sql, params, autocommit=True)
    except Exception as e:
        print(f"❌ Error updating overall trends for all pairs: {e}")

def olab_fetch_hedge_1_1():
    machine_id = 'm1'
    try:
        # Main query
        query = """
            SELECT 
                ps.pair, 
                ps.status1d_4h, 
                ps.status4h_1h, 
                ps.last_day_close_price, 
                ps.tf_1d_trend, 
                ps.squeeze_value, 
                ps.active_squeeze, 
                ps.active_squeeze_trend, 
                ps.overall_trend_rc, 
                ps.overall_trend_percentage_rc, 
                ps.overall_trend_hc, 
                ps.overall_trend_percentage_hc,
                ps.overall_trend_4h, 
                ps.overall_trend_percentage_4h, 
                ps.overall_trend_1h, 
                ps.overall_trend_percentage_1h
            FROM pairstatus ps
            INNER JOIN (
                SELECT pair
                FROM alltraderecords
                WHERE type != 'hedge_close' 
                AND type != 'close'
                AND hedge = 1 
                AND hedge_1_1_bool = 1
                GROUP BY pair
            ) m ON ps.pair = m.pair;
        """

        rows = sql_helper.fetch_all_safe(query, tag=machine_id)

        if not rows:
            return []

        # Get columns for PairStatus
        columns_query = "SELECT column_name FROM information_schema.columns WHERE table_name = 'pairstatus'"
        columns_data = sql_helper.fetch_all(columns_query)
        columns = [col[0] for col in columns_data]

        # Convert to list of dicts
        result = [dict(zip(columns, row)) for row in rows]
        return result

    except Exception as outer_e:
        olab_log_db_error(outer_e, "olab_fetch_hedge_1_1", machine_id)
        print(f"❌ olab_fetch_hedge_1_1 Global Error for {machine_id}: {outer_e}")

def olab_fetch_hedge_data_for_release(pair):
    try:
        # Parameterized query to prevent SQL injection
        query = """
            SELECT *
            FROM alltraderecords
            WHERE pair = :pair
              AND type != 'hedge_close'
              AND type != 'close'
              AND hedge = 1
              AND hedge_1_1_bool = 1
        """
        
        rows = sql_helper.fetch_all_safe(query, params={'pair': pair}, tag="system")
         # If no rows, return empty list
        if not rows:
            return []

        # Get columns dynamically
        columns_query = f"SELECT column_name FROM information_schema.columns WHERE table_name = 'alltraderecords'"
        columns_data = sql_helper.fetch_all(columns_query)
        columns = [col[0] for col in columns_data]

        # Convert rows to list of dicts
        result = [dict(zip(columns, row)) for row in rows]
        return result

    except Exception as outer_e:
        olab_log_db_error(outer_e, "olab_fetch_hedge_data_for_release", "system")
        print(f"❌ olab_fetch_hedge_data_for_release Global Error: {outer_e}")
        return []




# Add timestamp cleaning function
def olab_clean_timestamp_values(data):
    """Clean timestamp values to prevent 'NONE' string errors and preserve booleans for boolean DB columns"""
    if isinstance(data, dict):
        cleaned = {}
        boolean_keys = {
            'squeeze_status',
            'active_squeeze',
            'squeeze',
            'is_active',
            'exist_in_exchange',
            'auto',
            'update_table',
        }
        for key, value in data.items():
            if isinstance(value, str) and value.upper() == 'NONE':
                # Convert 'NONE' string to None for timestamp fields
                if any(timestamp_field in key.lower() for timestamp_field in ['time', 'date', 'timestamp']):
                    cleaned[key] = None
                else:
                    cleaned[key] = value
            elif isinstance(value, bool):
                # Preserve booleans for known boolean DB columns; convert others to int if needed
                if key in boolean_keys:
                    cleaned[key] = value
                else:
                    cleaned[key] = 1 if value else 0
            elif isinstance(value, (dict, list)):
                cleaned[key] = olab_clean_timestamp_values(value)
            else:
                cleaned[key] = value
        return cleaned
    elif isinstance(data, list):
        return [olab_clean_timestamp_values(item) for item in data]
    else:
        return data

# Add SQL query optimization function
def olab_optimize_sql_query(sql_query):
    """Fix common SQL issues for PostgreSQL compatibility"""
    if not sql_query:
        return sql_query
    
    # Fix boolean = integer comparisons
    patterns = [
        # Fix: WHERE m.active = 1 -> WHERE m.active = true
        (r'(\w+\.active)\s*=\s*1', r'\1 = true'),
        (r'(\w+\.active)\s*=\s*0', r'\1 = false'),
        # Fix: WHERE active = 1 -> WHERE active = true
        (r'\b(active)\s*=\s*1\b', r'\1 = true'),
        (r'\b(active)\s*=\s*0\b', r'\1 = false'),
        # Fix: WHERE is_active = 1 -> WHERE is_active = true
        (r'\b(is_active)\s*=\s*1\b', r'\1 = true'),
        (r'\b(is_active)\s*=\s*0\b', r'\1 = false'),
    ]
    
    optimized_query = sql_query
    for pattern, replacement in patterns:
        optimized_query = re.sub(pattern, replacement, optimized_query, flags=re.IGNORECASE)
    
    return optimized_query

# Enhanced connection management
class EnhancedSQLAccessHelper:
    def __init__(self, engine):
        self.engine = engine
        self._pid = os.getpid()
        self.connection_lock = threading.Lock()
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5 minutes
        
    def _ensure_engine(self):
        """Ensure the helper holds an engine created in the current process.
        If a fork occurred, dispose the inherited engine and create a fresh one.
        """
        current_pid = os.getpid()
        if current_pid != self._pid:
            try:
                # Dispose inherited connections safely
                self.engine.dispose()
            except Exception:
                pass
            # Recreate a brand-new engine for this process
            self.engine = olab_create_new_engine()
            self._pid = current_pid
    
    def _cleanup_connections(self):
        """Clean up idle connections"""
        current_time = time.time()
        if current_time - self.last_cleanup > self.cleanup_interval:
            try:
                import gc
                gc.collect()
                self.last_cleanup = current_time
            except Exception as e:
                logging.error(f"Connection cleanup error: {e}")
    
    def _get_connection_with_retry(self, max_retries=3, retry_delay=1):
        """Get database connection with retry logic"""
        for attempt in range(max_retries):
            try:
                self._ensure_engine()
                self._cleanup_connections()
                return self.engine.connect()
            except Exception as e:
                if "too many clients" in str(e).lower():
                    print(f"🔄 Connection pool exhausted, attempt {attempt + 1}/{max_retries}")
                    self._cleanup_connections()
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    raise e
        raise Exception("Failed to get database connection after retries")

    def fetch_one(self, sql_query, params=None):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                with self._get_connection_with_retry() as conn:
                    return conn.execute(text(optimized_query), params or {}).fetchone()
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Fetch One Error", 'fetch_one')
            print(f"❌ SQL Fetch One Error: {e}")
            return None

    def fetch_all(self, sql_query, params=None):
        try:
            with self.connection_lock:
                self._ensure_engine()
                optimized_query = olab_optimize_sql_query(sql_query)
                with self._get_connection_with_retry() as conn:
                    return conn.execute(text(optimized_query), params or {}).fetchall()
        except Exception as e:
            olab_log_db_error(e, "❌ SQL Fetch All Error", 'fetch_all')
            print(f"❌ SQL Fetch All Error: {e}")
            return []

    def fetch_all_safe(self, sql_query, params=None, timeout=5, retries=3, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    with self._get_connection_with_retry() as conn:
                        result = conn.execution_options(timeout=timeout).execute(text(optimized_query), params or {}).fetchall()
                        if attempt > 1:
                            print(f"✅ SQL FetchAll succeeded on attempt {attempt} | Tag: {tag}")
                        return result
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL FetchAll Error Try {attempt}", tag)
                print(f"❌ SQL FetchAll Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                if attempt < retries:
                    print(f"⏳ Waiting {delay} seconds before retry...")
                    time.sleep(delay)
                    delay *= 1.5
        print(f"🛑 SQL FetchAll FAILED after {retries} tries | Tag: {tag}")
        return []

    def fetch_one_safe(self, sql_query, params=None, timeout=5, retries=3, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    with self._get_connection_with_retry() as conn:
                        return conn.execution_options(timeout=timeout).execute(text(optimized_query), params or {}).fetchone()
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL FetchOne Error Try {attempt}", tag)
                print(f"❌ SQL FetchOne Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                time.sleep(delay)
        print(f"🛑 SQL FetchOne FAILED after {retries} tries | Tag: {tag}")
        return None

    def execute_safe(self, sql_query, params=None, autocommit=False, timeout=5, retries=3, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    # Clean parameters including boolean conversion
                    cleaned_params = olab_clean_timestamp_values(params) if params else {}
                    with self._get_connection_with_retry() as conn:
                        if autocommit:
                            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                        conn.execution_options(timeout=timeout).execute(text(optimized_query), cleaned_params)
                return True
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL Execute Error Try {attempt}", tag)
                print(f"❌ SQL Execute Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                time.sleep(delay)
        print(f"🛑 SQL Execute FAILED after {retries} tries | Tag: {tag}")
        return False

    def execute_many_safe(self, sql_query, param_list, autocommit=False, timeout=5, retries=3, delay=2, tag=""):
        for attempt in range(1, retries + 1):
            try:
                with self.connection_lock:
                    self._ensure_engine()
                    optimized_query = olab_optimize_sql_query(sql_query)
                    # Clean parameters including boolean conversion
                    cleaned_param_list = [olab_clean_timestamp_values(params) for params in param_list]
                    with self._get_connection_with_retry() as conn:
                        if autocommit:
                            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                        conn.execution_options(timeout=timeout).execute(text(optimized_query), cleaned_param_list)
                return True
            except Exception as e:
                olab_log_db_error(e, f"❌ SQL ExecuteMany Error Try {attempt}", tag)
                print(f"❌ SQL ExecuteMany Error Try {attempt}/{retries} | Tag: {tag} | Error: {e}")
                time.sleep(delay)
        print(f"🛑 SQL ExecuteMany FAILED after {retries} tries | Tag: {tag}")
        return False
    

def olab_convert_to_henkin(df):
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
        print(f"Error in convertToHenkin: {e}")        
        return df    
    
def olab_candle_color(symbol,min):
    df=olab_fetch_data_safe(symbol,min,10)

    # df = olab_convert_to_henkin(df)
    df['ha_color'] = np.where(df['close'] >= df['open'], 'GREEN', 'RED')
    return df['ha_color'].iloc[-1] 

def fetch_ohlcv(symbol, timeframe, limit):
    """Fetch OHLCV data from Binance."""
    try:
        klines = client.klines(symbol=symbol, interval=timeframe, limit=limit)
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                                           'close_time', 'quote_av', 'trades', 'tb_base_av', 
                                           'tb_quote_av', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume','tb_base_av']].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching OHLCV data: {e}")
        return pd.DataFrame()

# print(CandleColor('BTCUSDT','1h')) 

# print(getSuperTrend(60000))  
# print(getSuperTrendPercent(30))  

# result = check_and_deactivate_supertrend(5)
# print(result[6])

# if  result[0]:
#     print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
#     min = result[2]
#     if min > 45 :
#         print(f'Deactivating Supertrend for {min} minutes')

# print(result)

# print(sell_is_loss_exceeding_5_percent_with_min_trades())

# print(get_active_count('SELL',5))

# res = get_active_loss()
# print(res)

# buy = res["buy"]
# sell = res["sell"]

# print(buy)
# print(sell)

# abc = olab_count_running_trades('BUY')
# print(abc)
# if abc > 15:
#     print('More than 5 SELL trades are running')
# else:       
#     print('Less than 5 SELL trades are running')

# Lock for exchange sync so only one process/thread inserts at a time (multi-PC frontend safe)
_sync_exchange_trades_lock = threading.Lock()

# Default machine table for exchange-synced positions
EXCHANGE_SYNC_MACHINE_ID = "M1"

def _olab_build_m1_alltraderecords_document(unique_id, operator_trade_time, pair, investment, position_amt, entry_price, unrealized_profit, leverage_val, position_side, is_hedge):
    """Build document for m1 and alltraderecords from exchange_trade row. Same columns as assign + exist_in_exchange, exchange_position, auto, update_table."""
    action = "BUY" if position_side == "LONG" else "SELL"
    ts = operator_trade_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(operator_trade_time, "strftime") else str(operator_trade_time)
    buy_qty = position_amt if position_amt > 0 else 0
    sell_qty = abs(position_amt) if position_amt < 0 else 0
    buy_price = entry_price if position_side == "LONG" else 0
    sell_price = entry_price if position_side == "SHORT" else 0
    hedge_int = 1 if is_hedge else 0
    document = {
        "machineid": EXCHANGE_SYNC_MACHINE_ID,
        "unique_id": unique_id,
        "candel_time": ts,
        "fetcher_trade_time": ts,
        "operator_trade_time": operator_trade_time,
        "operator_close_time": None,
        "pair": pair,
        "investment": investment,
        "interval": "15m",
        "stop_price": 0,
        "save_price": 0,
        "min_comm": 0,
        "hedge": hedge_int,
        "hedge_1_1_bool": hedge_int,
        "action": action,
        "buy_qty": buy_qty,
        "buy_price": buy_price,
        "buy_pl": 0,
        "sell_qty": sell_qty,
        "sell_price": sell_price,
        "sell_pl": 0,
        "commission": 0,
        "pl_after_comm": unrealized_profit,
        "close_price": 0,
        "commision_journey": 0,
        "profit_journey": 0,
        "min_profit": 0,
        "hedge_order_size": 0,
        "hedge_1_1_bool": 0,
        "added_qty": 0,
        "min_comm_after_hedge": 0,
        "type": "running",
        "min_close": "NOT_ACTIVE",
        "signalfrom": "exchange_sync",
        "macd_action": "Active",
        "swing1": 0,
        "swing2": 0,
        "swing3": 0,
        "hedge_swing_high_point": 0,
        "hedge_swing_low_point": 0,
        "hedge_buy_pl": 0,
        "hedge_sell_pl": 0,
        "temp_high_point": 0,
        "temp_low_point": 0,
        "exist_in_exchange": True,
        "exchange_position": "running",
        "auto": False,
        "update_table": False,
    }
    return document


def _log_hedge_debug(msg):
    """Write sync debug to log_event/sync_hedge_debug.log (temporary, remove later)."""
    try:
        log_dir = os.path.join(os.path.dirname(__file__), '..', 'log_event')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'sync_hedge_debug.log')
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def olab_sync_exchange_trades(positions):
    """
    Sync open positions from Binance to exchange_trade, m1, and alltraderecords.
    Uses a lock so only one sync runs at a time (multi-PC frontend safe).
    If any of the three inserts fails, the transaction is rolled back and retried.
    positions: List of position dicts from getAllOpenPosition()
    Returns: dict with inserted_count, updated_count, already_existed_count, errors
    """
    if not positions or not isinstance(positions, list):
        _log_hedge_debug("STEP 0: SKIP - no positions or not a list, returning 0")
        return {"inserted_count": 0, "updated_count": 0, "already_existed_count": 0, "errors": []}
    
    inserted_count = 0
    already_existed_count = 0
    errors = []
    
    _log_hedge_debug(f"STEP 1: received {len(positions)} positions from getAllOpenPosition")
    
    try:
        # Group positions by symbol to detect hedge trades
        positions_by_symbol = {}
        for pos in positions:
            symbol = pos.get('symbol', '').upper()
            if symbol:
                if symbol not in positions_by_symbol:
                    positions_by_symbol[symbol] = []
                positions_by_symbol[symbol].append(pos)
        for sym, plist in positions_by_symbol.items():
            _log_hedge_debug(f"STEP 2a: symbol={sym} position_count={len(plist)} sides={[p.get('positionSide') for p in plist]}")
        
        # Check which positions already exist
        symbols_list = list(positions_by_symbol.keys())
        if not symbols_list:
            _log_hedge_debug("STEP 2b: SKIP - no valid symbols, returning")
            return {"inserted_count": 0, "updated_count": 0, "already_existed_count": 0, "errors": ["No valid symbols found"]}
        
        # Query existing running trades for these symbols
        placeholders = ','.join([f"'{s}'" for s in symbols_list])
        check_query = f"""
            SELECT pair, unique_id FROM exchange_trade 
            WHERE pair IN ({placeholders}) AND type = 'running'
        """
        existing_df = sql_helper.fetch_dataframe(check_query)
        existing_pairs = set(existing_df['pair'].str.upper().tolist() if not existing_df.empty else [])
        existing_unique_ids = set(existing_df['unique_id'].tolist() if not existing_df.empty else [])
        _log_hedge_debug(f"STEP 3: exchange_trade has {len(existing_unique_ids)} existing running rows, pairs={list(existing_pairs)}")
        
        # Process each position
        for symbol, symbol_positions in positions_by_symbol.items():
            is_hedge = len(symbol_positions) >= 2  # 2+ positions of same symbol = hedge
            hedge_val = 1 if is_hedge else 0
            _log_hedge_debug(f"STEP 4: symbol={symbol} len(symbol_positions)={len(symbol_positions)} is_hedge={is_hedge} hedge={hedge_val}")
            
            for pos in symbol_positions:
                try:
                    # Extract data
                    position_side = pos.get('positionSide', '').upper()
                    update_time_ms = pos.get('updateTime', 0)
                    
                    # Convert updateTime (milliseconds) to readable datetime
                    if update_time_ms:
                        update_dt = datetime.fromtimestamp(update_time_ms / 1000, tz=timezone.utc)
                        update_time_str = update_dt.strftime('%Y-%m-%d %H:%M:%S%z')
                        # Format timezone offset: +00:00 instead of +0000
                        if len(update_time_str) > 19:
                            tz_part = update_time_str[19:]
                            if len(tz_part) == 5 and tz_part[0] in ['+', '-']:
                                update_time_str = update_time_str[:19] + tz_part[:3] + ':' + tz_part[3:]
                    else:
                        update_dt = datetime.now(timezone.utc)
                        update_time_str = update_dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
                    
                    # Map positionSide to BUY/SELL
                    side_str = 'BUY' if position_side == 'LONG' else 'SELL'
                    
                    # Create unique_id: symbol + side + updateTime + "I" (as per example: ARPAUSDTSELL2026-02-09 04:00:00+00:00I)
                    unique_id = f"{symbol}{side_str}{update_time_str}I"
                    
                    # Skip if already exists
                    if unique_id in existing_unique_ids:
                        already_existed_count += 1
                        _log_hedge_debug(f"STEP 5a: SKIP unique_id exists - {symbol} {side_str} unique_id={unique_id[:50]}...")
                        continue
                    
                    # Skip if pair already exists as running (unless it's a different unique_id)
                    if symbol.upper() in existing_pairs:
                        # Check if this specific unique_id exists
                        if unique_id not in existing_unique_ids:
                            _log_hedge_debug(f"STEP 5b: pair {symbol} exists but unique_id different - PROCEED to insert")
                        else:
                            already_existed_count += 1
                            _log_hedge_debug(f"STEP 5b: SKIP pair exists + unique_id exists - {symbol} {side_str}")
                            continue
                    
                    # Prepare insert values
                    position_amt = float(pos.get('positionAmt', 0) or 0)
                    entry_price = float(pos.get('entryPrice', 0) or 0)
                    unrealized_profit = float(pos.get('unRealizedProfit', 0) or 0)
                    leverage_val = float(pos.get('leverage', 0) or 0)
                    notional = float(pos.get('notional', 0) or 0)
                    investment = abs(notional)
                    
                    exchange_params = {
                        "unique_id": unique_id,
                        "operator_trade_time": update_dt,
                        "pair": symbol.upper(),
                        "investment": investment,
                        "positionAmt": position_amt,
                        "entryPrice": entry_price,
                        "unRealizedProfit": unrealized_profit,
                        "leverage": leverage_val,
                        "positionSide": position_side,
                        "hedge": 1 if is_hedge else 0,
                    }
                    _log_hedge_debug(f"STEP 6: ATTEMPT INSERT {symbol} {side_str} unique_id={unique_id[:50]}... hedge={exchange_params['hedge']}")
                    exchange_insert = """
                        INSERT INTO exchange_trade (
                            unique_id, operator_trade_time, operator_close_time, type, pair,
                            investment, stop_price, positionAmt, entryPrice, unRealizedProfit,
                            leverage, positionSide, hedge
                        ) VALUES (
                            :unique_id, :operator_trade_time, NULL, 'running', :pair,
                            :investment, 0, :positionAmt, :entryPrice, :unRealizedProfit,
                            :leverage, :positionSide, CAST(:hedge AS BOOLEAN)
                        )
                    """
                    
                    # Build m1/alltraderecords document (same columns for both tables)
                    doc = _olab_build_m1_alltraderecords_document(
                        unique_id, update_dt, symbol.upper(), investment, position_amt,
                        entry_price, unrealized_profit, leverage_val, position_side, is_hedge
                    )
                    try:
                        from utils.timestamp_fix import apply_timestamp_fix_to_document
                        fixed_doc = apply_timestamp_fix_to_document(olab_clean_timestamp_values(doc))
                    except Exception:
                        fixed_doc = olab_clean_timestamp_values(doc)
                    cols = list(fixed_doc.keys())
                    placeholders = ", ".join([":" + c for c in cols])
                    cols_str = ", ".join(cols)
                    m1_insert = f"INSERT INTO m1 ({cols_str}) VALUES ({placeholders})"
                    alltraderecords_insert = f"INSERT INTO alltraderecords ({cols_str}) VALUES ({placeholders})"
                    
                    # Run all three inserts in one transaction; rollback if any fails, then retry
                    with _sync_exchange_trades_lock:
                        success = sql_helper.execute_in_transaction(
                            [
                                (exchange_insert, exchange_params),
                                (m1_insert, fixed_doc),
                                (alltraderecords_insert, fixed_doc),
                            ],
                            timeout=15,
                            retries=2,
                            delay=1,
                            tag=f"sync_exchange_{symbol}_{side_str}",
                        )
                    
                    if not success:
                        raise Exception("Transaction failed (exchange_trade + m1 + alltraderecords)")
                    
                    inserted_count += 1
                    _log_hedge_debug(f"STEP 7: INSERT SUCCESS - {symbol} {side_str} unique_id={unique_id[:50]}...")
                    
                except Exception as e:
                    error_msg = f"Error inserting position {symbol} {position_side}: {str(e)}"
                    errors.append(error_msg)
                    _log_hedge_debug(f"STEP 7: INSERT FAILED - {symbol} {position_side}: {error_msg}")
                    olab_log_db_error(e, "olab_sync_exchange_trades", f"symbol={symbol}")
        
        _log_hedge_debug(f"STEP 8: DONE - positions={len(positions)} already_existed={already_existed_count} inserted={inserted_count} errors={len(errors)}")
        return {
            "inserted_count": inserted_count,
            "updated_count": 0,
            "already_existed_count": already_existed_count,
            "errors": errors,
            "hedge_trades": sum(1 for sym, pos_list in positions_by_symbol.items() if len(pos_list) >= 2)
        }
        
    except Exception as e:
        error_msg = f"Error in olab_sync_exchange_trades: {str(e)}"
        errors.append(error_msg)
        _log_hedge_debug(f"STEP FATAL: {error_msg}")
        olab_log_db_error(e, "olab_sync_exchange_trades", "main")
        return {"inserted_count": inserted_count, "updated_count": 0, "already_existed_count": already_existed_count, "errors": errors}


def olab_ensure_income_history_table():
    """Create income_history table (for Binance income/PNL history) if it does not exist."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS income_history (
                        id BIGSERIAL PRIMARY KEY,
                        symbol TEXT,
                        income_type TEXT NOT NULL,
                        income NUMERIC(32, 16) NOT NULL,
                        asset TEXT,
                        info TEXT,
                        time TIMESTAMPTZ NOT NULL,
                        tran_id BIGINT NOT NULL,
                        trade_id TEXT
                    );
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_income_history_type_tran
                    ON income_history (income_type, tran_id);
                    """
                )
            )
    except Exception as e:
        try:
            olab_log_db_error(e, "olab_ensure_income_history_table", "income_history")
        except Exception:
            # Fallback logging if helper is unavailable
            print(f"❌ olab_ensure_income_history_table error: {e}")


def olab_sync_income_history(entries):
    """
    Insert Binance income history rows into income_history with de-duplication.

    entries: list of dicts from client.get_income_history(...) for any incomeType.
    De-duplicates using (income_type, tran_id) which Binance guarantees unique per user.
    """
    if not entries or not isinstance(entries, list):
        return {"inserted": 0, "skipped": 0, "errors": [], "total_received": 0}

    olab_ensure_income_history_table()

    inserted = 0
    skipped = 0
    errors = []

    try:
        with engine.begin() as conn:
            for raw in entries:
                try:
                    income_type = str(
                        raw.get("incomeType")
                        or raw.get("income_type")
                        or ""
                    ).upper()
                    if not income_type:
                        income_type = "UNKNOWN"

                    symbol = (raw.get("symbol") or "").upper() or None
                    income_str = raw.get("income") or "0"
                    try:
                        income_val = float(income_str)
                    except (TypeError, ValueError):
                        income_val = 0.0
                    asset = (raw.get("asset") or "").upper() or None
                    info = raw.get("info") or ""

                    time_ms = raw.get("time") or raw.get("timestamp")
                    if time_ms is None:
                        dt = datetime.now(timezone.utc)
                    else:
                        try:
                            dt = datetime.fromtimestamp(int(time_ms) / 1000.0, tz=timezone.utc)
                        except Exception:
                            dt = datetime.now(timezone.utc)

                    tran_id_raw = raw.get("tranId") or raw.get("tran_id")
                    if tran_id_raw is None:
                        # If tranId missing, treat as non-deduplicated row
                        tran_id = int(dt.timestamp() * 1000)
                    else:
                        tran_id = int(tran_id_raw)

                    trade_id = raw.get("tradeId") or raw.get("trade_id")
                    if trade_id is not None:
                        trade_id = str(trade_id)

                    result = conn.execute(
                        text(
                            """
                            INSERT INTO income_history (
                                symbol, income_type, income, asset, info,
                                time, tran_id, trade_id
                            )
                            VALUES (
                                :symbol, :income_type, :income, :asset, :info,
                                :time, :tran_id, :trade_id
                            )
                            ON CONFLICT (income_type, tran_id) DO NOTHING
                            """
                        ),
                        {
                            "symbol": symbol,
                            "income_type": income_type,
                            "income": income_val,
                            "asset": asset,
                            "info": info,
                            "time": dt,
                            "tran_id": tran_id,
                            "trade_id": trade_id,
                        },
                    )
                    # rowcount is 1 if inserted, 0 if skipped due to conflict
                    if getattr(result, "rowcount", 0) > 0:
                        inserted += 1
                    else:
                        skipped += 1
                except IntegrityError as e:
                    # Unique constraint violation -> treat as skipped
                    if isinstance(getattr(e, "orig", None), UniqueViolation):
                        skipped += 1
                    else:
                        msg = f"IntegrityError in olab_sync_income_history: {e}"
                        errors.append(msg)
                        try:
                            olab_log_db_error(e, "olab_sync_income_history", "insert")
                        except Exception:
                            print(msg)
                except Exception as e:
                    msg = f"Error in olab_sync_income_history for entry: {e}"
                    errors.append(msg)
                    try:
                        olab_log_db_error(e, "olab_sync_income_history", "insert")
                    except Exception:
                        print(msg)
    except Exception as e:
        msg = f"Fatal error in olab_sync_income_history transaction: {e}"
        errors.append(msg)
        try:
            olab_log_db_error(e, "olab_sync_income_history", "transaction")
        except Exception:
            print(msg)

    return {
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "total_received": len(entries),
    }


def olab_get_income_history(limit=1000):
    """
    Read recent income_history rows ordered by time desc.

    Returns a list of dicts ready for JSON serialization.
    """
    olab_ensure_income_history_table()

    try:
        limit_val = int(limit)
        if limit_val <= 0:
            limit_val = 1000
    except (TypeError, ValueError):
        limit_val = 1000

    rows_out = []
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT
                        symbol,
                        income_type,
                        income,
                        asset,
                        info,
                        time,
                        tran_id,
                        trade_id
                    FROM income_history
                    ORDER BY time DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit_val},
            )
            for row in result.mappings():
                time_val = row.get("time")
                if hasattr(time_val, "isoformat"):
                    time_serialized = time_val.isoformat()
                else:
                    time_serialized = str(time_val) if time_val is not None else None

                income_val = row.get("income")
                try:
                    income_serialized = float(income_val) if income_val is not None else 0.0
                except (TypeError, ValueError):
                    income_serialized = 0.0

                rows_out.append(
                    {
                        "symbol": row.get("symbol"),
                        "income_type": row.get("income_type"),
                        "income": income_serialized,
                        "asset": row.get("asset"),
                        "info": row.get("info"),
                        "time": time_serialized,
                        "tran_id": row.get("tran_id"),
                        "trade_id": row.get("trade_id"),
                    }
                )
    except Exception as e:
        try:
            olab_log_db_error(e, "olab_get_income_history", f"limit={limit}")
        except Exception:
            print(f"❌ olab_get_income_history error: {e}")

    return rows_out

# print(get_cnt_pl_more_than_sixty('SELL', 20,5))