# machine_id.py
# Global machine ID that will be set by the launcher

MACHINE_ID = None

def set_machine_id(machine_id):
    """Set the global machine ID"""
    global MACHINE_ID
    MACHINE_ID = machine_id

def get_machine_id():
    """Get the current machine ID"""
    global MACHINE_ID
    return MACHINE_ID
