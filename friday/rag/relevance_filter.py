"""
Relevance gate — the anti-hallucination filter.

A reranked candidate only enters the final context when it clears both:
  - the vector similarity floor (semantic relevance)
  - the combined rerank floor (fused evidence)
When nothing clears the gate, the service returns the controlled
no-context message instead of forcing weak context into the LLM.

Final selection is *evidence-bounded, budget-aware*: every gate-passing
candidate is admitted in rerank order (best evidence first) up to
`2 × final_k`.  `final_k` therefore expresses the primary context size; the
hard size limit is the `max_context_tokens` budget enforced downstream by
the compressor.  This prevents a relevant, gate-passing chunk from being
discarded purely because a relative slot ordering placed it just below
`final_k` — the dominant cause of hit@final < hit@10.
"""
from typing import List, Tuple

from friday.rag.models import RAGConfig, RAGQuery, RetrievedChunk


class RelevanceFilter:
    def __init__(self, config: RAGConfig):
        self.config = config

    def filter(
        self, reranked: List[RetrievedChunk], query: RAGQuery
    ) -> Tuple[List[RetrievedChunk], bool, str]:
        """
        Returns (kept, passed_gate, reason).
        `passed_gate` is True when at least one chunk is sufficiently relevant.
        """
        if not reranked:
            return [], False, "no_candidates"

        threshold = self.config.similarity_threshold
        min_score = self.config.relevance_min_score

        passed = [
            c for c in reranked
            if c.vector_score >= threshold and c.rerank_score >= min_score
        ]
        if not passed:
            # Diagnostic: nearest candidate below threshold
            top = reranked[0]
            return (
                [],
                False,
                f"gate_rejected best=(vec={top.vector_score:.2f}<{threshold}, rerank={top.rerank_score:.2f}<{min_score})",
            )

        # Cap at 2 × final_k: evidence up to twice the primary slots, ordered
        # by rerank (best evidence first); `max_context_tokens` is the hard
        # size limit enforced downstream by the compressor.
        kept = passed[: self.config.final_k * 2]

        return kept, True, "gate_passed"