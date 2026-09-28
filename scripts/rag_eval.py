"""
RAG evaluation runner.

Usage:
    python scripts/rag_eval.py                # offline retrieval eval, reuse index
    python scripts/rag_eval.py --rebuild      # force re-ingest the full corpus first
    python scripts/rag_eval.py --qualitative  # also probe Bonsai w/ and w/o RAG

Prints the before/after table:
  - before: no RAG (ungrounded reasoner) — measurable offline as gate=0,
    relevant context = none.
  - after:  hybrid retriever + rerank + relevance gate.
  - qualitative rows only appear when the local model is actually reachable.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from friday.rag.models import RAGConfig
from friday.rag.service import RAGService
from friday.rag.evaluator import run_offline_assessment, render_summary

EVAL_PERSIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".data", "rag", "eval")


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
    service = RAGService(cfg)
    service.ensure_index()
    return service


def qualitative(args, service: RAGService):
    """Bonsai w/ and w/o RAG on a sample — only runs when the model is up."""
    from friday.planning.context_resolver import ShortTermContext
    from friday.reasoning.llamacpp_reasoner import LlamaCppReasoner

    reasoner = LlamaCppReasoner()
    if not reasoner.is_available():
        print("\n[QUAL] Bonsai/llama.cpp NOT reachable — qualitative comparison skipped.")
        return

    questions = [
        "How does speech-to-text work in the project?",
        "What guardrails gate real tool execution?",
    ]
    stx = ShortTermContext()
    print("\n=== QUALITATIVE: Bonsai with & without RAG ===")
    for q in questions:
        before = reasoner.request(q, stx, mode="chat", retrieval_context="")
        result = service.build_result(q)
        block = service.build_prompt_block(result)
        after = reasoner.request(q, stx, mode="chat", retrieval_context=block)
        print(f"\nQ: {q}")
        print(f"  WITHOUT RAG: {str(before.get('text', before))[:400]}")
        print(f"  WITH RAG   : {str(after.get('text', after))[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="re-ingest corpus")
    ap.add_argument("--qualitative", action="store_true", help="try Bonsai comparison")
    args = ap.parse_args()

    print("Building index (reuse=%s) ..." % (not args.rebuild), flush=True)
    t0 = time.perf_counter()
    service = build_service(args.rebuild)
    print(f"index ready in {time.perf_counter() - t0:.1f}s, chunks={service.count()}", flush=True)

    t0 = time.perf_counter()
    summary = run_offline_assessment(service)
    print(f"eval ran in {time.perf_counter() - t0:.1f}s\n")
    print(render_summary(summary))

    p = summary["positive"]
    n = summary["negative"]
    print("\n=== THRESHOLD RECOMMENDATION ===")
    print(f"  relevant best_vec median={p['best_vec_median']} min={p['best_vec_min']} "
          f"| negative median={n['best_vec_median']}")
    print("  (tune similarity_threshold: positive passthrough vs negative rejection)")

    if args.qualitative:
        qualitative(args, service)


if __name__ == "__main__":
    main()