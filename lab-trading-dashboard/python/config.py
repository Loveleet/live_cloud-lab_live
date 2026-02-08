# config.py

# ✅ MACHINE IDS - List of all machines to run
MACHINE_IDS = ["M2"]

# ✅ Machine Launcher Settings
LAUNCHER_CONFIG = {
    "max_concurrent_machines": 3,  # Maximum number of machines to run simultaneously
    "restart_delay": 30,  # Seconds to wait before restarting a crashed machine
    "log_level": "INFO",  # Logging level for launcher
}

# ✅ SQL Connection (if needed for log saving)
DB_CONFIG = {
    "driver": "ODBC Driver 18 for SQL Server",
    "server": "localhost",
    "database": "trading",
    "uid": "sa",
    "pwd": "your_password_here",
}

# ✅ Log Table Name
LOG_TABLE_NAME = "BotLogs"

# ✅ Timezone Settings
TIMEZONE = "UTC"

# ✅ Global Constants
PRINT_INTERVAL = 10  # seconds
SWING_REFRESH_INTERVAL = 300  # seconds