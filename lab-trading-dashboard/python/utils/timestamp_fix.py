#!/usr/bin/env python3
"""
Timestamp Fix for PostgreSQL Database Issues
Fixes 'NONE' string values that should be NULL for timestamp fields
"""

def fix_timestamp_none_values(data):
    """
    Convert 'NONE' strings to None for timestamp and datetime fields
    This fixes PostgreSQL invalid timestamp format errors
    """
    if isinstance(data, dict):
        cleaned = {}
        timestamp_fields = [
            'operator_trade_time', 
            'operator_close_time', 
            'candel_time', 
            'fetcher_trade_time',
            'timestamp',
            'created_at',
            'updated_at',
            'trade_time',
            'close_time'
        ]
        
        for key, value in data.items():
            if isinstance(value, str) and value.upper() == 'NONE':
                # Check if this is a timestamp field
                if any(ts_field in key.lower() for ts_field in timestamp_fields):
                    cleaned[key] = None  # Convert to NULL
                    print(f"🔧 Fixed timestamp field {key}: 'NONE' → NULL")
                else:
                    cleaned[key] = value  # Keep as string for non-timestamp fields
            elif isinstance(value, (dict, list)):
                cleaned[key] = fix_timestamp_none_values(value)
            else:
                cleaned[key] = value
        return cleaned
    elif isinstance(data, list):
        return [fix_timestamp_none_values(item) for item in data]
    else:
        return data

def apply_timestamp_fix_to_document(document):
    """
    Apply timestamp fixes to a trade document before database insertion
    """
    if not document:
        return document
    
    # Apply the fix
    fixed_document = fix_timestamp_none_values(document)
    
    # Log the changes
    changes_made = []
    for key, value in document.items():
        if isinstance(value, str) and value.upper() == 'NONE':
            if fixed_document.get(key) is None:
                changes_made.append(f"{key}: '{value}' → NULL")
    
    if changes_made:
        print(f"🔧 Timestamp fixes applied: {', '.join(changes_made)}")
    
    return fixed_document

if __name__ == "__main__":
    # Test the function
    test_document = {
        'machineid': 'M1',
        'operator_trade_time': 'NONE',
        'operator_close_time': 'NONE',
        'candel_time': '2025-08-23 13:30:00',
        'fetcher_trade_time': '2025-08-23 14:13:20',
        'pair': 'PIPPINUSDT',
        'action': 'BUY'
    }
    
    print("Original document:")
    print(test_document)
    
    fixed_document = apply_timestamp_fix_to_document(test_document)
    
    print("\nFixed document:")
    print(fixed_document)


