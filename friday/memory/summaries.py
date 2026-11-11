"""Generated session summaries, kept strictly separate from raw history.

Raw messages are never rewritten or replaced. A summary is an additional row in
``summaries`` with a ``generated_by`` marker. Phase 2 uses a deterministic
extractive summary; an optional callable can supply an LLM summary later without
changing the storage contract.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

from friday.memory.models import SummaryRecord, TurnRecord, turn_from_row
from friday.memory.store import MemoryStore
from friday.memory.timeutil import utc_now_iso
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return utc_now_iso()


def extractive_summary(
    turns: Iterable[TurnRecord],
    max_chars: int = 1400,
) -> str:
    """Build a short, faithful digest of a session from its own words."""
    lines: List[str] = []
    used = 0
    for turn in turns:
        user = (turn.raw_text or "").strip().replace("\n", " ")
        assistant = (turn.response_text or "").strip().replace("\n", " ")
        if user:
            piece = f"User: {user[:300]}"
            if used + len(piece) > max_chars:
                break
            lines.append(piece)
            used += len(piece)
        if assistant:
            piece = f"FRIDAY: {assistant[:300]}"
            if used + len(piece) > max_chars:
                break
            lines.append(piece)
            used += len(piece)
    if not lines:
        return ""
    return "\n".join(lines)


def generate_session_summary(
    store: MemoryStore,
    session_id: str,
    turns: Optional[List[TurnRecord]] = None,
    *,
    generated_by: str = "extractive",
    model: Optional[str] = None,
    llm_summarizer: Optional[Callable[[List[TurnRecord]], str]] = None,
) -> Optional[SummaryRecord]:
    """Create a new summary row for ``session_id`` and point the session at it."""
    if turns is None:
        rows = store.query(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY turn_index ASC",
            (session_id,),
        )
        turns = [turn_from_row(row) for row in rows]

    if not turns:
        return None

    text = ""
    by = generated_by
    used_model = model
    if llm_summarizer is not None:
        try:
            text = (llm_summarizer(turns) or "").strip()
            by = "llm"
        except Exception as exc:
            logger.warning("[MEMORY] LLM summary failed; using extractive: %s", exc)
            text = ""
    if not text:
        text = extractive_summary(turns)
        by = "extractive"
        used_model = None
    if not text:
        return None

    summary_id = str(uuid.uuid4())
    created_at = _now_iso()
    source_ids = [turn.id for turn in turns]
    store.execute(
        """
        INSERT INTO summaries
            (id, session_id, kind, text, generated_by, model,
             source_message_ids_json, created_at)
        VALUES (?, ?, 'session', ?, ?, ?, ?, ?)
        """,
        (
            summary_id,
            session_id,
            text,
            by,
            used_model,
            json.dumps(source_ids),
            created_at,
        ),
    )
    store.execute(
        "UPDATE sessions SET summary_id = ? WHERE id = ?",
        (summary_id, session_id),
    )
    return SummaryRecord(
        id=summary_id,
        session_id=session_id,
        kind="session",
        text=text,
        generated_by=by,
        model=used_model,
        source_message_ids_json=json.dumps(source_ids),
        created_at=created_at,
    )


def latest_summary(store: MemoryStore, session_id: str) -> Optional[SummaryRecord]:
    row = store.query_one(
        "SELECT * FROM summaries WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (session_id,),
    )
    if row is None:
        return None
    return _summary_from_row(row)


def list_summaries(store: MemoryStore, session_id: str) -> List[SummaryRecord]:
    rows = store.query(
        "SELECT * FROM summaries WHERE session_id = ? ORDER BY created_at ASC, id ASC",
        (session_id,),
    )
    return [_summary_from_row(row) for row in rows]


def _summary_from_row(row) -> SummaryRecord:
    return SummaryRecord(
        id=row["id"],
        session_id=row["session_id"],
        kind=row["kind"],
        text=row["text"],
        generated_by=row["generated_by"],
        model=row["model"],
        source_message_ids_json=row["source_message_ids_json"],
        created_at=row["created_at"],
    )
