"""Storage-level tests for persistent memory (schema, FTS, backup, isolation)."""
from __future__ import annotations

import sqlite3

from friday.memory.schema import SCHEMA_VERSION
from friday.memory.service import MemoryService
from friday.memory.store import MemoryStore


def _service(tmp_path, **kwargs):
    cfg = {
        "db_path": str(tmp_path / "memory.db"),
        "vector_enabled": False,
        "summaries_enabled": True,
        "dedupe_window_seconds": 0,
    }
    cfg.update(kwargs.pop("config", {}))
    service = MemoryService.from_config(cfg, source="test", vector_worker=False, **kwargs)
    return service


def test_schema_creates_all_tables_and_version(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.db"))
    store.initialize()
    with store.connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
    assert version == SCHEMA_VERSION
    for table in (
        "sessions",
        "messages",
        "summaries",
        "episodes",
        "facts",
        "fact_revisions",
        "tasks",
        "task_steps",
        "messages_fts",
    ):
        assert table in names


def test_fts_triggers_track_insert_update_delete(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    turn = service.record_turn("alpha bravo", "first answer", session_id=sid)
    assert service.search("alpha", mode="keyword")["count"] == 1

    service.store.execute(
        "UPDATE messages SET raw_text = ?, response_text = ? WHERE id = ?",
        ("charlie delta", "updated answer", turn.id),
    )
    assert service.search("alpha", mode="keyword")["count"] == 0
    assert service.search("charlie", mode="keyword")["count"] == 1
    assert service.search("updated", mode="keyword")["count"] == 1

    service.store.execute("DELETE FROM messages WHERE id = ?", (turn.id,))
    assert service.search("updated", mode="keyword")["count"] == 0
    service.close()


def test_deleting_session_cascades_turns_and_episodes(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    service.record_turn("remember this", "stored", session_id=sid)
    assert service.store.count("messages") == 1
    assert service.store.count("episodes") >= 1

    result = service.delete_session(sid)
    assert result["deleted"] is True
    assert service.store.count("messages") == 0
    assert service.store.count("episodes") == 0
    assert service.store.query_one("SELECT id FROM sessions WHERE id = ?", (sid,)) is None
    service.close()


def test_legacy_memories_table_is_preserved(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO memories (key, value) VALUES ('name', 'Abhinav')")
        conn.commit()

    store = MemoryStore(str(db_path))
    store.initialize()
    row = store.query_one("SELECT value FROM memories WHERE key = 'name'")
    assert row["value"] == "Abhinav"
    assert store.count("messages") == 0
    store.close()


def test_backup_and_restore_round_trip(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    service.record_turn("before backup", "ok", session_id=sid)
    backup_path = str(tmp_path / "backup.db")
    assert service.backup(backup_path) == backup_path
    assert service.integrity_check() == "ok"

    service.record_turn("after backup", "ok", session_id=sid)
    assert service.store.count("messages") == 2

    assert service.restore(backup_path) is True
    assert service.store.count("messages") == 1
    # Restored connections still work and remain writeable.
    service.record_turn("after restore", "ok", session_id=sid)
    assert service.store.count("messages") == 2
    service.close()
