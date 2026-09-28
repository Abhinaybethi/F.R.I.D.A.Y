"""
Lightweight BM25 lexical scorer for hybrid retrieval.

Pure-python tokenisation + numpy aggregates — no scipy/sklearn dependency
(those are broken under the project's numpy 2.x pin).  Efficient for the
local corpus sizes Friday indexes (10^2–10^4 chunks).
"""
import re
import math
from typing import List, Union

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25:
    """BM25+ variant with a small floor (delta=0.5) to keep scores stable."""

    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75, delta: float = 0.5):
        self.k1 = k1
        self.b = b
        self.delta = delta
        self.doc_toks = [tokenize(d) for d in docs]
        self.docs = docs
        n_docs = len(self.doc_toks)
        self.doc_lens = [len(t) for t in self.doc_toks]
        self.avgdl = (sum(self.doc_lens) / n_docs) if n_docs else 0.0
        # df per term + idf
        self.df = {}
        for toks in self.doc_toks:
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.idf = {}
        for t, df in self.df.items():
            self.idf[t] = math.log1p((n_docs - df + 0.5) / (df + 0.5))
        # cached per-term occurrence counts
        self._term_counts = [self._count_term_doc(i) for i in range(n_docs)]

    def _count_term_doc(self, i: int) -> dict:
        counts = {}
        for t in self.doc_toks[i]:
            counts[t] = counts.get(t, 0) + 1
        return counts

    def score_docs(self, query: str, doc_ids: List[str] = None) -> dict:
        """Return {doc_index: bm25_score} for all (or selected) docs."""
        q_toks = tokenize(query)
        if not q_toks:
            return {}
        out = {}
        indices = range(len(self.doc_toks)) if doc_ids is None else doc_ids
        for i in indices:
            if i >= len(self.doc_toks):
                continue
            score = 0.0
            tf_map = self._term_counts[i]
            flen = self.doc_lens[i]
            for t in q_toks:
                f = tf_map.get(t, 0)
                if f == 0 or t not in self.idf:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * (flen / self.avgdl)) if self.avgdl else 1.0
                score += (self.idf[t] * (f + self.delta) / (denom if denom else 1e-9))
            out[i] = score
        return out

    def batched_scores(self, queries: List[str], doc_ids: List[int] = None) -> dict:
        """Aggregate BM25 across multiple query variants (sum of variants)."""
        total = {}
        for q in queries:
            for i, s in self.score_docs(q, doc_ids).items():
                total[i] = total.get(i, 0.0) + s
        return total