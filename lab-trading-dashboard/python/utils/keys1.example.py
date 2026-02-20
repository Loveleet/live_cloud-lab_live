# Copy to keys1.py and fill in real values. Do NOT commit keys1.py (it is in .gitignore).

# Binance API (one set active; others commented)
# api = 'your_binance_api_key'
# secret = 'your_binance_secret'

# api='...'
# secret='...'

api = 'YOUR_BINANCE_API_KEY'
secret = 'YOUR_BINANCE_SECRET'

# Optional: multiple machine keys
# anishm1_api = '...'
# anishm1_secret = '...'
# anishm2_api = '...'
# anishm2_secret = '...'
# M3_api = '...'
# M3_secret = '...'
# M4_api = '...'
# M4_secret = '...'

# SQL Server connection (if used)
connection_string = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    "SERVER=YOUR_SERVER,1433;"
    'DATABASE=labDB2;'
    'UID=lab;'
    'PWD=YOUR_PASSWORD;'
    'Connection Timeout=120;'
)

connection_string_labdb2 = connection_string  # or override
connection_string1 = connection_string       # or override
