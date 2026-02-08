# utils/database.py
import sys
import os

# ✅ Adjust path to where FinalVersionTradingDB_postgreSql.py is located
# Linux-compatible path - using current directory
custom_path = os.path.dirname(os.path.abspath(__file__))
if custom_path not in sys.path:
    sys.path.append(custom_path)



from utils.Final_olab_database import (
    # insert_bot_log,
    olab_fetch_data_from_machine,
    olab_update_table_from_all_pairs,
    olab_update_single_uid_in_table
)

class SQLAccessHelper:
    def __init__(self):
        pass  # Engine setup is managed in FinalVersionTradingDB_postgresql.py

    # def insert_log(self, uid, source, message, timestamp):
    #     try:
    #         insert_bot_log(uid, source, message, timestamp)
    #     except Exception as e:
    #         print(f"❌ DB Insert Error: {e}")

    def fetch_data_from_sql(self, machine_id, app_start):
       
        raw_list = olab_fetch_data_from_machine(machine_id, app_start)
        

        # ✅ Convert list of dicts → dict keyed by UID
        data_by_uid = {}
        for row in raw_list:
           
            uid = row.get("Unique_id")
            if uid:
                data_by_uid[uid] = row
        print(data_by_uid)
        return data_by_uid


    def update_all(self, all_pairs, machine_id):
        olab_update_table_from_all_pairs(all_pairs, machine_id)

    def update_uid(self, uid, all_pairs, machine_id):
        olab_update_single_uid_in_table(uid, all_pairs, machine_id)
