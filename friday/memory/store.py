"""Low-level, thread-safe SQLite access for the memory layer.

One connection per operation keeps this safe for FastAPI's threadpool and the
voice thread without sharing a connection across threads. Writes are serialised
by SQLite itself via ``busy_timeout``; the schema is created once per store
instance under a lock.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, List, Optional, Sequence

from friday.memory.schema import ensure_schema, schema_version
from friday.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryStore:
    """Thin wrapper around a local SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        self._initialized = False
        self._init_lock = threading.Lock()
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    # ------------------------------------------------------------------
    # Connections / schema
    # ------------------------------------------------------------------
    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    ensure_schema(conn)
                    self._initialized = True
        return conn

    def initialize(self) -> None:
        conn = self._new_connection()
        conn.close()

    @property
    def version(self) -> int:
        with self.connect() as conn:
            return schema_version(conn)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._new_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._new_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(sql, params)
            return int(cursor.lastrowid or 0)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        with self.transaction() as conn:
            cursor = conn.executemany(sql, rows)
            return int(cursor.rowcount or 0)

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = 0) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    def count(self, table: str) -> int:
        allowed = {
            "sessions", "messages", "summaries", "episodes", "facts",
            "fact_revisions", "tasks", "task_steps",
        }
        if table not in allowed:
            raise ValueError(f"Unknown memory table {table!r}")
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}"))

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))

    def backup(self, destination: str) -> str:
        """Copy the live database to ``destination`` using SQLite's backup API."""
        destination = os.path.abspath(destination)
        directory = os.path.dirname(destination)
        if directory:
            os.makedirs(directory, exist_ok=True)
        source = self._new_connection()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        return destination

    def restore_from(self, source_path: str) -> None:
        """Replace the live database with ``source_path`` (backup recovery)."""
        source_path = os.path.abspath(source_path)
        if not os.path.exists(source_path):
            raise FileNotFoundError(source_path)
        source = sqlite3.connect(source_path)
        target = sqlite3.connect(self.db_path)
        try:
            source.backup(target)
            target.commit()
            target.execute("PRAGMA journal_mode=WAL")
        finally:
            target.close()
            source.close()
        self._initialized = False
        self.initialize()

    def close(self) -> None:
        """No persistent connection is held; kept for a symmetric lifecycle API."""
        return None
