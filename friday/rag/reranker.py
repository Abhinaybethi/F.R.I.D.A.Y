"""
Lightweight re-ranker for retrieved candidates.

Vector similarity alone is not authority.  This unsupervised reranker fuses:
  - normalised cosine score
  - normalised BM25 score (lexical evidence)
  - keyword/entity coverage (does the chunk actually contain the query terms?)
  - a small section-title bonus (chunks whose heading matches query context)
Because it runs entirely locally and cheaply, it is the correct default for
Friday's local-only stack (no cross-encoder infra).
"""
import re
from typing import List

from friday.rag.models import RAGConfig, RAGQuery, RetrievedChunk
from friday.rag.lexical import tokenize

_HEADING_SPLIT = re.compile(r"[#\s\-_/]+")


class Reranker:
    def __init__(self, config: RAGConfig):
        self.config = config

    def rerank(self, candidates: List[RetrievedChunk], query: RAGQuery) -> List[RetrievedChunk]:
        if not candidates:
            return []

        vec_max = max((c.vector_score for c in candidates), default=1.0) or 1.0
        lex_max = max((c.lexical_score for c in candidates), default=1.0) or 1.0

        query_terms = set(tokenize(query.semantic_query or query.original))
        query_terms |= set(q.lower() for q in query.keywords)

        for c in candidates:
            v = c.vector_score / vec_max
            l = c.lexical_score / lex_max if lex_max > 0 else 0.0
            chunk_terms = set(tokenize(c.chunk.text))
            coverage = len(query_terms & chunk_terms) / len(query_terms) if query_terms else 0.0
            heading = _HEADING_SPLIT.sub(" ", (c.chunk.section or "")).lower()
            heading_bonus = 0.15 if any(t in heading for t in query_terms) else 0.0
            entity_bonus = 0.05 * (1.0 if c.chunk.topic and any(e in c.chunk.topic for e in query.entities) else 0.0)
            score = 0.50 * v + 0.30 * l + 0.20 * coverage + heading_bonus + entity_bonus
            c.rerank_score = round(score, 4)

        return sorted(candidates, key=lambda c: c.rerank_score, reverse=True)