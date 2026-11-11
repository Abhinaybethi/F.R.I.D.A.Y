"""Retrieval tests: keyword, date, topic, episodes, semantic and RRF hybrid."""
from __future__ import annotations

import sqlite3

from friday.memory import retrieval
from friday.memory.service import MemoryService


def _service(tmp_path, **overrides):
    config = {
        "db_path": str(tmp_path / "memory.db"),
        "vector_enabled": False,
        "summaries_enabled": False,
        "dedupe_window_seconds": 0,
    }
    config.update(overrides)
    return MemoryService.from_config(config, source="test", vector_worker=False)


class FakeVectors:
    enabled = True

    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def search(self, query, k=20, session_id=None):
        self.calls.append((query, k, session_id))
        return list(self.hits)


def test_keyword_date_and_topic_filters(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    jan = service.record_turn(
        "quarterly budget review",
        "Numbers attached.",
        session_id=sid,
        topic="finance",
        created_at="2026-01-15T10:00:00Z",
    )
    service.record_turn(
        "holiday plans",
        "Beach?",
        session_id=sid,
        topic="travel",
        created_at="2026-03-20T10:00:00Z",
    )

    same_day = service.search(
        "budget", mode="keyword", from_ts="2026-01-15", to_ts="2026-01-15"
    )
    assert same_day["count"] == 1
    assert same_day["results"][0]["id"] == jan.id

    out_of_range = service.search(
        "budget", mode="keyword", from_ts="2026-02-01", to_ts="2026-02-28"
    )
    assert out_of_range["count"] == 0

    topic = service.search("", mode="keyword", topic="travel")
    assert topic["count"] == 1
    assert topic["results"][0]["raw_text"] == "holiday plans"

    voice_sid = service.start_session(session_id="voice-session", source="voice")
    assert voice_sid == "voice-session"
    service.record_turn("budget check", "ok", session_id=voice_sid)
    by_source = service.search("budget", mode="keyword", source="test")
    assert by_source["count"] == 1
    assert all(item["session"]["source"] == "test" for item in by_source["results"])
    assert service.search("budget", mode="keyword")["count"] == 2
    service.close()


def test_keyword_search_falls_back_to_like_when_fts_errors(tmp_path, monkeypatch):
    service = _service(tmp_path)
    sid = service.start_session()
    service.record_turn("fallback needle", "found it", session_id=sid)

    original = service.store.query

    def flaky(sql, params=()):
        if "messages_fts MATCH" in sql:
            raise sqlite3.OperationalError("fts unavailable")
        return original(sql, params)

    monkeypatch.setattr(service.store, "query", flaky)
    result = service.search("needle", mode="keyword")
    assert result["count"] == 1
    assert result["results"][0]["match"] == "keyword"
    service.close()


def test_semantic_search_uses_vector_hits(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    first = service.record_turn("the sky is blue", "Yes.", session_id=sid)
    second = service.record_turn("grass is green", "Correct.", session_id=sid)

    service.vectors = FakeVectors([{"id": second.id, "score": 0.91, "metadata": {}}])
    result = service.search("colour of plants", mode="semantic")
    assert result["count"] == 1
    assert result["results"][0]["id"] == second.id
    assert result["results"][0]["match"] == "semantic"
    assert result["semantic_count"] == 1
    assert result["vector_available"] is True
    service.close()


def test_hybrid_merge_uses_reciprocal_rank_fusion(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    first = service.record_turn("database index tuning", "Use an index.", session_id=sid)
    second = service.record_turn("database backup plan", "Nightly.", session_id=sid)

    service.vectors = FakeVectors(
        [
            {"id": second.id, "score": 0.95, "metadata": {}},
            {"id": first.id, "score": 0.80, "metadata": {}},
        ]
    )
    result = service.search("database", mode="hybrid")
    ids = [item["id"] for item in result["results"]]
    assert set(ids) == {first.id, second.id}
    assert all(item["match"] == "hybrid" for item in result["results"])
    assert result["keyword_count"] >= 1
    assert result["semantic_count"] == 2
    service.close()


def test_merge_hybrid_handles_one_sided_inputs():
    keyword = [{"id": "a", "match": "keyword", "score": 1.0}]
    semantic = [{"id": "b", "match": "semantic", "score": 0.9}]
    assert [r["id"] for r in retrieval.merge_hybrid(keyword, [], 10)] == ["a"]
    assert [r["id"] for r in retrieval.merge_hybrid([], semantic, 10)] == ["b"]
    merged = retrieval.merge_hybrid(keyword, semantic, 10)
    assert {r["id"] for r in merged} == {"a", "b"}


def test_episode_search_keeps_source_reference(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    turn = service.record_turn("open chrome", "Chrome is open.", session_id=sid)

    episodes = service.search_episodes("chrome")
    assert episodes
    assert episodes[0]["source_message_id"] == turn.id
    assert episodes[0]["occurred_at"] == turn.created_at
    assert episodes[0]["kind"] == "turn"
    service.close()
