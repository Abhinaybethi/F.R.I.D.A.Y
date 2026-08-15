import pytest
import os
import time
from pathlib import Path
from friday.tools.files import find_file, _SAFE_DIRS

@pytest.fixture
def mock_safe_dirs(tmp_path, monkeypatch):
    test_docs = tmp_path / "Documents"
    test_docs.mkdir()
    
    # Create files
    f1 = test_docs / "old_resume.pdf"
    f1.write_text("old")
    # set mtime old
    os.utime(f1, (time.time() - 1000, time.time() - 1000))
    
    f2 = test_docs / "new_resume.pdf"
    f2.write_text("new")
    os.utime(f2, (time.time(), time.time()))
    
    f3 = test_docs / "notes.txt"
    f3.write_text("txt")
    os.utime(f3, (time.time() - 500, time.time() - 500))

    monkeypatch.setattr("friday.tools.files._SAFE_DIRS", {"documents": test_docs})
    return test_docs

def test_find_file_recency(mock_safe_dirs):
    res = find_file("resume")
    assert res["success"] is True
    # Should be new_resume.pdf first
    assert "new_resume.pdf" in res["candidates"][0]
    assert "old_resume.pdf" in res["candidates"][1]

def test_find_file_type_extraction(mock_safe_dirs):
    res = find_file("latest resume pdf")
    assert res["success"] is True
    # Only pdfs should match
    assert len(res["candidates"]) == 2
    assert "new_resume.pdf" in res["candidates"][0]

def test_find_file_implied_type_no_name(mock_safe_dirs):
    res = find_file("latest txt")
    assert res["success"] is True
    assert len(res["candidates"]) == 1
    assert "notes.txt" in res["candidates"][0]
