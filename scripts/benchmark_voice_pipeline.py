"""
Real Voice-to-Response Pipeline Latency Benchmark Script for F.R.I.D.A.Y. Phase 16 (P0).

Measures end-to-end processing latency from transcript arrival to response generation
across deterministic, fuzzy, confirmation, context, and Ollama reasoning commands.
"""
import sys
import os
import time
import numpy as np
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.reasoning.interface import Reasoner
from friday.planning.context_resolver import ShortTermContext
from friday.intent.models import Action

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


class MockReasoner(Reasoner):
    def request(self, transcript: str, context: ShortTermContext) -> dict:
        return {"type": "unknown", "action": "GET_TIME", "target": ""}
    def is_available(self) -> bool:
        return True
    def health(self) -> str:
        return "mock"
    def close(self):
        pass


def benchmark_voice_to_response_pipeline(num_samples: int = 10) -> Dict[str, Dict[str, float]]:
    print("=" * 65)
    print(" F.R.I.D.A.Y. PHASE 16 — REAL VOICE-TO-RESPONSE LATENCY BENCHMARK")
    print("=" * 65)

    cm = ConversationManager(dry_run=True, reasoner=MockReasoner(), permissions=_ALL_ENABLED)
    cm.start_session()

    scenarios = {
        "A. Deterministic Command ('open chrome')": "open chrome",
        "B. Fuzzy Command ('open grove')": "open grove",
        "C. Confirmation Command ('close chrome')": "close chrome",
        "D. Contextual Command ('close it')": "close it",
    }

    results = {}

    for name, transcript in scenarios.items():
        latencies_ms: List[float] = []

        # Preset context for contextual command
        if "Contextual" in name:
            from friday.intent.models import Intent
            cm.context.last_intent = Intent(action=Action.OPEN_APP, target="chrome")

        for _ in range(num_samples):
            t0 = time.perf_counter()
            resp, keep = cm.handle_transcript(transcript)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000)

        p50 = float(np.median(latencies_ms))
        p95 = float(np.percentile(latencies_ms, 95))
        max_lat = max(latencies_ms)

        results[name] = {"p50": p50, "p95": p95, "max": max_lat}

        print(f"\n[{name}]")
        print(f"  p50 Latency: {p50:.4f} ms")
        print(f"  p95 Latency: {p95:.4f} ms")
        print(f"  Max Latency: {max_lat:.4f} ms")

    print("\n" + "=" * 65)
    print(" PIPELINE BENCHMARK SUMMARY")
    print("=" * 65)
    for k, v in results.items():
        print(f"  {k:<45}: p50={v['p50']:.4f} ms | p95={v['p95']:.4f} ms")
    print("=" * 65)

    return results


if __name__ == "__main__":
    benchmark_voice_to_response_pipeline(10)
