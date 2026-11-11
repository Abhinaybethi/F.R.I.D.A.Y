"""Durable task/step storage tests (no execution happens here)."""
from __future__ import annotations

import pytest

from friday.memory.service import MemoryService


def _service(tmp_path):
    return MemoryService.from_config(
        {
            "db_path": str(tmp_path / "memory.db"),
            "vector_enabled": False,
            "dedupe_window_seconds": 0,
        },
        source="test",
        vector_worker=False,
    )


def test_create_list_and_get_task(tmp_path):
    service = _service(tmp_path)
    sid = service.start_session()
    task = service.create_task("book a flight", meta={"origin": "BLR"})
    assert task is not None
    assert task.state == "pending"
    assert task.source_session_id == sid
    assert task.meta == {"origin": "BLR"}
    assert service.get_task(task.id).goal == "book a flight"
    assert [t.id for t in service.list_tasks()] == [task.id]
    service.close()


def test_steps_are_ordered_and_idempotent(tmp_path):
    service = _service(tmp_path)
    task = service.create_task("prepare report")
    first = service.add_task_step(task.id, "open_app", target="docs")
    second = service.add_task_step(task.id, "search_web", target="q3 numbers")
    assert (first.step_index, second.step_index) == (0, 1)

    duplicate = service.add_task_step(
        task.id, "open_app", target="docs", idempotency_key="step-open"
    )
    duplicate_again = service.add_task_step(
        task.id, "open_app", target="docs", idempotency_key="step-open"
    )
    assert duplicate.id == duplicate_again.id
    assert len(service.get_task(task.id).steps) == 3
    service.close()


def test_update_step_tracks_timestamps_and_result(tmp_path):
    service = _service(tmp_path)
    task = service.create_task("do work")
    step = service.add_task_step(task.id, "open_app", target="chrome")

    running = service.update_task_step(step.id, status="running")
    assert running.status == "running"
    assert running.started_at
    assert running.completed_at is None

    done = service.update_task_step(
        step.id,
        status="completed",
        result={"ok": True},
        verification_status="verified",
    )
    assert done.status == "completed"
    assert done.completed_at
    assert done.result == {"ok": True}
    assert done.verification_status == "verified"
    service.close()


def test_cancel_resume_and_complete(tmp_path):
    service = _service(tmp_path)
    task = service.create_task("long job")

    cancelled = service.cancel_task(task.id, reason="user changed mind")
    assert cancelled.state == "cancelled"
    assert cancelled.completed_at
    assert cancelled.meta["cancel_reason"] == "user changed mind"

    resumed = service.resume_task(task.id)
    assert resumed.state == "in_progress"
    assert resumed.completed_at is None

    completed = service.complete_task(task.id)
    assert completed.state == "completed"
    assert completed.completed_at
    service.close()


def test_invalid_states_and_missing_tasks_are_rejected(tmp_path):
    service = _service(tmp_path)
    task = service.create_task("valid goal")
    with pytest.raises(ValueError):
        service.add_task_step(task.id, "open_app", status="exploded")
    with pytest.raises(ValueError):
        service.update_task_step(
            service.add_task_step(task.id, "open_app").id, status="exploded"
        )

    assert service.get_task("missing") is None
    assert service.cancel_task("missing") is None
    assert service.add_task_step("missing", "open_app") is None
    assert service.update_task_step("missing", status="completed") is None
    service.close()
