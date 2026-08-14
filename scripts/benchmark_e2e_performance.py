"""
End-to-End Performance & Latency Benchmarking Script.

Measures wall-clock latency (ms) across all pipeline boundaries:
    python scripts/benchmark_e2e_performance.py
"""
import sys
import os
import time
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.intent.router import route
from friday.planning.planner import parse_plan
from friday.planning.context_resolver import ShortTermContext
from friday.verification.models import ActionOutcome

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def benchmark_pipeline():
    print("=" * 60)
    print(" F.R.I.D.A.Y. Phase 11 Performance & Latency Benchmark")
    print("=" * 60)

    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    benchmarks = []

    # 1. Deterministic Router Latency
    t0 = time.perf_counter()
    intent = route("open chrome")
    t_route_ms = (time.perf_counter() - t0) * 1000
    benchmarks.append(("Deterministic Router", f"{t_route_ms:.2f} ms"))

    # 2. Multi-step Planner Latency
    t0 = time.perf_counter()
    plan, err = parse_plan("open chrome and open youtube", ShortTermContext())
    t_plan_ms = (time.perf_counter() - t0) * 1000
    benchmarks.append(("Multi-Step Planner", f"{t_plan_ms:.2f} ms"))

    # 3. ConversationManager Single Command (Warm)
    t0 = time.perf_counter()
    resp1, _ = cm.handle_transcript("open chrome")
    t_cm_single_ms = (time.perf_counter() - t0) * 1000
    benchmarks.append(("Warm Single Utterance (Router + Verification)", f"{t_cm_single_ms:.2f} ms"))

    # 4. ConversationManager Multi-step Command (Warm)
    t0 = time.perf_counter()
    resp2, _ = cm.handle_transcript("open chrome and open youtube")
    t_cm_multi_ms = (time.perf_counter() - t0) * 1000
    benchmarks.append(("Warm Multi-step Plan (Planner + Exec + Verifier)", f"{t_cm_multi_ms:.2f} ms"))

    # 5. Local Ollama Reasoning Fallback Latency (if available)
    if cm.reasoner and cm.reasoner.is_available():
        t0 = time.perf_counter()
        reasoned = cm.reasoner.request("find python tutorials on the web", ShortTermContext())
        t_reason_ms = (time.perf_counter() - t0) * 1000
        benchmarks.append(("Ollama Local Reasoner (llama3:latest)", f"{t_reason_ms:.2f} ms"))

    print("\nBenchmark Results:")
    print("-" * 60)
    for name, val in benchmarks:
        print(f"  {name:<45} {val}")
    print("-" * 60)
    print("\nLatency Benchmark Complete.")


if __name__ == "__main__":
    benchmark_pipeline()
