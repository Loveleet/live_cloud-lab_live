kk
# Copy to keys1_postgresql.py and fill in real values. Do NOT commit keys1_postgresql.py (it is in .gitignore).

# Binance API (same as keys1.example.py if needed)
api = 'YOUR_BINANCE_API_KEY'
secret = 'YOUR_BINANCE_SECRET'

# Optional: multiple machine keys
# anishm1_api = '...'
# anishm1_secret = '...'
# ... etc.

# PostgreSQL connection string
# Format: postgresql://username:password@host:port/database
connection_string_postgresql = "postgresql://lab:YOUR_PASSWORD@YOUR_HOST:5432/labdb2"

# connection_string_postgresql_backtest_db = "postgresql://lab:YOUR_PASSWORD@127.0.0.1:5432/backtestdb"

connection_string = connection_string_postgresql

# PostgreSQL config dict (optional)
POSTGRESQL_CONFIG = {
    'host': '127.0.0.1',
    'port': 5432,
    'database': 'labdb2',
    'user': 'lab',
    'password': 'YOUR_PASSWORD',
    'connect_timeout': 300,
    'application_name': 'TradingBot'
}

POSTGRESQL_POOL_CONFIG = {
    'pool_size': 50,
    'max_overflow': 20,
    'pool_timeout': 60,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}
