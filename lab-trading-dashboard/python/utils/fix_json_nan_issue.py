import json
import numpy as np
import pandas as pd

def clean_json_for_postgresql(data):
    """
    Clean JSON data to remove NaN values that PostgreSQL doesn't accept
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if pd.isna(value) or (isinstance(value, float) and np.isnan(value)):
                cleaned[key] = None
            elif isinstance(value, (dict, list)):
                cleaned[key] = clean_json_for_postgresql(value)
            else:
                cleaned[key] = value
        return cleaned
    elif isinstance(data, list):
        return [clean_json_for_postgresql(item) for item in data]
    elif pd.isna(data) or (isinstance(data, float) and np.isnan(data)):
        return None
    else:
        return data

def safe_json_dumps(data):
    """
    Safely convert data to JSON string, handling NaN values
    """
    cleaned_data = clean_json_for_postgresql(data)
    return json.dumps(cleaned_data, default=str)


