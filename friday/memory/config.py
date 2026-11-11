"""Typed configuration for persistent conversation & task memory.

The memory layer is local-first and optional. Every value has a safe default so
an older ``config.yaml`` (with no ``memory:`` section) still works, and a bad
value can never disable the rest of the assistant.

Storage layout:
  * raw history / episodes / facts / tasks -> SQLite (``.data/memory.db``)
  * semantic turn vectors                 -> ChromaDB (optional, degrades)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def default_project_root() -> str:
    return _PROJECT_ROOT


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0", ""):
            return False
    return default


def _as_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _as_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


@dataclass(frozen=True)
class MemoryConfig:
    """Immutable, validated memory configuration."""

    enabled: bool = True
    db_path: str = ".data/memory.db"
    vector_enabled: bool = True
    vector_path: str = ".data/rag/conversations"
    vector_collection: str = "conversation_memory"
    retention_days: int = 0          # 0 = keep forever
    max_turns_per_session: int = 0   # 0 = unlimited
    summaries_enabled: bool = True
    summary_min_turns: int = 4
    dedupe_window_seconds: float = 3.0
    search_limit: int = 20
    backup_dir: str = ".data/backups"

    # ------------------------------------------------------------------
    @classmethod
    def from_mapping(
        cls,
        mapping: Optional[Mapping[str, Any]],
        project_root: Optional[str] = None,
    ) -> "MemoryConfig":
        raw = dict(mapping or {})
        root = project_root or default_project_root()

        def path(key: str, default: str) -> str:
            value = raw.get(key, default)
            if not isinstance(value, str) or not value.strip():
                value = default
            return value if os.path.isabs(value) else os.path.join(root, value)

        collection = raw.get("vector_collection", "conversation_memory")
        if not isinstance(collection, str) or not collection.strip():
            collection = "conversation_memory"

        return cls(
            enabled=_as_bool(raw.get("enabled", True), True),
            db_path=path("db_path", ".data/memory.db"),
            vector_enabled=_as_bool(raw.get("vector_enabled", True), True),
            vector_path=path("vector_path", ".data/rag/conversations"),
            vector_collection=collection.strip()[:128],
            retention_days=_as_int(raw.get("retention_days", 0), 0, 0, 36500),
            max_turns_per_session=_as_int(
                raw.get("max_turns_per_session", 0), 0, 0, 1_000_000
            ),
            summaries_enabled=_as_bool(raw.get("summaries_enabled", True), True),
            summary_min_turns=_as_int(raw.get("summary_min_turns", 4), 4, 1, 1000),
            dedupe_window_seconds=_as_float(
                raw.get("dedupe_window_seconds", 3.0), 3.0, 0.0, 3600.0
            ),
            search_limit=_as_int(raw.get("search_limit", 20), 20, 1, 200),
            backup_dir=path("backup_dir", ".data/backups"),
        )

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "db_path": self.db_path,
            "vector_enabled": self.vector_enabled,
            "vector_path": self.vector_path,
            "vector_collection": self.vector_collection,
            "retention_days": self.retention_days,
            "max_turns_per_session": self.max_turns_per_session,
            "summaries_enabled": self.summaries_enabled,
            "summary_min_turns": self.summary_min_turns,
            "dedupe_window_seconds": self.dedupe_window_seconds,
            "search_limit": self.search_limit,
            "backup_dir": self.backup_dir,
        }
