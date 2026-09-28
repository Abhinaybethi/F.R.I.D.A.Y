"""
ChromaDB-backed vector index for knowledge chunks.

Thin wrapper around a persistent local collection:
  - stores chunk text + embeddings + metadata
  - semantic query by id (returns ids, distances, metadata)
  - upsert + count
Deliberately does NOT use Chroma's built-in query/document APIs for ranking
— the pipeline pulls raw candidate vectors and reranks with its own logic.
"""
import os
import threading
from typing import List, Dict, Optional, Tuple

from friday.rag.models import RAGChunk, RAGConfig
from friday.rag.embedder import Embedder
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def default_persist_dir(project_root: Optional[str] = None) -> str:
    root = project_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, ".data", "rag")


class VectorIndex:
    """Persistent ChromaDB collection manager."""

    def __init__(self, config: RAGConfig, embedder: Optional[Embedder] = None, root: Optional[str] = None):
        self.config = config
        self.embedder = embedder or Embedder()
        persist_dir = config.persist_dir or default_persist_dir(root)
        self._persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)
        self._client = None
        self._coll = None
        self._lock = threading.Lock()

    def _collection(self):
        if self._coll is not None:
            return self._coll
        with self._lock:
            if self._coll is not None:
                return self._coll
            import chromadb
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._coll = self._client.get_or_create_collection(
                self.config.collection, metadata={"hnsw:space": "cosine"}
            )
            logger.info("[RAG] Index ready: collection=%s persist=%s", self.config.collection, self._persist_dir)
            return self._coll

    def count(self) -> int:
        try:
            return self._collection().count()
        except Exception as e:
            logger.warning("[RAG] count failed: %s", e)
            return 0

    def add_chunks(self, chunks: List[RAGChunk]):
        if not chunks:
            return 0
        # Dedupe by id within the batch (identical windows gain identical ids).
        unique = {c.id: c for c in chunks}.values()
        chunks = list(unique)
        coll = self._collection()
        ids = [c.id for c in chunks]
        docs = [c.text for c in chunks]
        metas = [
            {
                "source": c.source, "document": c.document, "section": c.section,
                "topic": c.topic, "project": c.project, "content_type": c.content_type,
                "timestamp": c.timestamp, "id": c.id,
            }
            for c in chunks
        ]
        vecs = self.embedder.embed(docs)
        # Filter out already-present ids to keep ingestion idempotent.
        existing = coll.get(ids=ids, include=[])["ids"] if ids else []
        keep = [i for i, cid in enumerate(ids) if cid not in existing]
        if not keep:
            return 0
        coll.upsert(
            ids=[ids[i] for i in keep],
            documents=[docs[i] for i in keep],
            embeddings=[vecs[i].tolist() for i in keep],
            metadatas=[metas[i] for i in keep],
        )
        return len(keep)

    def semantic_query(self, query: str, k: int) -> Tuple[List[str], Dict[str, dict]]:
        """Return (ids, {id: {vector_score, metadata}}) for the top-k by cosine."""
        coll = self._collection()
        if coll.count() == 0:
            return [], {}
        qvec = self.embedder.embed([query])
        coll_vecs = coll.get(include=["embeddings", "metadatas"])
        ids = coll_vecs["ids"]
        metas = coll_vecs["metadatas"]
        emb = coll_vecs["embeddings"]
        if emb is None or (hasattr(emb, "__len__") and len(emb) == 0) or not ids:
            return [], {}
        import numpy as np
        mat = np.asarray(emb, dtype=np.float32)
        scores = self.embedder.cosine_matrix(qvec, mat)[0]
        order = scores.argsort()[::-1]
        out_ids, out_map = [], {}
        for i in order[:k]:
            cid = ids[i]
            out_ids.append(cid)
            out_map[cid] = {"vector_score": float(scores[i]), "metadata": dict(metas[i])}
        return out_ids, out_map

    def get_chunks(self, ids: List[str]) -> Dict[str, dict]:
        coll = self._collection()
        if not ids:
            return {}
        got = coll.get(ids=ids)
        out = {}
        for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"]):
            out[cid] = {"text": doc, "metadata": dict(meta or {})}
        return out

    def delete_all(self):
        with self._lock:
            if self._client is not None:
                self._client.delete_collection(self.config.collection)
                self._coll = None
            else:
                coll = self._collection()
                all_ids = coll.get(include=[])["ids"]
                if all_ids:
                    coll.delete(ids=all_ids)