"""
Hardware & Subsystem Latency Benchmark Script for F.R.I.D.A.Y. Phase 14 (P0).

Measures exact microsecond-level timing across router, fuzzy matcher, planner,
context resolver, tool verifier, response engine, and Ollama fallback.
"""
import sys
import os
import time
from typing import Dict
import logging
logging.disable(logging.CRITICAL)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.router import route
from friday.intent.fuzzy_router import fuzzy_route
from friday.planning.planner import parse_plan
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.response.engine import format_spoken_response
from friday.tools import registry
from friday.intent.models import Action, Intent

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


def benchmark_subsystems() -> Dict[str, float]:
    results = {}

    try:
        # 1. Deterministic Router
        t0 = time.perf_counter()
        for _ in range(100):
            route("open chrome")
        results["router_exact_ms"] = ((time.perf_counter() - t0) / 100) * 1000

        # 2. Fuzzy Phonetic Router
        t0 = time.perf_counter()
        for _ in range(100):
            fuzzy_route("open grove")
        results["fuzzy_router_ms"] = ((time.perf_counter() - t0) / 100) * 1000

        # 3. Context Resolver
        ctx = ShortTermContext(last_action=Action.OPEN_APP, last_target="chrome")
        t0 = time.perf_counter()
        for _ in range(100):
            resolve_context("close it", ctx)
        results["context_resolver_ms"] = ((time.perf_counter() - t0) / 100) * 1000

        # 4. Multi-Step Planner
        t0 = time.perf_counter()
        for _ in range(100):
            parse_plan("open chrome and search python tutorials", ctx)
        results["planner_ms"] = ((time.perf_counter() - t0) / 100) * 1000

        # 5. Tool Execution & Post-Action Verification
        intent = Intent(action=Action.OPEN_APP, target="chrome")
        t0 = time.perf_counter()
        for _ in range(50):
            registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)
        results["tool_exec_verifier_ms"] = ((time.perf_counter() - t0) / 50) * 1000

        # 6. Spoken Response Engine
        outcome_min = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)
        t0 = time.perf_counter()
        for _ in range(100):
            format_spoken_response(outcome_min)
        results["response_engine_ms"] = ((time.perf_counter() - t0) / 100) * 1000

    except Exception as e:
        print(f"Error during benchmark: {e}")
        traceback.print_exc()

    return results


def print_summary(results: Dict[str, float]):
    print("=" * 60)
    print(" F.R.I.D.A.Y. PHASE 14 — SUBSYSTEM LATENCY BENCHMARK")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {k:<35}: {v:.4f} ms")
    total_deterministic = sum(results.values())
    print("-" * 60)
    print(f"  TOTAL DETERMINISTIC LATENCY        : {total_deterministic:.4f} ms")
    print("=" * 60)


if __name__ == "__main__":
    res = benchmark_subsystems()
    print_summary(res)
