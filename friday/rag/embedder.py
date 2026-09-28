"""
Local embedding wrapper for RAG.

Uses ChromaDB's ONNX `all-MiniLM-L6-v2` embedder (numpy/onnxruntime only —
deliberately avoids sentence-transformers/scipy, which are broken under the
project's numpy 2.x pin).  Lazily initialised so importing friday.rag is cheap.
"""
import threading
import numpy as np
from functools import lru_cache

from friday.utils.logger import get_logger

logger = get_logger(__name__)

_MODEL_DIM = 384


class Embedder:
    """Thread-safe, lazily-loaded embedding service."""

    def __init__(self):
        self._ef = None
        self._lock = threading.Lock()

    def _load(self):
        if self._ef is not None:
            return
        with self._lock:
            if self._ef is not None:
                return
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self._ef = DefaultEmbeddingFunction()
            logger.info("[RAG] Embedder loaded: all-MiniLM-L6-v2 (ONNX, dim=%d)", _MODEL_DIM)

    def embed(self, texts: list, query: bool = False) -> np.ndarray:
        """Embed a list of texts into a (N, 384) float32 matrix (l2-normalised)."""
        if not texts:
            return np.zeros((0, _MODEL_DIM), dtype=np.float32)
        self._load()
        if query and len(texts) == 1:
            vecs = self._ef.embed_query(texts[0])
            arr = np.asarray([vecs], dtype=np.float32)
        else:
            vecs = self._ef(texts)
            arr = np.asarray([np.asarray(v, dtype=np.float32) for v in vecs], dtype=np.float32)
        arr = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
        return arr

    @staticmethod
    def cosine_matrix(query_vecs: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """Cosine scores (query x doc). Inputs should already be L2-normalised."""
        if query_vecs.size == 0 or doc_vecs.size == 0:
            return np.zeros((query_vecs.shape[0], doc_vecs.shape[0]), dtype=np.float32)
        if np.any(np.linalg.norm(query_vecs, axis=1) > 0) and np.any(np.linalg.norm(doc_vecs, axis=1) > 0):
            return np.clip(query_vecs @ doc_vecs.T, -1.0, 1.0)
        return np.zeros((query_vecs.shape[0], doc_vecs.shape[0]), dtype=np.float32)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return Embedder()