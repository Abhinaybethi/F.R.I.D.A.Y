"""
RAG failure-mode diagnostic.

For every eval item whose expected document is lost between retrieval and
final context, produces a stage-by-stage trace:

    retrieved -> reranked -> threshold -> final-k -> deduped -> token-budget -> context

and classifies the loss into one of:
    reranker_mistake
    duplicate_suppression
    threshold_filtering
    final_k_truncation
    context_compression
    retrieval_miss
    evaluation_issue

Usage:
    python scripts/rag_diag.py [--rebuild]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from friday.rag.models import RAGConfig
from friday.rag.service import RAGService
from friday.rag.query_analyzer import analyze_query
from friday.rag.evaluator import run_offline_assessment, render_summary
from friday.rag.eval_set import build_eval_set, expected_docs

EVAL_PERSIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".data", "rag", "eval")
CHAR_PER_TOKEN = 4.2


def build_service(rebuild: bool) -> RAGService:
    if rebuild and os.path.isdir(EVAL_PERSIST):
        import shutil
        shutil.rmtree(EVAL_PERSIST, ignore_errors=True)
    cfg = RAGConfig(
        enabled=True, collection="friday_knowledge", persist_dir=EVAL_PERSIST,
        retrieval_k=15, final_k=5, similarity_threshold=0.30,
        relevance_min_score=0.30, rerank=True, hybrid=True,
        bm25_k1=1.5, bm25_b=0.75, context_compression=True,
        max_context_tokens=3000, auto_ingest=True, source_dirs=["docs"],
        include_md=True,
    )
    svc = RAGService(cfg)
    svc.ensure_index()
    return svc


def trace_query(service, item):
    """Stage-by-stage trace for a single eval item."""
    q = item["question"]
    history = item.get("history", [])
    expected = expected_docs(item)

    query = analyze_query(q, history or [])
    candidates = service.retriever.retrieve(query)
    reranked = service.reranker.rerank(candidates, query) if service.config.rerank else candidates
    gated, passed, reason = service.filter.filter(reranked, query)
    kept_text = service.compressor.compress(gated)

    # which doc ids survive each stage (doc-level, mirrors evaluator)
    def doc_rank(chunks):
        seen, out = set(), []
        for c in chunks:
            d = c.chunk.document
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out

    cand_docs = doc_rank(candidates)          # retrieval order (vector-sorted)
    rerank_docs = doc_rank(reranked)          # rerank order
    gated_docs = doc_rank(gated)
    # doc-level presence in the final *text* block (after dedupe + budget)
    blocks = kept_text.split("\n\n") if kept_text else []
    text_docs = {c.chunk.document for c in gated
                 if any(c.chunk.text in b for b in blocks)}

    rows = []
    for doc in expected:
        doc_chunks = [c for c in reranked if c.chunk.document == doc]  # rerank order
        if not doc_chunks:
            # recheck raw candidates (may be present beyond rerank? rerank includes all)
            doc_chunks = [c for c in candidates if c.chunk.document == doc]
        row = {
            "expected_doc": doc,
            "n_chunks": len(doc_chunks),
            "retrieve_rank": None, "vector_score": None, "lexical_score": None,
            "rerank_rank": None, "rerank_score": None,
            "retrieved": bool(doc in cand_docs),
            "hit10": bool(doc in rerank_docs and rerank_docs.index(doc) < 10),
            "passed_threshold": None,
            "in_gated": bool(doc in gated_docs),
            "in_final_text": bool(doc in text_docs),
            "final_k_slot": None,
        }
        if doc_chunks:
            best_c = max(doc_chunks, key=lambda c: c.rerank_score)  # best-scoring chunk of the doc
            row["vector_score"] = round(best_c.vector_score, 4)
            row["lexical_score"] = round(best_c.lexical_score, 4)
            row["rerank_score"] = round(best_c.rerank_score, 4)
            if doc in cand_docs:
                row["retrieve_rank"] = cand_docs.index(doc) + 1
            row["rerank_rank"] = rerank_docs.index(doc) + 1 if doc in rerank_docs else None
            thr_v = best_c.vector_score >= service.config.similarity_threshold
            thr_r = best_c.rerank_score >= service.config.relevance_min_score
            row["passed_threshold"] = bool(thr_v and thr_r)
            row["final_k_slot"] = rerank_docs.index(doc) + 1 if doc in rerank_docs and rerank_docs.index(doc) < service.config.final_k else None
        rows.append(row)

    return {
        "question": q, "expected": expected, "passed_gate": passed, "reason": reason,
        "n_candidates": len(candidates), "n_reranked": len(reranked),
        "n_gated": len(gated), "final_text_tokens": int(len(kept_text) / CHAR_PER_TOKEN),
        "final_text_chars": len(kept_text),
        "rows": sorted(rows, key=lambda r: r["rerank_rank"] if r["rerank_rank"] else 9999),
    }


def classify(tr):
    """Dominant loss stage: compare against stages of the expected docs."""
    lost = [r for r in tr["rows"] if not r["in_gated"]]
    if not lost:
        # present in final_context list; check compression (final text) instead
        text_lost = [r for r in tr["rows"] if r["in_gated"] and not r["in_final_text"]]
        if text_lost:
            return "context_compression"
        return None  # all expected docs reached the final context (should not be here)
    for r in lost:
        if not r["retrieved"]:
            return "retrieval_miss"
        if r["rerank_rank"] is None:
            return "reranker_mistake"
        if r["passed_threshold"] is False:
            return "threshold_filtering"
        if r["in_gated"] is False and r["passed_threshold"]:
            return "final_k_truncation"
    return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    service = build_service(args.rebuild)
    print(f"index chunks={service.count()}\n")

    items = build_eval_set()
    failures, dist = [], {}
    for item in items:
        if item.get("type") == "negative":
            continue
        tr = trace_query(service, item)
        hit_final = any(r["in_gated"] for r in tr["rows"])
        if not hit_final:
            cat = classify(tr)
            dist[cat] = dist.get(cat, 0) + 1
            failures.append((tr, cat))

    print("=== LOST-AT-FINAL CASES (%d) ===" % len(failures))
    for tr, cat in failures:
        print(f"\nQUERY: {tr['question']!r}")
        print(f"  expected={tr['expected']} gate={tr['reason']} "
              f"cand={tr['n_candidates']} reranked={tr['n_reranked']} gated={tr['n_gated']} "
              f"final_text_tokens~{tr['final_text_tokens']} => {cat}")
        for r in tr["rows"]:
            print(f"    doc='{r['expected_doc'][:45]}' chunks={r['n_chunks']} "
                  f"retr#{r['retrieve_rank']} vec={r['vector_score']} lex={r['lexical_score']} "
                  f"rerank#{r['rerank_rank']} rrk={r['rerank_score']} "
                  f"thr={r['passed_threshold']} gated={r['in_gated']} text={r['in_final_text']}")

    print("\n=== FAILURE DISTRIBUTION ===")
    for cat, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:26s} {n}  ({100.0 * n / max(1, len(failures)):.0f}%)")

    print("\n=== BASELINE METRICS (reproduce eval) ===")
    summary = run_offline_assessment(service)
    print(render_summary(summary))


if __name__ == "__main__":
    main()