"""SQLite schema and additive migrations for persistent memory.

Everything here is *additive*: the legacy ``memories`` table owned by
``friday.tools.memory`` is never touched. All statements use
``IF NOT EXISTS`` and the schema is versioned with ``PRAGMA user_version`` so
upgrades are repeatable and safe.

Timestamp convention: ISO-8601 UTC strings with second precision
(``2026-11-06T13:47:12Z``) so plain lexicographic comparison works for range
queries, while ``datetime(...)`` also works in SQLite.
"""
from __future__ import annotations

import sqlite3

from friday.utils.logger import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1

_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        started_at  TEXT NOT NULL,
        ended_at    TEXT,
        source      TEXT NOT NULL DEFAULT 'text',
        title       TEXT,
        summary_id  TEXT,
        meta_json   TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id                  TEXT PRIMARY KEY,
        session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        turn_index          INTEGER NOT NULL,
        role                TEXT NOT NULL DEFAULT 'user',
        raw_text            TEXT NOT NULL DEFAULT '',
        resolved_text       TEXT,
        response_text       TEXT,
        intent_action       TEXT,
        intent_target       TEXT,
        tool_status         TEXT,
        verification_status TEXT,
        topic               TEXT,
        created_at          TEXT NOT NULL,
        meta_json           TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS summaries (
        id                     TEXT PRIMARY KEY,
        session_id             TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        kind                   TEXT NOT NULL DEFAULT 'session',
        text                   TEXT NOT NULL,
        generated_by           TEXT NOT NULL DEFAULT 'extractive',
        model                  TEXT,
        source_message_ids_json TEXT,
        created_at             TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS episodes (
        id                TEXT PRIMARY KEY,
        session_id        TEXT REFERENCES sessions(id) ON DELETE CASCADE,
        kind              TEXT NOT NULL,
        title             TEXT NOT NULL,
        detail            TEXT,
        importance        REAL NOT NULL DEFAULT 0.0,
        occurred_at       TEXT NOT NULL,
        source_message_id TEXT,
        meta_json         TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS facts (
        id                TEXT PRIMARY KEY,
        subject           TEXT NOT NULL,
        predicate         TEXT NOT NULL,
        object            TEXT NOT NULL,
        category          TEXT NOT NULL DEFAULT 'general',
        confidence        REAL NOT NULL DEFAULT 1.0,
        source_message_id TEXT,
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        deleted_at        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fact_revisions (
        id            TEXT PRIMARY KEY,
        fact_id       TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
        old_subject   TEXT,
        old_predicate TEXT,
        old_object    TEXT,
        old_category  TEXT,
        old_confidence REAL,
        reason        TEXT,
        created_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id                TEXT PRIMARY KEY,
        goal              TEXT NOT NULL,
        state             TEXT NOT NULL DEFAULT 'pending',
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL,
        completed_at      TEXT,
        source_session_id TEXT,
        meta_json         TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_steps (
        id                  TEXT PRIMARY KEY,
        task_id             TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        step_index          INTEGER NOT NULL,
        action              TEXT NOT NULL DEFAULT '',
        target              TEXT NOT NULL DEFAULT '',
        status              TEXT NOT NULL DEFAULT 'pending',
        idempotency_key     TEXT,
        result_json         TEXT,
        verification_status TEXT,
        error               TEXT,
        started_at          TEXT,
        completed_at        TEXT
    )
    """,
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source)",
    "CREATE INDEX IF NOT EXISTS idx_messages_session_turn ON messages(session_id, turn_index)",
    "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(topic)",
    "CREATE INDEX IF NOT EXISTS idx_summaries_session ON summaries(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_episodes_occurred ON episodes(occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id, step_index)",
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_steps_idem "
        "ON task_steps(task_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    ),
)

_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    raw_text,
    response_text,
    content='messages',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
)
"""

_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, raw_text, response_text)
        VALUES (new.rowid, new.raw_text, new.response_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, raw_text, response_text)
        VALUES ('delete', old.rowid, old.raw_text, old.response_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, raw_text, response_text)
        VALUES ('delete', old.rowid, old.raw_text, old.response_text);
        INSERT INTO messages_fts(rowid, raw_text, response_text)
        VALUES (new.rowid, new.raw_text, new.response_text);
    END
    """,
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create every memory table / index / trigger on ``conn`` if missing.

    Safe to call on every connection open and on an existing database. The WAL
    journal mode persists; the version bump is what records that the additive
    migration has run.
    """
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error as exc:  # pragma: no cover - platform specific
        logger.warning("[MEMORY] WAL unavailable: %s", exc)

    existing_version = 0
    try:
        existing_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    except (sqlite3.Error, TypeError):
        existing_version = 0

    for statement in _TABLES:
        conn.execute(statement)
    for statement in _INDEXES:
        conn.execute(statement)
    conn.execute(_FTS)
    for statement in _TRIGGERS:
        conn.execute(statement)

    # Populate the external-content index for databases created before FTS
    # existed (or for a fresh DB that somehow already had message rows).
    if existing_version < SCHEMA_VERSION:
        try:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            logger.warning("[MEMORY] FTS rebuild failed: %s", exc)

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    except (sqlite3.Error, TypeError):
        return 0
