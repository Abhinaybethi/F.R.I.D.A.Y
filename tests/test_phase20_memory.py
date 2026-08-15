import pytest
import os
import sqlite3
from friday.tools.memory import remember, recall, forget, _get_db_path, _init_db

@pytest.fixture(autouse=True)
def clean_memory_db():
    db_path = _get_db_path()
    # Clean up before
    if os.path.exists(db_path):
        os.remove(db_path)
    
    _init_db()
    
    yield
    
    # Clean up after
    if os.path.exists(db_path):
        os.remove(db_path)

def test_memory_dry_run():
    res = remember("My favorite color is blue", dry_run=True)
    assert res["success"] is True
    
    # Verify it was not actually saved
    recall_res = recall("favorite color")
    assert recall_res["success"] is False

def test_memory_real_execution():
    res = remember("My favorite color is blue", dry_run=False)
    assert res["success"] is True
    
    # Recall
    recall_res = recall("favorite color")
    assert recall_res["success"] is True
    assert "blue" in recall_res["message"]
    
    # Forget
    forget_res = forget("favorite color", dry_run=False)
    assert forget_res["success"] is True
    
    # Recall again
    recall_res2 = recall("favorite color")
    assert recall_res2["success"] is False

def test_memory_secret_filtering():
    # Should block saving anything looking like an API key or password
    res1 = remember("My password: super_secret_123", dry_run=False)
    assert res1["success"] is False
    assert res1.get("blocked") is True
    
    res2 = remember("My openai api key is sk-123456789012345678901234567890123", dry_run=False)
    assert res2["success"] is False
    assert res2.get("blocked") is True
