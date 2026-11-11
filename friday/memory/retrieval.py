"""Retrieval for persistent memory.

Three retrieval paths, merged deterministically:

* **keyword / phrase** — SQLite FTS5 over raw user + assistant text
* **date / topic / source** — indexed SQL predicates (no model involved)
* **meaning** — optional ChromaDB cosine search, never required

Hybrid mode uses Reciprocal Rank Fusion (RRF). If the vector backend is missing
or disabled it silently degrades to keyword results, so the API contract is
stable.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from friday.memory.models import EpisodeRecord, TurnRecord
from friday.memory.store import MemoryStore
from friday.utils.logger import get_logger

logger = get_logger(__name__)

_HOSTED = re.compile(r"[A-Za-z0-9_]+")
_TOKEN = re.compile(r"[^A-Za-z0-9_]+")

_MSG_SELECT = """
SELECT m.*, s.title AS session_title, s.source AS session_source,
       s.started_at AS session_started_at, s.ended_at AS session_ended_at
FROM messages m
LEFT JOIN sessions s ON s.id = m.session_id
"""


# ----------------------------------------------------------------------
# Time helpers
# ----------------------------------------------------------------------
def normalise_time_bound(value: Optional[str], end: bool = False) -> Optional[str]:
    """Normalise a date or datetime to the stored ISO-8601 UTC format."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text + ("T23:59:59Z" if end else "T00:00:00Z")
    text = text.replace(" ", "T")
    if text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text):
        return text
    if len(text) == 16:
        return text + ":00Z"
    return text + "Z"


def _time_clause(
    column: str,
    from_ts: Optional[str],
    to_ts: Optional[str],
    params: List[Any],
) -> List[str]:
    clauses: List[str] = []
    start = normalise_time_bound(from_ts)
    end = normalise_time_bound(to_ts, end=True)
    if start:
        clauses.append(f"{column} >= ?")
        params.append(start)
    if end:
        clauses.append(f"{column} <= ?")
        params.append(end)
    return clauses


def _topic_clause(topic: Optional[str], params: List[Any]) -> List[str]:
    if not topic:
        return []
    like = f"%{topic.strip()}%"
    params.extend([like, like])
    return ["(m.topic LIKE ? OR s.title LIKE ?)"]


# ----------------------------------------------------------------------
# Keyword search
# ----------------------------------------------------------------------
def _match_expression(query: str) -> str:
    tokens = _HOSTED.findall(query or "")
    return " AND ".join(f"{token}*" for token in tokens)


def _row_to_turn(row: sqlite3.Row) -> TurnRecord:
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


def _decorate(row: sqlite3.Row, match: str, score: float) -> Dict[str, Any]:
    item = _row_to_turn(row).to_dict()
    item["session"] = {
        "id": row["session_id"],
        "title": row["session_title"],
        "source": row["session_source"],
        "started_at": row["session_started_at"],
        "ended_at": row["session_ended_at"],
    }
    item["match"] = match
    item["score"] = round(float(score), 6)
    return item


def search_keyword(
    store: MemoryStore,
    query: str,
    limit: int = 20,
    *,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    topic: Optional[str] = None,
    session_id: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """FTS5 keyword search with an automatic LIKE fallback."""
    limit = max(1, min(int(limit), 200))
    params: List[Any] = []
    clauses: List[str] = []
    match = _match_expression(query)

    if match:
        params.append(match)
        clauses.append("messages_fts MATCH ?")
    clauses.extend(_time_clause("m.created_at", from_ts, to_ts, params))
    clauses.extend(_topic_clause(topic, params))
    if session_id:
        clauses.append("m.session_id = ?")
        params.append(session_id)
    if source:
        clauses.append("s.source = ?")
        params.append(source)

    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(limit)
    sql = f"""
        SELECT m.*, s.title AS session_title, s.source AS session_source,
               s.started_at AS session_started_at, s.ended_at AS session_ended_at,
               bm25(messages_fts) AS rank
        FROM messages_fts
        JOIN messages m ON m.rowid = messages_fts.rowid
        LEFT JOIN sessions s ON s.id = m.session_id
        WHERE {where}
        ORDER BY rank ASC, m.created_at DESC
        LIMIT ?
    """
    try:
        rows = store.query(sql, params)
    except sqlite3.Error as exc:
        logger.warning("[MEMORY] FTS query failed (%s); falling back to LIKE", exc)
        rows = _search_like(
            store, query, limit, from_ts, to_ts, topic, session_id, source
        )

    results = []
    for row in rows:
        rank = float(row["rank"]) if "rank" in row.keys() and row["rank"] is not None else -1.0
        results.append(_decorate(row, "keyword", 1.0 / (1.0 + abs(rank))))
    return results


def _search_like(
    store: MemoryStore,
    query: str,
    limit: int,
    from_ts: Optional[str],
    to_ts: Optional[str],
    topic: Optional[str],
    session_id: Optional[str],
    source: Optional[str],
) -> List[sqlite3.Row]:
    params: List[Any] = []
    clauses: List[str] = []
    tokens = _HOSTED.findall(query or "")
    for token in tokens:
        pattern = f"%{token}%"
        params.extend([pattern, pattern])
        clauses.append("(m.raw_text LIKE ? OR m.response_text LIKE ?)")
    clauses.extend(_time_clause("m.created_at", from_ts, to_ts, params))
    clauses.extend(_topic_clause(topic, params))
    if session_id:
        clauses.append("m.session_id = ?")
        params.append(session_id)
    if source:
        clauses.append("s.source = ?")
        params.append(source)
    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(limit)
    rows = store.query(
        f"{_MSG_SELECT} WHERE {where} ORDER BY m.created_at DESC LIMIT ?", params
    )
    # Advertise the rank column so the common decorator works.
    return [_with_rank(row, -1.0) for row in rows]


class _RankedRow(dict):
    """sqlite3.Row-like mapping with an extra synthetic ``rank`` value."""

    def __getitem__(self, key):
        if key == "rank":
            return self.get("__rank", -1.0)
        return super().__getitem__(key)

    def keys(self):  # pragma: no cover - trivial
        return list(super().keys()) + ["rank"]


def _with_rank(row: sqlite3.Row, rank: float) -> _RankedRow:
    data = _RankedRow({key: row[key] for key in row.keys()})
    data["__rank"] = rank
    return data


# ----------------------------------------------------------------------
# Semantic search
# ----------------------------------------------------------------------
def search_semantic(
    store: MemoryStore,
    vectors,
    query: str,
    limit: int = 20,
    *,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if vectors is None or not getattr(vectors, "enabled", False):
        return []
    hits = vectors.search(query, k=limit, session_id=session_id)
    if not hits:
        return []
    ids = [hit["id"] for hit in hits]
    placeholders = ",".join("?" for _ in ids)
    rows = store.query(
        f"{_MSG_SELECT} WHERE m.id IN ({placeholders})", ids
    )
    by_id = {row["id"]: row for row in rows}
    results = []
    for hit in hits:
        row = by_id.get(hit["id"])
        if row is None:
            continue
        results.append(_decorate(row, "semantic", hit["score"]))
    return results


# ----------------------------------------------------------------------
# Hybrid merge
# ----------------------------------------------------------------------
def merge_hybrid(
    keyword: Iterable[Dict[str, Any]],
    semantic: Iterable[Dict[str, Any]],
    limit: int,
    rrf_k: int = 60,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion over two ordered result lists."""
    keyword = list(keyword)
    semantic = list(semantic)
    if not semantic:
        return keyword[:limit]
    if not keyword:
        return semantic[:limit]

    scores: Dict[str, float] = {}
    payload: Dict[str, Dict[str, Any]] = {}
    matches: Dict[str, set] = {}

    for rank, item in enumerate(keyword, start=1):
        mid = item["id"]
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
        payload[mid] = item
        matches.setdefault(mid, set()).add("keyword")

    for rank, item in enumerate(semantic, start=1):
        mid = item["id"]
        scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
        payload.setdefault(mid, item)
        matches.setdefault(mid, set()).add("semantic")

    merged = []
    for mid, score in sorted(scores.items(), key=lambda pair: pair[1], reverse=True):
        item = dict(payload[mid])
        found = matches.get(mid, set())
        item["match"] = "hybrid" if len(found) > 1 else next(iter(found))
        item["score"] = round(score, 6)
        merged.append(item)
    return merged[:limit]


# ----------------------------------------------------------------------
# Episodes
# ----------------------------------------------------------------------
def search_episodes(
    store: MemoryStore,
    query: str = "",
    limit: int = 20,
    *,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: List[Any] = []
    clauses: List[str] = []
    tokens = _HOSTED.findall(query or "")
    for token in tokens:
        pattern = f"%{token}%"
        params.extend([pattern, pattern, pattern])
        clauses.append("(e.title LIKE ? OR e.detail LIKE ? OR e.kind LIKE ?)")
    clauses.extend(_time_clause("e.occurred_at", from_ts, to_ts, params))
    if session_id:
        clauses.append("e.session_id = ?")
        params.append(session_id)
    where = " AND ".join(clauses) if clauses else "1=1"
    params.append(max(1, min(int(limit), 200)))
    rows = store.query(
        f"SELECT e.* FROM episodes e WHERE {where} ORDER BY e.occurred_at DESC LIMIT ?",
        params,
    )
    return [
        EpisodeRecord(
            id=row["id"],
            session_id=row["session_id"],
            kind=row["kind"],
            title=row["title"],
            detail=row["detail"],
            importance=float(row["importance"] or 0.0),
            occurred_at=row["occurred_at"],
            source_message_id=row["source_message_id"],
            meta_json=row["meta_json"],
        ).to_dict()
        for row in rows
    ]
