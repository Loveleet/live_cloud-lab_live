# utils/global_store.py

# ✅ Shared dictionary to store live signal data per UID
from threading import Lock, Event

message_queues={}
test_threads={}

# utils/global_store.py

last_3min_check_time = {}  # To track the last time 3-min checks were done per UID
last_added_invest_check_time = {}


swing_proximity_flags_hedge_release = {}
swing_proximity_flags_hedge_close ={}

# ✅ Optional: other shared global structures
analysis_tracker = {}
all_pairs = {}
all_pairs_locks  = {}
all_pairs_lock = Lock()  # Added missing lock for all_pairs
analysis_tracker_locks = {}
# utils/global_store.py

# Add shutdown event for graceful shutdown
shutdown_event = Event()  # Added missing shutdown event

# utils/global_store.py

high_and_low_swings = {} 
active_threads ={}
last_heartbeat ={}
last_5min_check_time = {}
get_default_analysis_tracker={}
high_and_low_swings_locks ={}
log_lock = Lock()

last_update_time_signal_data ={}

# Add these
simulation_running_flags = {}         # UID -> threading.Event()
simulation_flags_lock = Lock()
last_simulation_time = {}  # uid: timestamp
simulation_thread_monitor = {}  # uid: start_time for monitoring hanging simulations
simulation_timeout = 60  # seconds

buy_active_loss = False
sell_active_loss = False



