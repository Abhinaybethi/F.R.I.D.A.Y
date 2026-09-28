"""
Hybrid retriever — merges vector (cosine) + lexical (BM25) candidates.

Pipeline:
  1. Semantic retrieval -> top `retrieval_k` by cosine.
  2. Lexical retrieval  -> top `retrieval_k` by BM25 over multiple query
     variants (semantic query + original).
  3. Merge unions, dedupe by chunk id, keep `retrieval_k` candidates with
     both scores populated for the reranker.
"""
import logging
from collections import defaultdict
from typing import List, Dict

from friday.rag.models import RAGConfig, RAGQuery, RetrievedChunk, RAGChunk
from friday.rag.index import VectorIndex
from friday.rag.lexical import BM25, tokenize
from friday.rag.embedder import Embedder

logger = logging.getLogger("friday.rag.retriever")


class Retriever:
    def __init__(self, index: VectorIndex, config: RAGConfig):
        self.index = index
        self.config = config

    def retrieve(self, query: RAGQuery) -> List[RetrievedChunk]:
        if self.index.count() == 0:
            return []

        # --- 1. Semantic ---
        variants = _query_variants(query)
        semantic_hits: Dict[str, dict] = {}
        for variant in variants:
            ids, scores = self.index.semantic_query(variant, self.config.retrieval_k)
            for cid in ids:
                entry = scores[cid]
                if cid not in semantic_hits or entry["vector_score"] > semantic_hits[cid]["vector_score"]:
                    semantic_hits[cid] = entry
        semantic_ids = list(semantic_hits.keys())

        # --- 2. Lexical (BM25) ---
        all_text = self.index.get_chunks(semantic_ids)
        doc_ids = [semantic_ids.index(cid) for cid in semantic_ids]
        docs = [all_text[cid]["text"] for cid in semantic_ids]
        lexical_scores: Dict[str, float] = {}
        if docs and self.config.hybrid:
            bm25 = BM25(docs, k1=self.config.bm25_k1, b=self.config.bm25_b)
            for v in variants:
                scored = bm25.score_docs(v, doc_ids=doc_ids)
                for i, s in scored.items():
                    chunk_id = semantic_ids[i]
                    lexical_scores[chunk_id] = max(lexical_scores.get(chunk_id, 0.0), s)

        # --- 3. Merge candidates ---
        merged: Dict[str, RetrievedChunk] = {}
        for cid in semantic_ids:
            meta = all_text[cid]["metadata"]
            chunk = _chunk_from_meta(cid, all_text[cid]["text"], meta)
            merged[cid] = RetrievedChunk(
                chunk=chunk,
                vector_score=semantic_hits[cid]["vector_score"],
                lexical_score=lexical_scores.get(cid, 0.0),
            )
        # keep retrieval_k candidates after union
        merged = dict(sorted(merged.items(), key=lambda kv: kv[1].vector_score, reverse=True))
        return list(merged.values())[: self.config.retrieval_k]


def _query_variants(query: RAGQuery) -> List[str]:
    variants = [query.semantic_query or query.original]
    if query.original and query.original.lower() != (query.semantic_query or "").lower():
        variants.append(query.original)
    kw = " ".join(query.keywords[:8])
    if kw:
        variants.append(kw)
    return variants


def _chunk_from_meta(cid: str, text: str, meta: dict) -> RAGChunk:
    return RAGChunk(
        id=cid,
        text=text,
        source=meta.get("source", ""),
        document=meta.get("document", ""),
        section=meta.get("section", ""),
        topic=meta.get("topic", ""),
        project=meta.get("project", ""),
        content_type=meta.get("content_type", "markdown"),
        timestamp=meta.get("timestamp", ""),
    )