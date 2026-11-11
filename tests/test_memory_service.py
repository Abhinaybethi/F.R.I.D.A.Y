"""Service-level tests for recording, dedupe, summaries, facts and retention."""
from __future__ import annotations

import pytest

from friday.memory.service import MemoryService


def _service(tmp_path, **overrides):
    config = {
        "db_path": str(tmp_path / "memory.db"),
        "vector_enabled": False,
        "summaries_enabled": True,
        "dedupe_window_seconds": 0,
    }
    config.update(overrides)
    return MemoryService.from_config(config, source="test", vector_worker=False)


def test_start_and_end_session(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session(title="Morning")
    assert sid
    assert service.current_session_id == sid
    assert service.ensure_session() == sid

    result = service.end_session()
    assert result["session_id"] == sid
    assert result["ended_at"]
    assert service.current_session_id is None
    assert service.ensure_session() not in (None, sid)
    service.close()


def test_record_turn_is_idempotent_for_stable_message_id(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    first = service.record_turn("hello friday", "Hi.", session_id=sid, message_id="turn-1")
    second = service.record_turn("hello friday", "Hi.", session_id=sid, message_id="turn-1")
    assert first.id == second.id
    assert service.store.count("messages") == 1
    service.close()


def test_short_window_duplicate_is_ignored(tmp_path):
    service = _service(tmp_path, dedupe_window_seconds=60)
    sid = service.start_session()
    first = service.record_turn("repeat me", "Same answer.", session_id=sid)
    duplicate = service.record_turn("repeat me", "Same answer.", session_id=sid)
    assert duplicate.id == first.id
    assert service.store.count("messages") == 1

    different = service.record_turn("repeat me", "Different answer.", session_id=sid)
    assert different.id != first.id
    assert service.store.count("messages") == 2
    service.close()


def test_turn_indexes_are_monotonic_and_recording_never_raises(tmp_path, monkeypatch):
    service = _service(tmp_path)
    sid = service.start_session()
    a = service.record_turn("one", "1", session_id=sid)
    b = service.record_turn("two", "2", session_id=sid)
    assert (a.turn_index, b.turn_index) == (0, 1)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service.store, "transaction", boom)
    assert service.record_turn("three", "3", session_id=sid) is None
    service.close()


def test_session_title_summary_and_raw_history_are_separate(tmp_path):
    service = _service(tmp_path, summary_min_turns=2)
    sid = service.start_session()
    service.record_turn("plan the trip", "Let us plan.", session_id=sid)
    service.record_turn("book a hotel", "Which city?", session_id=sid)

    payload = service.get_session(sid)
    assert payload["session"]["title"] == "plan the trip"
    assert len(payload["turns"]) == 2
    assert payload["summaries"] == []

    ended = service.end_session()
    assert ended["summary"] is not None
    payload = service.get_session(sid)
    assert len(payload["turns"]) == 2, "raw turns must not be replaced by a summary"
    assert len(payload["summaries"]) == 1
    assert payload["summaries"][0]["generated_by"] == "extractive"
    assert payload["summaries"][0]["source_message_ids"]
    service.close()


def test_keyword_search_finds_past_turns(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    service.record_turn("open chrome then search for rust", "Chrome opened.", session_id=sid)
    service.record_turn("what about tea", "Tea is nice.", session_id=sid)

    result = service.search("chrome", mode="keyword")
    assert result["count"] == 1
    hit = result["results"][0]
    assert hit["raw_text"] == "open chrome then search for rust"
    assert hit["session"]["id"] == sid
    assert hit["created_at"]
    service.close()


def test_facts_are_audited_correctable_and_restorable(tmp_path):
    service = _service(tmp_path)
    fact = service.upsert_fact("user", "favourite_drink", "coffee")
    assert fact is not None and fact.deleted_at is None

    corrected = service.correct_fact(
        fact.id, object_value="tea", reason="User corrected it"
    )
    assert corrected.object == "tea"

    detail = service.get_fact(fact.id)
    assert len(detail["revisions"]) == 1
    assert detail["revisions"][0]["old_object"] == "coffee"

    updated = service.upsert_fact("user", "favourite_drink", "matcha")
    assert updated.id == fact.id
    assert len(service.get_fact(fact.id)["revisions"]) == 2

    assert service.delete_fact(fact.id) is True
    assert service.list_facts()["count"] == 0
    assert service.restore_fact(fact.id) is True
    assert service.list_facts()["count"] == 1
    service.close()


def test_secret_looking_facts_are_rejected(tmp_path):
    service = _service(tmp_path)
    assert service.upsert_fact("user", "api_key", "sk-abcdefghijklmnopqrstuvwxyz0123456789") is None
    assert service.list_facts()["count"] == 0
    service.close()


def test_stats_and_prune_dry_run_then_real(tmp_path):
    service = _service(tmp_path)
    old_sid = service.start_session()
    service.record_turn("old memory", "ok", session_id=old_sid)
    service.end_session()
    service.store.execute(
        "UPDATE sessions SET started_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00Z", old_sid),
    )
    new_sid = service.start_session()
    service.record_turn("new memory", "ok", session_id=new_sid)

    stats = service.stats()
    assert stats["sessions"] == 2
    assert stats["messages"] == 2

    dry = service.prune(dry_run=True, retention_days=1)
    assert dry["deleted"] == 0 and dry["would_delete"] == 1
    assert service.store.count("sessions") == 2

    real = service.prune(dry_run=False, retention_days=1)
    assert real["deleted"] == 1
    assert service.store.count("sessions") == 1
    assert service.search("old memory", mode="keyword")["count"] == 0
    service.close()


def test_disabled_memory_is_a_noop(tmp_path):
    service = _service(tmp_path, enabled=False)
    assert service.stats() == {"enabled": False, "source": "test"}
    assert service.start_session() is None
    assert service.record_turn("hello", "hi") is None
    assert service.search("hello")["results"] == []
    assert service.list_sessions()["sessions"] == []
    assert service.list_facts()["facts"] == []
    assert service.list_tasks() == []
    assert service.backup(str(tmp_path / "nope.db")) is None
    service.close()
