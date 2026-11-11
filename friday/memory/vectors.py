"""Optional ChromaDB index for semantic conversation memory.

Semantic search is a *second* retrieval path. Keyword/date/topic search lives
entirely in SQLite FTS5 and keeps working when Chroma is missing, disabled, or
broken. Every method here fails soft: an unavailable vector backend returns a
clear status instead of raising into the conversation loop.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryVectorIndex:
    """Persistent cosine collection of recorded turns (one vector per message)."""

    def __init__(
        self,
        path: str,
        collection: str = "conversation_memory",
        enabled: bool = True,
    ):
        self.path = os.path.abspath(path)
        self.collection_name = collection
        self.enabled = bool(enabled)
        self._client = None
        self._collection = None
        self._embedder = None
        self._lock = threading.Lock()
        self._error = ""

    # ------------------------------------------------------------------
    @property
    def last_error(self) -> str:
        return self._error

    def _embedder_instance(self):
        if self._embedder is None:
            from friday.rag.embedder import get_embedder

            self._embedder = get_embedder()
        return self._embedder

    def _coll(self):
        if not self.enabled:
            raise RuntimeError("vector memory disabled")
        if self._collection is not None:
            return self._collection
        with self._lock:
            if self._collection is not None:
                return self._collection
            import chromadb

            os.makedirs(self.path, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.path)
            self._collection = self._client.get_or_create_collection(
                self.collection_name, metadata={"hnsw:space": "cosine"}
            )
            logger.info(
                "[MEMORY] vector index ready: collection=%s path=%s",
                self.collection_name,
                self.path,
            )
            return self._collection

    # ------------------------------------------------------------------
    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            self._coll()
            return True
        except Exception as exc:
            self._error = str(exc)
            logger.warning("[MEMORY] vector index unavailable: %s", exc)
            return False

    def count(self) -> int:
        if not self.enabled:
            return 0
        try:
            return int(self._coll().count())
        except Exception as exc:
            self._error = str(exc)
            return 0

    def add(self, records: List[Dict[str, Any]]) -> int:
        """Upsert ``[{id, text, metadata}, ...]``. Returns the number written."""
        if not self.enabled or not records:
            return 0
        try:
            coll = self._coll()
            ids = [str(r["id"]) for r in records]
            docs = [str(r.get("text") or "") for r in records]
            metas = [dict(r.get("metadata") or {}) for r in records]
            vectors = self._embedder_instance().embed(docs)
            coll.upsert(
                ids=ids,
                documents=docs,
                embeddings=[v.tolist() for v in vectors],
                metadatas=metas,
            )
            return len(ids)
        except Exception as exc:
            self._error = str(exc)
            logger.warning("[MEMORY] vector upsert failed: %s", exc)
            return 0

    def delete(self, ids: List[str]) -> int:
        if not self.enabled or not ids:
            return 0
        try:
            self._coll().delete(ids=[str(i) for i in ids])
            return len(ids)
        except Exception as exc:
            self._error = str(exc)
            logger.warning("[MEMORY] vector delete failed: %s", exc)
            return 0

    def delete_session(self, session_id: str) -> int:
        if not self.enabled or not session_id:
            return 0
        try:
            coll = self._coll()
            coll.delete(where={"session_id": session_id})
            return 1
        except Exception as exc:
            self._error = str(exc)
            logger.warning("[MEMORY] vector session delete failed: %s", exc)
            return 0

    def search(
        self,
        query: str,
        k: int = 20,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return ``[{id, score, metadata}, ...]`` ordered by cosine similarity."""
        if not self.enabled or not query.strip():
            return []
        try:
            coll = self._coll()
            if coll.count() == 0:
                return []
            vector = self._embedder_instance().embed([query], query=True)
            where = {"session_id": session_id} if session_id else None
            result = coll.query(
                query_embeddings=[vector[0].tolist()],
                n_results=max(1, min(int(k), 200)),
                where=where,
                include=["metadatas", "distances"],
            )
            ids = (result.get("ids") or [[]])[0]
            metas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            out = []
            for index, doc_id in enumerate(ids):
                distance = float(distances[index]) if index < len(distances) else 1.0
                out.append(
                    {
                        "id": str(doc_id),
                        "score": max(0.0, min(1.0, 1.0 - distance)),
                        "metadata": dict(metas[index] or {}) if index < len(metas) else {},
                    }
                )
            return out
        except Exception as exc:
            self._error = str(exc)
            logger.warning("[MEMORY] vector search failed: %s", exc)
            return []
