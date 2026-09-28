"""
Context compression — maximum signal, minimum tokens.

Reduces the gated candidate set into a compact, deduplicated context block:
  - near-identical chunks are collapsed (n-gram overlap)
  - repeated metadata is stripped
  - chunks are grouped under a single per-source header
  - a token budget guards the final length for the local LLM
"""
import re
from typing import List

from friday.rag.models import RAGConfig, RetrievedChunk

_WS = re.compile(r"\s+")

# rough tokens-per-char for technical English
_CHAR_PER_TOKEN = 4.2


def _ngrams(text: str, n: int = 8) -> set:
    words = _WS.sub(" ", text.lower()).split()
    if len(words) < n:
        return {_WS.sub(" ", text.lower())}
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _dedupe(chunks: List[RetrievedChunk], threshold: float = 0.55) -> List[RetrievedChunk]:
    keep: List[RetrievedChunk] = []
    for c in chunks:
        grams = _ngrams(c.chunk.text)
        dup = False
        for seen in keep:
            overlap = len(grams & _ngrams(seen.chunk.text)) / max(1, min(len(grams), len(_ngrams(seen.chunk.text))))
            if overlap >= threshold:
                dup = True
                break
        if not dup:
            keep.append(c)
    return keep


class ContextCompressor:
    def __init__(self, config: RAGConfig):
        self.config = config

    def compress(self, gated: List[RetrievedChunk]) -> str:
        if not gated:
            return ""

        budget = self.config.max_context_tokens
        budget_chars = int(budget * _CHAR_PER_TOKEN) if self.config.context_compression else 10_000_000

        gated = _dedupe(gated)
        rows: List[str] = []
        used = 0

        for c in gated:
            label = _label(c)
            header = f"[Source: {label}]"
            header_len = len(header) + len(c.chunk.text) + 3
            if used + header_len > budget_chars and rows:
                break
            rows.append(f"{header}\n{c.chunk.text}")
            used += header_len

        return "\n\n".join(rows)


def _label(c: RetrievedChunk) -> str:
    parts = []
    if c.chunk.document:
        parts.append(c.chunk.document)
    if c.chunk.section and c.chunk.section.lower() not in (c.chunk.document.lower(),):
        parts.append(c.chunk.section)
    if not parts:
        parts.append(c.chunk.source or "Unknown")
    return " - ".join(parts)