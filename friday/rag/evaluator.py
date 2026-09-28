"""
Offline RAG evaluation fixtures + metrics.

Measures the retrieval half of the pipeline without an LLM:
  - hit@k / hit@final: did a relevant source surface among candidates / final?
  - MRR: reciprocal rank of first relevant hit
  - gate precision: negative queries produce no-context (gate rejects)
  - gate recall: relevant queries actually pass the gate
  - score distributions: vector & rerank stats to calibrate thresholds
Used by scripts/rag_eval.py to produce the before/after table.
"""
from collections import defaultdict
from typing import List, Dict, Tuple

from friday.rag.service import RAGService
from friday.rag.eval_set import build_eval_set, expected_docs, is_negative


def run_offline_assessment(service: RAGService, items: List[Dict] = None) -> Dict:
    items = items if items is not None else build_eval_set()

    by_type = defaultdict(lambda: {"total": 0, "hit": 0, "hit_final": 0, "mrr": 0.0,
                                   "passed": 0, "rejected_neg": 0})
    rows = []
    score_stats = defaultdict(list)

    for item in items:
        expected = expected_docs(item)
        result = service.build_result(item["question"], history=item.get("history", []))

        # Candidates ranked list of document names (deduped, in rank order)
        doc_rank = []
        seen = set()
        for c in result.chunks:
            doc = c.chunk.document
            if doc not in seen:
                seen.add(doc)
                doc_rank.append(doc)
        final_docs = [c.chunk.document for c in result.final_context]

        hit_at_k = any(d in doc_rank[:10] for d in expected) if expected else None
        hit_final = any(d in final_docs for d in expected) if expected else None
        mrr = 0.0
        if expected:
            for rank, doc in enumerate(doc_rank, start=1):
                if doc in expected and rank <= 10:
                    mrr = 1.0 / rank
                    break

        neg = is_negative(item)
        passed = result.used and not result.no_context
        safe_reject = (not passed) if neg else None  # True when gate kept a negative out
        gate_hit = passed if not neg else None       # positive queries must pass

        row = {
            "type": item["type"], "question": item["question"],
            "expected": expected, "neg": neg,
            "hit_at_k": hit_at_k, "hit_at_final": hit_final, "mrr": mrr,
            "passed_gate": passed, "safe_reject": safe_reject,
            "candidates": len(result.chunks), "final": len(result.final_context),
            "reason": result.reason,
            "best_vec": (result.final_context[0].vector_score if result.final_context
                         else (result.chunks[0].vector_score if result.chunks else 0.0)),
            "best_rerank": (result.final_context[0].rerank_score if result.final_context
                            else (result.chunks[0].rerank_score if result.chunks else 0.0)),
        }
        rows.append(row)

        bucket = "negative" if neg else "positive"
        t = by_type[bucket]
        t["total"] += 1
        if hit_at_k is True:
            t["hit"] += 1
        if hit_final is True:
            t["hit_final"] += 1
        t["mrr"] += mrr
        if gate_hit is True:
            t["passed"] += 1
        if safe_reject is True:
            t["rejected_neg"] += 1

        score_stats[bucket].append((row["best_vec"], row["best_rerank"]))

    return _summarise(by_type, score_stats, rows)


def _summarise(by_type: Dict, score_stats: Dict, rows: List[Dict]) -> Dict:
    summary = {}
    for bucket in ("positive", "negative"):
        t = by_type[bucket]
        n = t["total"]
        summary[bucket] = {
            "total": n,
            "hit@10": round(t["hit"] / n, 3) if n else 0.0,
            "hit@final": round(t["hit_final"] / n, 3) if n else 0.0,
            "mrr": round(t["mrr"] / n, 3) if n else 0.0,
            "gate_pass_rate": round(t["passed"] / t["total"], 3) if t["total"] else 0.0,
            "gate_reject_rate": round(t["rejected_neg"] / t["total"], 3) if t["total"] else 0.0,
        }
        vecs = [s[0] for s in score_stats.get(bucket, [])]
        reranks = [s[1] for s in score_stats.get(bucket, [])]
        summary[bucket]["best_vec_min"] = round(min(vecs), 3) if vecs else 0.0
        summary[bucket]["best_vec_median"] = round(sorted(vecs)[len(vecs) // 2], 3) if vecs else 0.0
        summary[bucket]["best_vec_max"] = round(max(vecs), 3) if vecs else 0.0
        summary[bucket]["best_rerank_median"] = round(sorted(reranks)[len(reranks) // 2], 3) if reranks else 0.0

    summary["rows"] = rows
    summary["total_queries"] = len(rows)
    return summary


def render_summary(summary: Dict) -> str:
    lines = []
    p = summary["positive"]
    n = summary["negative"]
    lines.append("=== OFFLINE RAG EVAL (positive = expected-source retrievable) ===")
    lines.append(f"positive: total={p['total']} hit@10={p['hit@10']:.3f} "
                 f"hit@final={p['hit@final']:.3f} mrr={p['mrr']:.3f} "
                 f"gate_pass={p['gate_pass_rate']:.3f} "
                 f"vec[min={p['best_vec_min']} med={p['best_vec_median']} max={p['best_vec_max']}] "
                 f"rerank med={p['best_rerank_median']}")
    lines.append(f"negative: total={n['total']} gate_reject={n['gate_reject_rate']:.3f} "
                 f"vec median={n['best_vec_median']}")
    for row in summary["rows"]:
        flag = "NEG" if row["neg"] else "POS"
        hit = "HIT" if row["hit_at_k"] else "miss"
        final = "FIN" if row["hit_at_final"] else ""
        lines.append(
            f"  [{flag}][{hit}{final}] best_vec={row['best_vec']:.2f} best_rank={row['best_rerank']:.2f} "
            f"final={row['final']} reason={row['reason']} "
            f"{row['question'][:70]}"
        )
    return "\n".join(lines)