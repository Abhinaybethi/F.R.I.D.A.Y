"""High-level memory facade used by the conversation loop and the API.

Design rules (Phase 2):
  * **Never break a response.** Every write is best-effort; failures are logged
    and returned as ``None``/empty result, never raised into the caller.
  * **Raw history is the source of truth.** Summaries live in their own table.
  * **Stable identifiers.** Callers may supply a ``message_id``; inserts use
    ``INSERT OR IGNORE`` so retries are idempotent. A short-window identical
    (raw, response) pair is also skipped to absorb reconnect retries.
  * **Read-first API.** Nothing here infers task success or fact content.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from friday.memory import retrieval, summaries, tasks
from friday.memory.config import MemoryConfig
from friday.memory.models import (
    EpisodeRecord,
    FactRecord,
    SessionRecord,
    SummaryRecord,
    TaskRecord,
    TaskStepRecord,
    TurnRecord,
    turn_from_row,
)
from friday.memory.store import MemoryStore
from friday.memory.timeutil import utc_now_iso
from friday.memory.vectors import MemoryVectorIndex
from friday.utils.logger import get_logger

logger = get_logger(__name__)


# ----------------------------------------------------------------------
# Result parsing helpers
# ----------------------------------------------------------------------
def _enum_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def derive_tool_status(result: Any) -> Optional[str]:
    if not result:
        return None
    if isinstance(result, dict):
        if "success" in result:
            return "success" if result.get("success") else "failed"
        for key in ("tool_status", "final_status", "status"):
            value = result.get(key)
            if value:
                return str(value).lower()
        return None
    execution = getattr(result, "execution", None)
    status = getattr(execution, "status", None)
    if status is not None:
        return (_enum_name(status) or "").lower() or None
    if hasattr(result, "success"):
        return "success" if bool(getattr(result, "success")) else "failed"
    if hasattr(result, "is_success"):
        return "success" if bool(getattr(result, "is_success")) else "failed"
    return None


def derive_verification_status(result: Any) -> Optional[str]:
    if not result:
        return None
    if isinstance(result, dict):
        for key in ("verification_status", "verification"):
            value = result.get(key)
            if isinstance(value, dict):
                value = value.get("status") or value.get("verification_status")
            if value:
                return str(value).lower()
        return None
    verification = getattr(result, "verification", None)
    status = getattr(verification, "status", None)
    if status is not None:
        return (_enum_name(status) or "").lower() or None
    return None


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _session_from_row(row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        source=row["source"],
        title=row["title"],
        summary_id=row["summary_id"],
        meta_json=row["meta_json"],
    )


def _fact_from_row(row) -> FactRecord:
    return FactRecord(
        id=row["id"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        category=row["category"],
        confidence=float(row["confidence"] or 0.0),
        source_message_id=row["source_message_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _episode_from_row(row) -> EpisodeRecord:
    return EpisodeRecord(
        id=row["id"],
        session_id=row["session_id"],
        kind=row["kind"],
        title=row["title"],
        detail=row["detail"],
        importance=float(row["importance"] or 0.0),
        occurred_at=row["occurred_at"],
        source_message_id=row["source_message_id"],
        meta_json=row["meta_json"],
    )


# ----------------------------------------------------------------------
class MemoryService:
    """Facade over SQLite raw history + optional Chroma semantic index."""

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        *,
        store: Optional[MemoryStore] = None,
        vectors: Optional[MemoryVectorIndex] = None,
        source: str = "text",
        vector_worker: bool = True,
    ):
        self.config = config or MemoryConfig()
        self.enabled = bool(self.config.enabled)
        self.source = source
        self.store = store or MemoryStore(self.config.db_path)
        if self.enabled:
            self.store.initialize()

        if vectors is not None:
            self.vectors = vectors
        elif self.enabled and self.config.vector_enabled:
            self.vectors = MemoryVectorIndex(
                self.config.vector_path,
                collection=self.config.vector_collection,
                enabled=True,
            )
        else:
            self.vectors = None

        self._session_id: Optional[str] = None
        self._session_lock = threading.RLock()
        self._vector_lock = threading.Lock()
        self._vector_futures: List[Future] = []
        self._vector_executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="friday-memory")
            if vector_worker and self.enabled and self.vectors is not None
            else None
        )
        self._closed = False

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        mapping: Optional[Dict[str, Any]],
        *,
        source: str = "text",
        project_root: Optional[str] = None,
        **kwargs: Any,
    ) -> "MemoryService":
        return cls(
            MemoryConfig.from_mapping(mapping, project_root=project_root),
            source=source,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    @property
    def current_session_id(self) -> Optional[str]:
        with self._session_lock:
            return self._session_id

    def start_session(
        self,
        source: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            with self._session_lock:
                if session_id:
                    existing = self.store.query_one(
                        "SELECT id FROM sessions WHERE id = ?", (session_id,)
                    )
                    if existing is not None:
                        self._session_id = session_id
                        return session_id
                elif self._session_id:
                    existing = self.store.query_one(
                        "SELECT id, ended_at FROM sessions WHERE id = ?",
                        (self._session_id,),
                    )
                    if existing is not None and not existing["ended_at"]:
                        return self._session_id

                sid = session_id or str(uuid.uuid4())
                now = utc_now_iso()
                self.store.execute(
                    """
                    INSERT OR IGNORE INTO sessions
                        (id, started_at, ended_at, source, title, summary_id, meta_json)
                    VALUES (?, ?, NULL, ?, ?, NULL, ?)
                    """,
                    (
                        sid,
                        now,
                        source or self.source,
                        title,
                        json.dumps(meta) if meta else None,
                    ),
                )
                self._session_id = sid
                logger.info("[MEMORY] session started: %s (source=%s)", sid, source or self.source)
                return sid
        except Exception as exc:
            logger.warning("[MEMORY] start_session failed: %s", exc)
            return None

    def end_session(
        self,
        session_id: Optional[str] = None,
        *,
        generate_summary: bool = True,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        sid = session_id or self.current_session_id
        if not sid:
            return {"session_id": None}
        try:
            self.flush_vectors()
            now = utc_now_iso()
            self.store.execute(
                "UPDATE sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
                (now, sid),
            )
            summary = None
            turns = self._turns_for_session(sid)
            if (
                generate_summary
                and self.config.summaries_enabled
                and len(turns) >= self.config.summary_min_turns
            ):
                summary = summaries.generate_session_summary(self.store, sid, turns)
            with self._session_lock:
                if self._session_id == sid:
                    self._session_id = None
            logger.info("[MEMORY] session ended: %s", sid)
            return {
                "session_id": sid,
                "ended_at": now,
                "turns": len(turns),
                "summary": summary.to_dict() if summary else None,
            }
        except Exception as exc:
            logger.warning("[MEMORY] end_session failed: %s", exc)
            return {"session_id": sid, "error": str(exc)}

    def ensure_session(self) -> Optional[str]:
        if not self.enabled:
            return None
        sid = self.current_session_id
        if sid:
            row = self.store.query_one(
                "SELECT ended_at FROM sessions WHERE id = ?", (sid,)
            )
            if row is not None and not row["ended_at"]:
                return sid
        return self.start_session()

    # ------------------------------------------------------------------
    # Turn recording
    # ------------------------------------------------------------------
    def record_turn(
        self,
        raw_text: str,
        response_text: str = "",
        *,
        resolved_text: str = "",
        intent: Any = None,
        tool_result: Any = None,
        tool_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        message_id: Optional[str] = None,
        role: str = "user",
        topic: str = "",
        session_id: Optional[str] = None,
        created_at: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        record_episode: bool = True,
    ) -> Optional[TurnRecord]:
        """Persist one complete user turn. Never raises into the caller."""
        if not self.enabled:
            return None
        raw_text = (raw_text or "").strip()
        if not raw_text:
            return None
        try:
            sid = session_id or self.ensure_session()
            if not sid:
                return None
            if session_id:
                self.start_session(session_id=session_id)

            now = created_at or utc_now_iso()
            action = _enum_name(getattr(intent, "action", None)) if intent is not None else None
            target = str(getattr(intent, "target", "") or "") if intent is not None else ""
            status = tool_status or derive_tool_status(tool_result)
            verification = verification_status or derive_verification_status(tool_result)

            if message_id is None and self.config.dedupe_window_seconds > 0:
                duplicate = self._recent_duplicate(sid, raw_text, response_text)
                if duplicate is not None:
                    logger.debug("[MEMORY] duplicate turn ignored: %s", duplicate.id)
                    return duplicate

            mid = message_id or str(uuid.uuid4())
            turn_index = int(
                self.store.scalar(
                    "SELECT COALESCE(MAX(turn_index), -1) + 1 FROM messages WHERE session_id = ?",
                    (sid,),
                    default=0,
                )
            )

            with self.store.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (id, session_id, turn_index, role, raw_text, resolved_text,
                         response_text, intent_action, intent_target, tool_status,
                         verification_status, topic, created_at, meta_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mid,
                        sid,
                        turn_index,
                        role or "user",
                        raw_text,
                        resolved_text or None,
                        response_text or None,
                        action,
                        target or None,
                        status,
                        verification,
                        topic or None,
                        now,
                        json.dumps(meta) if meta else None,
                    ),
                )
                inserted = cursor.rowcount > 0

            if not inserted:
                existing = self.store.query_one("SELECT * FROM messages WHERE id = ?", (mid,))
                return turn_from_row(existing) if existing is not None else None

            self._set_session_title(sid, raw_text)
            self._enforce_session_cap(sid)

            record = turn_from_row(
                self.store.query_one("SELECT * FROM messages WHERE id = ?", (mid,))
            )
            if record_episode:
                self._record_turn_episode(record, action, target, status, verification)
            if action and action.upper() not in ("UNKNOWN", "NONE"):
                self.record_event(
                    kind="action",
                    title=f"{action} {target}".strip(),
                    detail=self._short_result(tool_result),
                    importance=0.6 if status == "success" else 0.4,
                    session_id=sid,
                    source_message_id=mid,
                    occurred_at=now,
                    meta={"tool_status": status, "verification_status": verification},
                )
            self._schedule_vector(record, topic)
            return record
        except Exception as exc:
            logger.warning("[MEMORY] record_turn failed: %s", exc)
            return None

    def record_event(
        self,
        kind: str,
        title: str,
        detail: str = "",
        importance: float = 0.5,
        *,
        session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        occurred_at: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[EpisodeRecord]:
        if not self.enabled:
            return None
        try:
            sid = session_id or self.ensure_session()
            episode_id = str(uuid.uuid4())
            now = occurred_at or utc_now_iso()
            self.store.execute(
                """
                INSERT INTO episodes
                    (id, session_id, kind, title, detail, importance, occurred_at,
                     source_message_id, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    sid,
                    kind,
                    title[:300],
                    detail or None,
                    float(importance),
                    now,
                    source_message_id,
                    json.dumps(meta) if meta else None,
                ),
            )
            row = self.store.query_one("SELECT * FROM episodes WHERE id = ?", (episode_id,))
            return _episode_from_row(row) if row is not None else None
        except Exception as exc:
            logger.warning("[MEMORY] record_event failed: %s", exc)
            return None

    def _record_turn_episode(
        self,
        record: TurnRecord,
        action: Optional[str],
        target: str,
        status: Optional[str],
        verification: Optional[str],
    ) -> None:
        title = record.raw_text[:120]
        detail = (record.response_text or "")[:800]
        importance = 0.2
        if status == "success":
            importance = 0.5
        self.record_event(
            kind="turn",
            title=title,
            detail=detail,
            importance=importance,
            session_id=record.session_id,
            source_message_id=record.id,
            occurred_at=record.created_at,
            meta={
                "intent_action": action,
                "intent_target": target or None,
                "tool_status": status,
                "verification_status": verification,
            },
        )

    def _recent_duplicate(
        self, session_id: str, raw_text: str, response_text: str
    ) -> Optional[TurnRecord]:
        row = self.store.query_one(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        )
        if row is None:
            return None
        if (row["raw_text"] or "").strip() != raw_text:
            return None
        if (row["response_text"] or "").strip() != (response_text or "").strip():
            return None
        previous = _parse_iso(row["created_at"])
        if previous is None:
            return None
        delta = (datetime.now(timezone.utc) - previous).total_seconds()
        if 0.0 <= delta <= self.config.dedupe_window_seconds:
            return turn_from_row(row)
        return None

    def _set_session_title(self, session_id: str, raw_text: str) -> None:
        try:
            self.store.execute(
                "UPDATE sessions SET title = ? WHERE id = ? AND (title IS NULL OR title = '')",
                (raw_text[:120], session_id),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[MEMORY] title update failed: %s", exc)

    def _enforce_session_cap(self, session_id: str) -> None:
        cap = self.config.max_turns_per_session
        if cap <= 0:
            return
        rows = self.store.query(
            "SELECT id FROM messages WHERE session_id = ? ORDER BY turn_index DESC LIMIT -1 OFFSET ?",
            (session_id, cap),
        )
        if not rows:
            return
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        self.store.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", ids)
        if self.vectors is not None:
            self.vectors.delete(ids)

    def _short_result(self, result: Any, max_chars: int = 500) -> str:
        if result is None:
            return ""
        if isinstance(result, dict):
            try:
                text = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(result)
        else:
            text = str(result)
        return text[:max_chars]

    def _turns_for_session(self, session_id: str) -> List[TurnRecord]:
        rows = self.store.query(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY turn_index ASC",
            (session_id,),
        )
        return [turn_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # Vector indexing
    # ------------------------------------------------------------------
    def _schedule_vector(self, record: TurnRecord, topic: str) -> None:
        if self.vectors is None:
            return
        payload = {
            "id": record.id,
            "text": "\n".join(
                part for part in (record.raw_text, record.response_text or "") if part
            ),
            "metadata": {
                "session_id": record.session_id,
                "created_at": record.created_at,
                "topic": topic or "",
                "intent_action": record.intent_action or "",
                "source": self.source,
            },
        }
        if self._vector_executor is None:
            self._index_vector(payload)
            return
        try:
            with self._vector_lock:
                self._vector_futures = [f for f in self._vector_futures if not f.done()]
                self._vector_futures.append(
                    self._vector_executor.submit(self._index_vector, payload)
                )
        except Exception as exc:  # pragma: no cover - executor shutdown
            logger.debug("[MEMORY] vector scheduling failed: %s", exc)

    def _index_vector(self, payload: Dict[str, Any]) -> None:
        try:
            self.vectors.add([payload])
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[MEMORY] background vector index failed: %s", exc)

    def flush_vectors(self, timeout: float = 10.0) -> None:
        """Wait for background vector writes (used by tests and shutdown)."""
        with self._vector_lock:
            futures = list(self._vector_futures)
        if futures:
            wait(futures, timeout=timeout)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(
        self,
        query: str = "",
        mode: str = "hybrid",
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        topic: Optional[str] = None,
        session_id: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
        include_episodes: bool = True,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "query": query,
                "mode": mode,
                "count": 0,
                "results": [],
                "episodes": [],
            }
        mode = (mode or "hybrid").lower()
        if mode not in ("keyword", "semantic", "hybrid"):
            mode = "hybrid"
        limit = max(1, min(int(limit or self.config.search_limit), 200))
        keyword: List[Dict[str, Any]] = []
        semantic: List[Dict[str, Any]] = []
        try:
            if mode in ("keyword", "hybrid"):
                keyword = retrieval.search_keyword(
                    self.store,
                    query,
                    limit=limit,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    topic=topic,
                    session_id=session_id,
                    source=source,
                )
            if mode in ("semantic", "hybrid") and self.vectors is not None:
                semantic = retrieval.search_semantic(
                    self.store,
                    self.vectors,
                    query,
                    limit=limit,
                    session_id=session_id,
                )
                if mode == "semantic" and keyword:
                    keyword = []
        except Exception as exc:
            logger.warning("[MEMORY] search failed: %s", exc)

        if mode == "keyword":
            results = keyword
        elif mode == "semantic":
            results = semantic
        else:
            results = retrieval.merge_hybrid(keyword, semantic, limit)

        episodes: List[Dict[str, Any]] = []
        if include_episodes:
            episodes = retrieval.search_episodes(
                self.store,
                query,
                limit=min(limit, 20),
                from_ts=from_ts,
                to_ts=to_ts,
                session_id=session_id,
            )

        return {
            "enabled": True,
            "query": query,
            "mode": mode,
            "count": len(results),
            "results": results,
            "episodes": episodes,
            "vector_available": bool(
                self.vectors is not None and getattr(self.vectors, "enabled", False)
            ),
            "keyword_count": len(keyword),
            "semantic_count": len(semantic),
        }

    def recall(self, query: str, **kwargs: Any) -> Dict[str, Any]:
        return self.search(query, **kwargs)

    def search_episodes(
        self, query: str = "", limit: int = 20, **kwargs: Any
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            return retrieval.search_episodes(self.store, query, limit=limit, **kwargs)
        except Exception as exc:
            logger.warning("[MEMORY] episode search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Sessions (read side)
    # ------------------------------------------------------------------
    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        source: Optional[str] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "sessions": [], "count": 0}
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        params: List[Any] = []
        clauses: List[str] = []
        if source:
            clauses.append("s.source = ?")
            params.append(source)
        start = retrieval.normalise_time_bound(from_ts)
        end = retrieval.normalise_time_bound(to_ts, end=True)
        if start:
            clauses.append("s.started_at >= ?")
            params.append(start)
        if end:
            clauses.append("s.started_at <= ?")
            params.append(end)
        where = " AND ".join(clauses) if clauses else "1=1"

        total = int(
            self.store.scalar(
                f"SELECT COUNT(*) FROM sessions s WHERE {where}", params, default=0
            )
        )
        rows = self.store.query(
            f"""
            SELECT s.*, COUNT(m.id) AS turn_count,
                   MAX(m.created_at) AS last_message_at
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            WHERE {where}
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        )
        sessions = []
        for row in rows:
            item = _session_from_row(row).to_dict()
            item["turn_count"] = int(row["turn_count"] or 0)
            item["last_message_at"] = row["last_message_at"]
            item["active"] = bool(
                row["ended_at"] is None and row["id"] == self.current_session_id
            )
            sessions.append(item)
        return {
            "enabled": True,
            "sessions": sessions,
            "count": total,
            "limit": limit,
            "offset": offset,
        }

    def get_session(
        self, session_id: str, *, include_episodes: bool = True
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        row = self.store.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if row is None:
            return None
        session = _session_from_row(row).to_dict()
        turns = self._turns_for_session(session_id)
        session["turn_count"] = len(turns)
        payload: Dict[str, Any] = {
            "enabled": True,
            "session": session,
            "turns": [turn.to_dict() for turn in turns],
            "summaries": [s.to_dict() for s in summaries.list_summaries(self.store, session_id)],
        }
        if include_episodes:
            ep_rows = self.store.query(
                "SELECT * FROM episodes WHERE session_id = ? ORDER BY occurred_at ASC",
                (session_id,),
            )
            payload["episodes"] = [_episode_from_row(r).to_dict() for r in ep_rows]
        return payload

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"deleted": False}
        row = self.store.query_one("SELECT id FROM sessions WHERE id = ?", (session_id,))
        if row is None:
            return {"deleted": False, "session_id": session_id}
        turns = self.store.scalar(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,), default=0
        )
        self.store.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        if self.vectors is not None:
            self.vectors.delete_session(session_id)
        with self._session_lock:
            if self._session_id == session_id:
                self._session_id = None
        return {"deleted": True, "session_id": session_id, "turns": int(turns)}

    def set_session_title(self, session_id: str, title: str) -> bool:
        if not self.enabled:
            return False
        with self.store.transaction() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (title[:300], session_id)
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Facts (semantic memory)
    # ------------------------------------------------------------------
    def upsert_fact(
        self,
        subject: str,
        predicate: str,
        object_value: str,
        *,
        category: str = "general",
        confidence: float = 1.0,
        source_message_id: Optional[str] = None,
        fact_id: Optional[str] = None,
    ) -> Optional[FactRecord]:
        if not self.enabled:
            return None
        subject = (subject or "").strip()
        predicate = (predicate or "").strip()
        object_value = (object_value or "").strip()
        if not subject or not predicate or not object_value:
            return None
        if self._contains_secret(object_value):
            logger.warning("[MEMORY] refused to store a secret-looking fact")
            return None
        try:
            existing = self.store.query_one(
                """
                SELECT * FROM facts
                WHERE deleted_at IS NULL AND subject = ? AND predicate = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (subject, predicate),
            )
            now = utc_now_iso()
            if existing is not None:
                if (existing["object"] or "") == object_value and existing["category"] == category:
                    self.store.execute(
                        "UPDATE facts SET confidence = ?, updated_at = ? WHERE id = ?",
                        (float(confidence), now, existing["id"]),
                    )
                    return _fact_from_row(
                        self.store.query_one("SELECT * FROM facts WHERE id = ?", (existing["id"],))
                    )
                self._insert_fact_revision(existing, reason="upsert")
                self.store.execute(
                    """
                    UPDATE facts
                    SET object = ?, category = ?, confidence = ?, updated_at = ?,
                        source_message_id = COALESCE(?, source_message_id)
                    WHERE id = ?
                    """,
                    (
                        object_value,
                        category,
                        float(confidence),
                        now,
                        source_message_id,
                        existing["id"],
                    ),
                )
                return _fact_from_row(
                    self.store.query_one("SELECT * FROM facts WHERE id = ?", (existing["id"],))
                )

            fid = fact_id or str(uuid.uuid4())
            self.store.execute(
                """
                INSERT INTO facts
                    (id, subject, predicate, object, category, confidence,
                     source_message_id, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    fid,
                    subject,
                    predicate,
                    object_value,
                    category,
                    float(confidence),
                    source_message_id,
                    now,
                    now,
                ),
            )
            row = self.store.query_one("SELECT * FROM facts WHERE id = ?", (fid,))
            return _fact_from_row(row) if row is not None else None
        except Exception as exc:
            logger.warning("[MEMORY] upsert_fact failed: %s", exc)
            return None

    def _contains_secret(self, text: str) -> bool:
        try:
            from friday.tools.memory import _contains_secrets

            return bool(_contains_secrets(text))
        except Exception:
            return False

    def _insert_fact_revision(self, row, reason: str) -> None:
        self.store.execute(
            """
            INSERT INTO fact_revisions
                (id, fact_id, old_subject, old_predicate, old_object,
                 old_category, old_confidence, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                row["id"],
                row["subject"],
                row["predicate"],
                row["object"],
                row["category"],
                float(row["confidence"] or 0.0),
                reason,
                utc_now_iso(),
            ),
        )

    def list_facts(
        self,
        query: str = "",
        category: Optional[str] = None,
        *,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "facts": [], "count": 0}
        params: List[Any] = []
        clauses: List[str] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if category:
            clauses.append("category = ?")
            params.append(category)
        tokens = [t for t in retrieval._HOSTED.findall(query or "")]
        for token in tokens:
            pattern = f"%{token}%"
            params.extend([pattern, pattern, pattern])
            clauses.append("(subject LIKE ? OR predicate LIKE ? OR object LIKE ?)")
        where = " AND ".join(clauses) if clauses else "1=1"
        total = int(
            self.store.scalar(f"SELECT COUNT(*) FROM facts WHERE {where}", params, default=0)
        )
        rows = self.store.query(
            f"SELECT * FROM facts WHERE {where} ORDER BY updated_at DESC, created_at DESC LIMIT ? OFFSET ?",
            params + [max(1, min(int(limit), 500)), max(0, int(offset))],
        )
        return {
            "enabled": True,
            "facts": [_fact_from_row(row).to_dict() for row in rows],
            "count": total,
        }

    def get_fact(self, fact_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        row = self.store.query_one("SELECT * FROM facts WHERE id = ?", (fact_id,))
        if row is None:
            return None
        payload = _fact_from_row(row).to_dict()
        revisions = self.store.query(
            "SELECT * FROM fact_revisions WHERE fact_id = ? ORDER BY created_at ASC",
            (fact_id,),
        )
        payload["revisions"] = [dict(r) for r in revisions]
        return payload

    def correct_fact(
        self,
        fact_id: str,
        *,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object_value: Optional[str] = None,
        category: Optional[str] = None,
        confidence: Optional[float] = None,
        reason: str = "",
    ) -> Optional[FactRecord]:
        if not self.enabled:
            return None
        row = self.store.query_one("SELECT * FROM facts WHERE id = ?", (fact_id,))
        if row is None or row["deleted_at"]:
            return None
        if object_value is not None and self._contains_secret(object_value):
            raise ValueError("Fact content looks sensitive and was not stored")
        self._insert_fact_revision(row, reason or "correction")
        now = utc_now_iso()
        self.store.execute(
            """
            UPDATE facts
            SET subject = ?, predicate = ?, object = ?, category = ?,
                confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                (subject if subject is not None else row["subject"]).strip(),
                (predicate if predicate is not None else row["predicate"]).strip(),
                (object_value if object_value is not None else row["object"]).strip(),
                category if category is not None else row["category"],
                float(confidence) if confidence is not None else float(row["confidence"]),
                now,
                fact_id,
            ),
        )
        return _fact_from_row(
            self.store.query_one("SELECT * FROM facts WHERE id = ?", (fact_id,))
        )

    def delete_fact(self, fact_id: str, *, hard: bool = False) -> bool:
        if not self.enabled:
            return False
        row = self.store.query_one("SELECT id FROM facts WHERE id = ?", (fact_id,))
        if row is None:
            return False
        if hard:
            self.store.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        else:
            self.store.execute(
                "UPDATE facts SET deleted_at = ? WHERE id = ?",
                (utc_now_iso(), fact_id),
            )
        return True

    def restore_fact(self, fact_id: str) -> bool:
        if not self.enabled:
            return False
        with self.store.transaction() as conn:
            cursor = conn.execute(
                "UPDATE facts SET deleted_at = NULL WHERE id = ?", (fact_id,)
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Tasks (durable records only)
    # ------------------------------------------------------------------
    def create_task(
        self,
        goal: str,
        *,
        source_session_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[TaskRecord]:
        if not self.enabled:
            return None
        try:
            return tasks.create_task(
                self.store,
                goal,
                source_session_id=source_session_id or self.current_session_id,
                meta=meta,
            )
        except Exception as exc:
            logger.warning("[MEMORY] create_task failed: %s", exc)
            return None

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        if not self.enabled:
            return None
        return tasks.get_task(self.store, task_id)

    def list_tasks(
        self, state: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[TaskRecord]:
        if not self.enabled:
            return []
        return tasks.list_tasks(self.store, state=state, limit=limit, offset=offset)

    def cancel_task(self, task_id: str, reason: str = "") -> Optional[TaskRecord]:
        if not self.enabled:
            return None
        return tasks.cancel_task(self.store, task_id, reason)

    def resume_task(self, task_id: str) -> Optional[TaskRecord]:
        if not self.enabled:
            return None
        return tasks.resume_task(self.store, task_id)

    def complete_task(self, task_id: str) -> Optional[TaskRecord]:
        if not self.enabled:
            return None
        return tasks.complete_task(self.store, task_id)

    def add_task_step(self, task_id: str, action: str, **kwargs: Any) -> Optional[TaskStepRecord]:
        if not self.enabled:
            return None
        return tasks.add_step(self.store, task_id, action, **kwargs)

    def update_task_step(self, step_id: str, **kwargs: Any) -> Optional[TaskStepRecord]:
        if not self.enabled:
            return None
        return tasks.update_step(self.store, step_id, **kwargs)

    # ------------------------------------------------------------------
    # Stats / retention / maintenance
    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "source": self.source}
        try:
            db_size = os.path.getsize(self.store.db_path) if os.path.exists(self.store.db_path) else 0
            return {
                "enabled": True,
                "source": self.source,
                "db_path": self.store.db_path,
                "db_size_bytes": db_size,
                "schema_version": self.store.version,
                "sessions": self.store.count("sessions"),
                "messages": self.store.count("messages"),
                "summaries": self.store.count("summaries"),
                "episodes": self.store.count("episodes"),
                "facts": self.store.count("facts"),
                "tasks": self.store.count("tasks"),
                "task_steps": self.store.count("task_steps"),
                "current_session_id": self.current_session_id,
                "retention_days": self.config.retention_days,
                "vector": {
                    "enabled": bool(self.vectors is not None),
                    "available": bool(
                        self.vectors is not None and self.vectors.available()
                    ),
                    "count": self.vectors.count() if self.vectors is not None else 0,
                },
            }
        except Exception as exc:
            logger.warning("[MEMORY] stats failed: %s", exc)
            return {"enabled": True, "error": str(exc)}

    def prune(
        self,
        dry_run: bool = True,
        retention_days: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "dry_run": dry_run, "deleted": 0}
        days = self.config.retention_days if retention_days is None else int(retention_days)
        if days <= 0:
            return {
                "enabled": True,
                "dry_run": dry_run,
                "deleted": 0,
                "retention_days": days,
                "sessions": [],
                "message": "Retention disabled (retention_days=0); nothing pruned.",
            }
        current = now or datetime.now(timezone.utc)
        cutoff = (current - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")
        rows = self.store.query(
            "SELECT id, started_at FROM sessions WHERE started_at < ? ORDER BY started_at ASC",
            (cutoff,),
        )
        ids = [row["id"] for row in rows]
        if dry_run or not ids:
            return {
                "enabled": True,
                "dry_run": dry_run,
                "deleted": 0,
                "would_delete": len(ids),
                "session_ids": ids,
                "retention_days": days,
                "cutoff": cutoff,
            }
        for session_id in ids:
            self.delete_session(session_id)
        return {
            "enabled": True,
            "dry_run": False,
            "deleted": len(ids),
            "session_ids": ids,
            "retention_days": days,
            "cutoff": cutoff,
        }

    def backup(self, destination: Optional[str] = None) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            if destination is None:
                os.makedirs(self.config.backup_dir, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                destination = os.path.join(self.config.backup_dir, f"memory-{stamp}.db")
            return self.store.backup(destination)
        except Exception as exc:
            logger.warning("[MEMORY] backup failed: %s", exc)
            return None

    def restore(self, backup_path: str) -> bool:
        if not self.enabled:
            return False
        try:
            self.store.restore_from(backup_path)
            return True
        except Exception as exc:
            logger.warning("[MEMORY] restore failed: %s", exc)
            return False

    def integrity_check(self) -> str:
        if not self.enabled:
            return "disabled"
        try:
            return self.store.integrity_check()
        except Exception as exc:
            return f"error: {exc}"

    # ------------------------------------------------------------------
    # Web research → memory integration (Phase 2 addon)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_facts_from_snippets(snippets: List[str], max_facts: int = 10) -> List[Dict[str, str]]:
        """Very simple extractive fact miner over search result snippets.

        Heuristic: treat lines that look like ``Subject - Predicate - Object`` or
        ``Subject is Object`` as candidate facts.  The predicate is inferred from
        surrounding context (e.g. "X is Y" -> predicate="is").

        Returns a list of ``{subject, predicate, object}`` dicts ready for
        :meth:`upsert_fact`.
        """
        import re

        facts: List[Dict[str, str]] = []
        seen: set = set()

        for snippet in snippets or []:
            text = (snippet or "").strip().replace("\n", " ")
            if not text:
                continue

            # Pattern: "Subject is Object" / "Subject was Y" / "X became Y"
            for m in re.finditer(
                r"([A-Z][A-Za-z0-9\-\s]{2,50})\s+(?:is|was|are|were|be|been|has\s+had|had)\s+([A-Z][A-Za-z0-9\-\s]{2,50})",
                text,
            ):
                subject = m.group(1).strip().rstrip(".,;:")
                obj = m.group(2).strip().rstrip(".,;:")
                if len(subject) >= 2 and len(obj) >= 2:
                    key = (subject.lower(), obj.lower())
                    if key not in seen:
                        seen.add(key)
                        facts.append({"subject": subject, "predicate": "is", "object": obj})

            # Pattern: "Subject - Predicate - Object" (pipe-separated or dash)
            for m in re.finditer(
                r"([A-Z][A-Za-z0-9\-\s]{2,50})\s*[|—]\s*([A-Z][A-Za-z0-9\-\s]{2,50})\s*[|—]\s*([A-Z][A-Za-z0-9\-\s]{2,50})",
                text,
            ):
                subject, pred, obj = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                if len(subject) >= 2 and len(pred) >= 2 and len(obj) >= 2:
                    key = (subject.lower(), pred.lower(), obj.lower())
                    if key not in seen:
                        seen.add(key)
                        facts.append({"subject": subject, "predicate": pred, "object": obj})

        # Deduplicate by (subject, predicate, object) case-insensitive
        uniq: List[Dict[str, str]] = []
        final_seen: set = set()
        for f in facts:
            key = (f["subject"].lower(), f["predicate"].lower(), f["object"].lower())
            if key not in final_seen:
                final_seen.add(key)
                uniq.append(f)
            if len(uniq) >= max_facts:
                break
        return uniq

    @staticmethod
    def _get_ddg() -> "_DuckDuckGoProvider":
        import threading

        _DDG_CACHE: Optional["_DuckDuckGoProvider"] = None
        _DDG_LOCK = threading.Lock()

        def _get() -> "_DuckDuckGoProvider":
            global _DDG_CACHE
            with _DDG_LOCK:
                if _DDG_CACHE is None:
                    _DDG_CACHE = _DuckDuckGoProvider()
                return _DDG_CACHE

        return _get()

    def research_and_store_memories(self, query: str, max_results: int = 5, max_facts: int = 10) -> Dict[str, Any]:
        """Run a web search for *query* and upsert extracted facts into memory.

        Returns a dict with:
          * ``"results"`` — number of search results fetched
          * ``"facts_stored"`` — number of facts successfully stored
          * ``"fact_ids"`` — list of fact ids that were inserted
          * ``"error"`` — present if something went wrong (but the function
            never raises; failures are logged and returned gracefully).
        """
        if not query or not query.strip():
            return {"results": 0, "facts_stored": 0, "fact_ids": [], "error": "empty query"}

        try:
            cfg = {
                "db_path": ".data/memory.db",
                "vector_enabled": False,
                "dedupe_window_seconds": 0,
            }
        except Exception as exc:  # pragma: no cover
            logger.warning("[MEMORY] could not build config: %s", exc)
            return {"results": 0, "facts_stored": 0, "fact_ids": [], "error": str(exc)}

        try:
            svc = MemoryService.from_config(cfg, source="web", vector_worker=False)
        except Exception as exc:
            logger.warning("[MEMORY] could not create MemoryService: %s", exc)
            return {"results": 0, "facts_stored": 0, "fact_ids": [], "error": str(exc)}

        try:
            from friday.research.search.ddg_provider import DuckDuckGoSearchProvider

            ddg = DuckDuckGoSearchProvider(api_key="")
            snippets = ddg.search(query, max_results=max_results)

            # Normalise to list of {title, url, snippet} dicts
            normalized: List[Dict[str, str]] = []
            for r in snippets:
                if isinstance(r, dict):
                    normalized.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "snippet": r.get("snippet", ""),
                        }
                    )
                else:
                    normalized.append({"title": str(r), "url": "", "snippet": ""})

            # Extract candidate facts from snippets
            candidates = self._extract_facts_from_snippets(
                [s.get("snippet", "") or "" for s in normalized], max_facts=max_facts
            )

            stored_ids: List[str] = []
            for cand in candidates:
                try:
                    # Reject anything that looks like a secret/credential
                    if svc._contains_secret(cand["object"]):
                        continue
                    rec = svc.upsert_fact(
                        subject=cand["subject"],
                        predicate=cand["predicate"],
                        object_value=cand["object"],
                        category="web_research",
                        confidence=0.7,
                    )
                    if rec and rec.id:
                        stored_ids.append(rec.id)
                except Exception as exc:
                    logger.debug("[MEMORY] fact upsert failed for %s: %s", cand, exc)

            svc.close()
            return {
                "results": len(normalized),
                "facts_stored": len(stored_ids),
                "fact_ids": stored_ids,
                "error": None,
            }
        except Exception as exc:  # never raise
            logger.warning("[MEMORY] research_and_store_memories failed: %s", exc)
            return {"results": 0, "facts_stored": 0, "fact_ids": [], "error": str(exc)}

    @staticmethod
    def api_research_and_store(query: str, max_results: int = 5, max_facts: int = 10) -> Dict[str, Any]:
        """Public helper: run web research and store facts in memory.

        Meant to be called from an API route or the conversation loop.  Never
        raises; every failure is caught and reported in the returned dict.
        """
        return MemoryService.research_and_store_memories(query, max_results=max_results, max_facts=max_facts)


# ----------------------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.current_session_id:
                self.end_session(generate_summary=False)
            self.flush_vectors(timeout=5.0)
        finally:
            if self._vector_executor is not None:
                self._vector_executor.shutdown(wait=False)
            self.store.close()
