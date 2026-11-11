"""Plain data records returned by the memory layer.

These are deliberately boring dataclasses: the API/UI serialises them straight
to JSON, and tests can compare fields without depending on sqlite rows.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


def _loads(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dumps(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class SessionRecord:
    id: str
    started_at: str
    ended_at: Optional[str] = None
    source: str = "text"
    title: Optional[str] = None
    summary_id: Optional[str] = None
    meta_json: Optional[str] = None

    @property
    def meta(self) -> Dict[str, Any]:
        return _loads(self.meta_json)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("meta_json", None)
        data["meta"] = self.meta
        return data


@dataclass
class TurnRecord:
    id: str
    session_id: str
    turn_index: int
    role: str = "user"
    raw_text: str = ""
    resolved_text: Optional[str] = None
    response_text: Optional[str] = None
    intent_action: Optional[str] = None
    intent_target: Optional[str] = None
    tool_status: Optional[str] = None
    verification_status: Optional[str] = None
    topic: Optional[str] = None
    created_at: str = ""
    meta_json: Optional[str] = None

    @property
    def meta(self) -> Dict[str, Any]:
        return _loads(self.meta_json)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("meta_json", None)
        data["meta"] = self.meta
        return data


@dataclass
class SummaryRecord:
    id: str
    session_id: str
    kind: str = "session"
    text: str = ""
    generated_by: str = "extractive"
    model: Optional[str] = None
    source_message_ids_json: Optional[str] = None
    created_at: str = ""

    @property
    def source_message_ids(self) -> list:
        if not self.source_message_ids_json:
            return []
        try:
            parsed = json.loads(self.source_message_ids_json)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("source_message_ids_json", None)
        data["source_message_ids"] = self.source_message_ids
        return data


def turn_from_row(row) -> TurnRecord:
    """Build a :class:`TurnRecord` from a sqlite ``messages`` row."""
    return TurnRecord(
        id=row["id"],
        session_id=row["session_id"],
        turn_index=int(row["turn_index"]),
        role=row["role"],
        raw_text=row["raw_text"] or "",
        resolved_text=row["resolved_text"],
        response_text=row["response_text"],
        intent_action=row["intent_action"],
        intent_target=row["intent_target"],
        tool_status=row["tool_status"],
        verification_status=row["verification_status"],
        topic=row["topic"],
        created_at=row["created_at"],
        meta_json=row["meta_json"],
    )


@dataclass
class EpisodeRecord:
    id: str
    session_id: Optional[str]
    kind: str
    title: str
    detail: Optional[str] = None
    importance: float = 0.0
    occurred_at: str = ""
    source_message_id: Optional[str] = None
    meta_json: Optional[str] = None

    @property
    def meta(self) -> Dict[str, Any]:
        return _loads(self.meta_json)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("meta_json", None)
        data["meta"] = self.meta
        return data


@dataclass
class FactRecord:
    id: str
    subject: str
    predicate: str
    object: str
    category: str = "general"
    confidence: float = 1.0
    source_message_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    deleted_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskStepRecord:
    id: str
    task_id: str
    step_index: int
    action: str = ""
    target: str = ""
    status: str = "pending"
    idempotency_key: Optional[str] = None
    result_json: Optional[str] = None
    verification_status: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    @property
    def result(self) -> Dict[str, Any]:
        return _loads(self.result_json)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("result_json", None)
        data["result"] = self.result
        return data


@dataclass
class TaskRecord:
    id: str
    goal: str
    state: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    completed_at: Optional[str] = None
    source_session_id: Optional[str] = None
    meta_json: Optional[str] = None
    steps: list = field(default_factory=list)

    @property
    def meta(self) -> Dict[str, Any]:
        return _loads(self.meta_json)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("meta_json", None)
        data.pop("steps", None)
        data["meta"] = self.meta
        data["steps"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in self.steps]
        return data
