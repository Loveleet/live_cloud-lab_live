# data_handler.py

from utils.Final_olab_database import olab_fetch_data_from_machine,olab_fetch_hedge_data_from_machine
from decimal import Decimal

class DataHandler:
    def __init__(self):
        pass

    def load_initial_data(self, machine_id, app_start):
        print(f"📦 Fetching data for: {machine_id}, app_start={app_start}")
        raw_data = olab_fetch_data_from_machine(machine_id, app_start)
        #raw_data = fetch_hedge_data_from_machine(machine_id, app_start)
        print(f'machine_id: {machine_id}, app_start: {app_start}')
        print(f'raw_data: {raw_data}')

        if not raw_data:
            print("⚠️ No data found. Returning empty dict.")
            return {}

        filtered_data = [item for item in raw_data if item.get("type") != "close"]

        uid_map = {}
        for item in filtered_data:
            uid = item.get("unique_id")
            if uid:
                uid_map[uid] = {
                    key: float(value) if isinstance(value, Decimal) else value
                    for key, value in item.items()
                }

            # print("✅ UID mapping created:", uid)
        return uid_map

    def load_running_uids(self, machine_id):
        # print(f"📦 Loading RUNNING UIDs for: {machine_id}")
        raw_data = olab_fetch_data_from_machine(machine_id, app_start=True)
        #raw_data = fetch_hedge_data_from_machine(machine_id, app_start=True)
        
        
        if not raw_data:
            # print("⚠️ No running data found.")
            return {}

        filtered_data = [item for item in raw_data if item.get("type") != "close"]

        uid_map = {}
        for item in filtered_data:
            uid = item.get("unique_id")
            if uid:
                uid_map[uid] = {
                    key: float(value) if isinstance(value, Decimal) else value
                    for key, value in item.items()
                }

        # print("✅ Running UID map:", uid_map)
        return uid_map
