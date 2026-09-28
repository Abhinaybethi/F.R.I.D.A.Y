"""
RAGService — orchestrates the retrieval pipeline and owns observability.

Flow (called only for chat/knowledge questions):
  analyzed query
    -> memory router (stable personal facts — separate store)
    -> hybrid retrieval (vector + BM25)
    -> re-rank
    -> relevance gate (anti-hallucination)
    -> context compression (token-budgeted, source-tagged)
    -> prompt-block build
    -> structured [RAG] observability log

Latency per stage and per retrieval is captured and logged (not leaked).
"""
import time
import logging
import threading
from typing import List, Dict

from friday.rag.models import RAGConfig, RAGQuery, RAGResult
from friday.rag.query_analyzer import analyze_query
from friday.rag.index import VectorIndex, default_persist_dir
from friday.rag.embedder import Embedder
from friday.rag.retriever import Retriever
from friday.rag.reranker import Reranker
from friday.rag.relevance_filter import RelevanceFilter
from friday.rag.context_compressor import ContextCompressor, _label
from friday.rag.memory_router import try_recall_memory
from friday.rag.prompt_builder import build_rag_prompt_block
from friday.rag.ingestion import ingest as ingest_documents
from friday.rag.models import RetrievedChunk

logger = logging.getLogger("friday.rag")


class RAGService:
    def __init__(self, config: RAGConfig, callbacks: Dict = None):
        self.config = config
        self.callbacks = callbacks or {}
        self.embedder = Embedder()
        self.index = VectorIndex(config, self.embedder)
        self.retriever = Retriever(self.index, config)
        self.reranker = Reranker(config)
        self.filter = RelevanceFilter(config)
        self.compressor = ContextCompressor(config)
        self._ingested = False
        self._ingest_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def ensure_index(self):
        """Ingest when empty. Never blocks a chat turn on first ingestion."""
        if self._ingested:
            return
        has_chunks = self.index.count() > 0
        if has_chunks:
            self._ingested = True
            return
        if not self.config.auto_ingest:
            return
        if self._ingest_lock.acquire(blocking=False):
            try:
                if self.index.count() == 0:
                    self._ingest()
                self._ingested = True
            finally:
                self._ingest_lock.release()

    def start_background_ingest(self):
        """Kick off ingestion from a daemon thread at startup (non-blocking)."""
        if self.config.auto_ingest and self.index.count() == 0 and not self._ingested:
            threading.Thread(target=self.ensure_index, daemon=True).start()

    def _ingest(self):
        t0 = time.perf_counter()
        try:
            stats = ingest_documents(self.config, self.index, self.embedder)
            self._ingest_ms = (time.perf_counter() - t0) * 1000.0
            logger.info("[RAG] Auto-ingestion took %.0f ms", self._ingest_ms)
        except Exception as e:
            logger.warning("[RAG] Auto-ingestion failed: %s (search degraded)", e)

    def count(self) -> int:
        return self.index.count()

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    def build_result(self, transcript: str, history: List[Dict] = None) -> RAGResult:
        timings = {}
        t0 = time.perf_counter()

        if not self.config.enabled:
            query = analyze_query(transcript, history or [])
            return RAGResult(
                query=query, context_block="", used=False,
                reason="rag_disabled", stats={"total_ms": (time.perf_counter() - t0) * 1000.0},
            )

        query = analyze_query(transcript, history or [])
        timings["analyze"] = time.perf_counter() - t0

        if not query.needs_rag:
            return RAGResult(
                query=query, context_block="", used=False,
                reason="rag_not_needed", stats={"total_ms": (time.perf_counter() - t0) * 1000.0},
            )

        # --- memory first (separate store, never mixed) ---
        t0m = time.perf_counter()
        memory_answer = try_recall_memory(query, self.callbacks.get("recall"))
        timings["memory"] = time.perf_counter() - t0m

        # --- retrieval ---
        self.ensure_index()
        t0r = time.perf_counter()
        candidates = self.retriever.retrieve(query)
        timings["retrieve"] = time.perf_counter() - t0r

        # --- rerank ---
        t0k = time.perf_counter()
        reranked = self.reranker.rerank(candidates, query) if self.config.rerank else candidates
        timings["rerank"] = time.perf_counter() - t0k

        # --- relevance gate ---
        t0f = time.perf_counter()
        gated, passed, reason = self.filter.filter(reranked, query)
        timings["filter"] = time.perf_counter() - t0f

        # --- compress ---
        t0c = time.perf_counter()
        context_block = self.compressor.compress(gated) if self.config.context_compression else "\n\n".join(
            f"[Source: {_label(c.chunk)}]\n{c.chunk.text}" for c in gated
        )
        timings["compress"] = time.perf_counter() - t0c

        result = RAGResult(
            query=query,
            context_block=context_block,
            chunks=reranked,
            final_context=gated,
            used=passed,
            no_context=(not passed),
            reason=reason,
            stats=timings,
            sources=sorted({c.chunk.source for c in gated if c.chunk.source}),
        )
        if memory_answer:
            result.prompt_memory = memory_answer  # type: ignore[attr-defined]

        self._observe(query, result, timings, memory_answer)
        return result

    def build_prompt_block(self, result: RAGResult) -> str:
        memory_answer = getattr(result, "prompt_memory", "")
        return build_rag_prompt_block(
            result,
            memory_answer=memory_answer,
            conversation_context=result.query.conversation_context,
        )

    # ------------------------------------------------------------------
    # Observability (structured, non-flooding)
    # ------------------------------------------------------------------
    def _observe(self, query: RAGQuery, result: RAGResult, timings: dict, memory_answer: str = ""):
        final = result.final_context
        top_score = final[0].rerank_score if final else 0.0
        latency = sum(timings.values()) * 1000.0
        sources = [c.chunk.document for c in final] or result.sources[:4]

        logger.info(
            "[RAG] query=%r type=%s needs_rag=%s | candidates=%d reranked=%d final=%d "
            "top_score=%.3f threshold=%.2f passed=%s latency_ms=%.0f "
            "sources=%s",
            query.original[:100], query.query_type, query.needs_rag,
            len(result.chunks), len(result.chunks), len(final),
            top_score, self.config.similarity_threshold, result.reason,
            latency, sources[:4],
        )