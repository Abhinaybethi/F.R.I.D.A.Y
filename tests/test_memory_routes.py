"""HTTP API tests for the persistent memory routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from friday.web import metrics as metrics_mod
from friday.web.app import create_app
from friday.web.runtime import DashboardRuntime, reset_runtime


CONFIG = """
wake_word: "friday"
tools:
  dry_run: true
  allow_real_execution: false
reasoning:
  provider: llamacpp
  endpoint: "http://127.0.0.1:9"
rag:
  enabled: false
memory:
  enabled: true
  db_path: "{db_path}"
  vector_enabled: false
  summaries_enabled: true
  dedupe_window_seconds: 0
"""


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        CONFIG.format(db_path=(tmp_path / "memory.db").as_posix()), encoding="utf-8"
    )
    monkeypatch.setattr(metrics_mod, "prime_cpu", lambda: None)
    rt = DashboardRuntime(
        config_path=str(config_path),
        activity_path=str(tmp_path / "activity.json"),
    )
    reset_runtime(rt)
    yield rt
    reset_runtime(None)


@pytest.fixture()
def client(runtime):
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def seeded(runtime):
    memory = runtime.memory_service()
    sid = memory.start_session(title="Test session")
    first = memory.record_turn(
        "open chrome and search rust", "Chrome is open.", session_id=sid
    )
    second = memory.record_turn(
        "remind me about the report", "Noted.", session_id=sid
    )
    return {"memory": memory, "session_id": sid, "first": first, "second": second}


def test_stats_and_sessions(client, seeded):
    stats = client.get("/api/memory/stats").json()
    assert stats["enabled"] is True
    assert stats["sessions"] == 1
    assert stats["messages"] == 2
    assert stats["vector"]["enabled"] is False

    listing = client.get("/api/memory/sessions").json()
    assert listing["count"] == 1
    assert listing["sessions"][0]["id"] == seeded["session_id"]
    assert listing["sessions"][0]["turn_count"] == 2


def test_session_detail_and_delete(client, seeded):
    sid = seeded["session_id"]
    detail = client.get(f"/api/memory/sessions/{sid}").json()
    assert detail["session"]["id"] == sid
    assert [t["raw_text"] for t in detail["turns"]] == [
        "open chrome and search rust",
        "remind me about the report",
    ]

    missing = client.get("/api/memory/sessions/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "memory_session_not_found"

    deleted = client.delete(f"/api/memory/sessions/{sid}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/memory/sessions/{sid}").status_code == 404


def test_search_keyword_and_validation(client, seeded):
    result = client.get("/api/memory/search", params={"q": "chrome", "mode": "keyword"}).json()
    assert result["count"] == 1
    assert result["results"][0]["raw_text"] == "open chrome and search rust"
    assert result["results"][0]["created_at"]

    bad = client.get("/api/memory/search", params={"q": "x", "mode": "psychic"})
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_mode"


def test_fact_lifecycle(client):
    created = client.post(
        "/api/memory/facts",
        json={
            "subject": "user",
            "predicate": "favourite_drink",
            "object": "coffee",
            "category": "preference",
        },
    )
    assert created.status_code == 200
    fact_id = created.json()["id"]

    listing = client.get("/api/memory/facts", params={"q": "coffee"}).json()
    assert listing["count"] == 1

    detail = client.get(f"/api/memory/facts/{fact_id}").json()
    assert detail["object"] == "coffee"
    assert detail["revisions"] == []

    corrected = client.post(
        f"/api/memory/facts/{fact_id}/correct",
        json={"object": "tea", "reason": "user said so"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["object"] == "tea"
    assert len(client.get(f"/api/memory/facts/{fact_id}").json()["revisions"]) == 1

    deleted = client.delete(f"/api/memory/facts/{fact_id}")
    assert deleted.json()["deleted"] is True
    assert client.get("/api/memory/facts").json()["count"] == 0

    restored = client.post(f"/api/memory/facts/{fact_id}/restore")
    assert restored.json()["restored"] is True
    assert client.get("/api/memory/facts").json()["count"] == 1

    assert client.get("/api/memory/facts/missing").status_code == 404


def test_task_lifecycle(client):
    created = client.post(
        "/api/memory/tasks", json={"goal": "prepare the quarterly report"}
    )
    assert created.status_code == 200
    task_id = created.json()["id"]

    step = client.post(
        f"/api/memory/tasks/{task_id}/steps",
        json={"action": "open_app", "target": "docs"},
    )
    assert step.status_code == 200
    step_id = step.json()["id"]

    updated = client.patch(
        f"/api/memory/tasks/{task_id}/steps/{step_id}",
        json={"status": "completed", "result": {"ok": True}},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"

    cancelled = client.post(f"/api/memory/tasks/{task_id}/cancel")
    assert cancelled.json()["state"] == "cancelled"
    resumed = client.post(f"/api/memory/tasks/{task_id}/resume")
    assert resumed.json()["state"] == "in_progress"
    completed = client.post(f"/api/memory/tasks/{task_id}/complete")
    assert completed.json()["state"] == "completed"

    listing = client.get("/api/memory/tasks").json()
    assert listing["count"] == 1

    assert client.get("/api/memory/tasks/missing").status_code == 404
    assert client.post("/api/memory/tasks/missing/cancel").status_code == 404


def test_prune_defaults_to_dry_run(client, seeded):
    response = client.post("/api/memory/prune", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["deleted"] == 0
    assert "retention_days" in payload
    assert client.get("/api/memory/stats").json()["sessions"] == 1


def test_backup_reports_integrity(client, seeded):
    response = client.post("/api/memory/backup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["backup"]
    assert payload["integrity"] == "ok"


def test_disabled_memory_reports_honestly(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        CONFIG.format(db_path=(tmp_path / "memory.db").as_posix()).replace(
            "enabled: true\n  db_path", "enabled: false\n  db_path"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics_mod, "prime_cpu", lambda: None)
    runtime = DashboardRuntime(
        config_path=str(config_path),
        activity_path=str(tmp_path / "activity.json"),
    )
    reset_runtime(runtime)
    try:
        with TestClient(create_app()) as client:
            stats = client.get("/api/memory/stats").json()
            assert stats == {"enabled": False, "source": "chat"}
            assert client.get("/api/memory/sessions").json()["enabled"] is False
    finally:
        reset_runtime(None)
