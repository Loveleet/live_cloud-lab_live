# anish m1
anishm1_api='3i2ZW2WqaU3bckPJN6E6JwBewelLOGDImNNA4z5PrcT3TZXvha4VwDYPr6z8xMOn'
anishm1_secret='hSVSyIDVNzpbyKAVPq8X4AJQ8NAkiUQMhT2UZDnw76rBUFDgJnXIA435J9KAXUC8'

# anish m2
anishm2_api='seSpIhGqzKPaDMQSX2fBkj5HfOyss1dUPyhwN6zfqTmUQLYSOsvtzBZ6uWN0svgV'
anishm2_secret='GQ3sn0TjR9VEDn3lBipDRmaGxoU9BercHNVZYOEaleneTVsd1gFZMv7FiIwa4iO9'

M3_api = 'eIWajxTqaT8l7LkoyNUQBbTV447ZwfZh2lSbS9wQTn2TEtHnEjIBbARZtU8twQnj'
M3_secret = 'HKXTKyiqDsvblmkzBiQ1s2D4CUh2hHJIjzxu4Y6DM4M5hz2Kbs2xmowXVZrP1LdD'

M4_api= 'Pi1VQWPhUiNUVigmHepoaOKG53NhroN0stwqYcTnLDosz8G9SrWJTxlOHzTD5LHr'
M4_secret= 'nGk5dOAYTnAaxVnRDhXxegaCdGYEyzGAxx53ryeWDIob1XXAMlazDQGO8mFEIYJS'


api='d8d0107edbc3794599efcbd9ae6b640bf46241b48d866edc806df65f0b6dbc22'
secret='476a347161016506113c608fdd621a502e3e72b786f126f4da10af2a9f9335c2'

# PostgreSQL Connection Strings
# Format: postgresql://username:password@host:port/database

# # Primary PostgreSQL connection string
connection_string_postgresql = "postgresql://lab:IndiaNepal1-@150.241.244.130:5432/labdb2"

connection_string_postgresql_backtest_db  = "postgresql://lab:IndiaNepal1-@127.0.0.1:5432/backtestdb"
# connection_string_postgresql_backtest_db  = "postgresql://lab:IndiaNepal1-@150.241.244.130:5432/backtestdb"

# # Backup PostgreSQL connection strings
# connection_string_postgresql_backup1 = "postgresql://lab:IndiaNepal1-@150.241.244.23:5432/labdb2"

# connection_string_postgresql_backup2 = "postgresql://lab:IndiaNepal1-@150.241.244.23:5432/labdb2"


# Primary PostgreSQL connection string
# connection_string_postgresql = "postgresql://lab:IndiaNepal1-@127.0.0.1:5432/labdb2"

# Backup PostgreSQL connection strings
connection_string_postgresql_backup1 = "postgresql://lab:IndiaNepal1-@127.0.0.1:5432/labdb2"

connection_string_postgresql_backup2 = "postgresql://lab:IndiaNepal1-@127.0.0.1:5432/labdb2"

# For compatibility with existing code, keep the old variable name but point to PostgreSQL
connection_string = connection_string_postgresql

# PostgreSQL-specific configuration
POSTGRESQL_CONFIG = {
    'host': '127.0.0.1',
    'port': 5432,
    'database': 'labdb2',
    'user': 'lab',
    'password': 'IndiaNepal1-',
    'connect_timeout': 300,
    'application_name': 'TradingBot'
}

# Connection pool settings for PostgreSQL
POSTGRESQL_POOL_CONFIG = {
    'pool_size': 50,
    'max_overflow': 20,
    'pool_timeout': 60,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}

