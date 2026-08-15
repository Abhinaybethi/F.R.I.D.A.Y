"""
UNIT TEST — Phase 22 Active Memory & Personalization System
============================================================
Tests preference resolution, categories, and memory updates in friday/tools/memory.py.
"""
from friday.tools.memory import remember, recall, forget, resolve_preference, _get_db_path
import sqlite3
from contextlib import closing


def test_active_preference_resolution():
    # Save a preference memory (dry_run=False to test persistence & querying)
    remember("my favorite browser is Chrome", category="preference", key_name="browser", dry_run=False)

    try:
        pref = resolve_preference("browser")
        assert pref == "Chrome"

        res = recall("favorite browser")
        assert res["success"]
        assert "Chrome" in res["message"]
    finally:
        # Cleanup
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE content LIKE '%favorite browser%'")


def test_memory_deduplication_and_categories():
    r1 = remember("my Wi-Fi password is 123", category="credential", dry_run=False)
    r2 = remember("my Wi-Fi password is 123", category="credential", dry_run=False)
    assert r2.get("duplicate") is True

    try:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category FROM memories WHERE content LIKE '%Wi-Fi%'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "credential"
    finally:
        with closing(sqlite3.connect(_get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM memories WHERE content LIKE '%Wi-Fi%'")
