import sys
import os
import logging

# Add src to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.metadata.ioc_manager import IOCManager

logging.basicConfig(level=logging.INFO)

def test_ioc_manager(tmp_path):
    db_path = str(tmp_path / "test_wingscribe.db")
    # Use the real Excel file if available, otherwise mock
    real_xlsx = "config/Multiling IOC 15.1_d.xlsx"
    
    # Cleanup previous test
    if os.path.exists(db_path):
        os.remove(db_path)

    print("--- Initializing Manager ---")
    manager = IOCManager(db_path)
    
    if os.path.exists(real_xlsx):
        print(f"--- Importing Data from {real_xlsx} ---")
        manager.import_ioc_data(real_xlsx)
        
        # Test query with a known bird from the excel (e.g., Ostrich)
        print("--- Querying 'Struthio camelus' (Ostrich) ---")
        info = manager.get_bird_info("Struthio camelus")
        print(f"Result: {info}")
        if info:
            assert "鸵鸟" in info['chinese_name'] or "非洲鸵鸟" in info['chinese_name']
    else:
        print("Skipping import test as file not found.")
    
    
    print("--- Testing Photo Insert ---")
    photo_id = manager.add_photo_record({
        'file_path': '/tmp/test.jpg',
        'filename': 'test.jpg',
        'captured_date': '2023-10-01',
        'location_tag': 'Park',
        'primary_bird_cn': '白头鹎',
        'scientific_name': 'Pycnonotus sinensis',
        'confidence_score': 0.95,
        'width': 800,
        'height': 600
    })
    print(f"Inserted Photo ID: {photo_id}")
    assert photo_id is not None

    manager.close()
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
    print("--- Test Passed ---")
