"""Persistent task records (storage only — no execution engine).

Phase 2 stores resumable tasks and their ordered steps so a restart can show
what was in flight and continue later. Executing steps is Phase 3; this module
only writes/reads the durable record and never invents success.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from friday.memory.models import TaskRecord, TaskStepRecord
from friday.memory.store import MemoryStore
from friday.memory.timeutil import utc_now_iso
from friday.utils.logger import get_logger

logger = get_logger(__name__)

TASK_STATES = frozenset(
    {"pending", "in_progress", "waiting", "completed", "cancelled", "failed"}
)
STEP_STATES = frozenset(
    {"pending", "running", "completed", "failed", "skipped", "cancelled"}
)


def _check_state(value: str, allowed, label: str) -> str:
    if value not in allowed:
        raise ValueError(f"Invalid {label} state {value!r}; expected one of {sorted(allowed)}")
    return value


def task_from_row(row, steps: Optional[List[TaskStepRecord]] = None) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        goal=row["goal"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        source_session_id=row["source_session_id"],
        meta_json=row["meta_json"],
        steps=list(steps or []),
    )


def step_from_row(row) -> TaskStepRecord:
    return TaskStepRecord(
        id=row["id"],
        task_id=row["task_id"],
        step_index=int(row["step_index"]),
        action=row["action"] or "",
        target=row["target"] or "",
        status=row["status"] or "pending",
        idempotency_key=row["idempotency_key"],
        result_json=row["result_json"],
        verification_status=row["verification_status"],
        error=row["error"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def list_steps(store: MemoryStore, task_id: str) -> List[TaskStepRecord]:
    rows = store.query(
        "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_index ASC",
        (task_id,),
    )
    return [step_from_row(row) for row in rows]


def get_task(store: MemoryStore, task_id: str) -> Optional[TaskRecord]:
    row = store.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return None
    return task_from_row(row, list_steps(store, task_id))


def list_tasks(
    store: MemoryStore,
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[TaskRecord]:
    params: List[Any] = []
    where = "1=1"
    if state:
        where = "state = ?"
        params.append(state)
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    rows = store.query(
        f"SELECT * FROM tasks WHERE {where} ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?",
        params,
    )
    return [task_from_row(row, list_steps(store, row["id"])) for row in rows]


def create_task(
    store: MemoryStore,
    goal: str,
    *,
    source_session_id: Optional[str] = None,
    state: str = "pending",
    meta: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> TaskRecord:
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("Task goal must not be empty")
    _check_state(state, TASK_STATES, "task")
    now = utc_now_iso()
    task_id = task_id or str(uuid.uuid4())
    store.execute(
        """
        INSERT INTO tasks
            (id, goal, state, created_at, updated_at, completed_at,
             source_session_id, meta_json)
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            task_id,
            goal,
            state,
            now,
            now,
            source_session_id,
            json.dumps(meta) if meta else None,
        ),
    )
    return get_task(store, task_id)  # type: ignore[return-value]


def set_task_state(
    store: MemoryStore,
    task_id: str,
    state: str,
    *,
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[TaskRecord]:
    _check_state(state, TASK_STATES, "task")
    now = utc_now_iso()
    completed_at = now if state in ("completed", "cancelled", "failed") else None
    existing = get_task(store, task_id)
    if existing is None:
        return None
    merged_meta = existing.meta
    if meta is not None:
        merged_meta.update(meta)
    store.execute(
        """
        UPDATE tasks
        SET state = ?, updated_at = ?, completed_at = ?, meta_json = ?
        WHERE id = ?
        """,
        (state, now, completed_at, json.dumps(merged_meta) if merged_meta else None, task_id),
    )
    return get_task(store, task_id)


def cancel_task(store: MemoryStore, task_id: str, reason: str = "") -> Optional[TaskRecord]:
    return set_task_state(store, task_id, "cancelled", meta={"cancel_reason": reason} if reason else None)


def resume_task(store: MemoryStore, task_id: str) -> Optional[TaskRecord]:
    """Move a paused/waiting task back to in-progress and return pending steps."""
    return set_task_state(store, task_id, "in_progress")


def complete_task(store: MemoryStore, task_id: str) -> Optional[TaskRecord]:
    return set_task_state(store, task_id, "completed")


def add_step(
    store: MemoryStore,
    task_id: str,
    action: str,
    *,
    target: str = "",
    idempotency_key: Optional[str] = None,
    status: str = "pending",
    result: Optional[Dict[str, Any]] = None,
    verification_status: Optional[str] = None,
    error: Optional[str] = None,
    step_index: Optional[int] = None,
) -> Optional[TaskStepRecord]:
    """Append a step. A repeated ``idempotency_key`` returns the existing row."""
    _check_state(status, STEP_STATES, "step")
    if get_task(store, task_id) is None:
        return None

    if idempotency_key:
        existing = store.query_one(
            "SELECT * FROM task_steps WHERE task_id = ? AND idempotency_key = ?",
            (task_id, idempotency_key),
        )
        if existing is not None:
            return step_from_row(existing)

    if step_index is None:
        step_index = int(
            store.scalar(
                "SELECT COALESCE(MAX(step_index), -1) + 1 FROM task_steps WHERE task_id = ?",
                (task_id,),
                default=0,
            )
        )

    step_id = str(uuid.uuid4())
    try:
        store.execute(
            """
            INSERT INTO task_steps
                (id, task_id, step_index, action, target, status, idempotency_key,
                 result_json, verification_status, error, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                step_id,
                task_id,
                step_index,
                action or "",
                target or "",
                status,
                idempotency_key,
                json.dumps(result) if result else None,
                verification_status,
                error,
            ),
        )
    except sqlite3.IntegrityError:
        # Concurrent duplicate with the same idempotency key: return the winner.
        existing = store.query_one(
            "SELECT * FROM task_steps WHERE task_id = ? AND idempotency_key = ?",
            (task_id, idempotency_key),
        )
        return step_from_row(existing) if existing is not None else None

    store.execute(
        "UPDATE tasks SET updated_at = ? WHERE id = ?", (utc_now_iso(), task_id)
    )
    row = store.query_one("SELECT * FROM task_steps WHERE id = ?", (step_id,))
    return step_from_row(row) if row is not None else None


def update_step(
    store: MemoryStore,
    step_id: str,
    *,
    status: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    verification_status: Optional[str] = None,
    error: Optional[str] = None,
) -> Optional[TaskStepRecord]:
    row = store.query_one("SELECT * FROM task_steps WHERE id = ?", (step_id,))
    if row is None:
        return None
    if status is not None:
        _check_state(status, STEP_STATES, "step")

    now = utc_now_iso()
    new_status = status if status is not None else row["status"]
    started_at = row["started_at"]
    completed_at = row["completed_at"]
    if new_status == "running" and not started_at:
        started_at = now
    if new_status in ("completed", "failed", "skipped", "cancelled"):
        completed_at = now
    result_json = json.dumps(result) if result is not None else row["result_json"]
    store.execute(
        """
        UPDATE task_steps
        SET status = ?, result_json = ?, verification_status = ?,
            error = ?, started_at = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            new_status,
            result_json,
            verification_status if verification_status is not None else row["verification_status"],
            error if error is not None else row["error"],
            started_at,
            completed_at,
            step_id,
        ),
    )
    store.execute(
        "UPDATE tasks SET updated_at = ? WHERE id = ?", (now, row["task_id"])
    )
    fresh = store.query_one("SELECT * FROM task_steps WHERE id = ?", (step_id,))
    return step_from_row(fresh) if fresh is not None else None
