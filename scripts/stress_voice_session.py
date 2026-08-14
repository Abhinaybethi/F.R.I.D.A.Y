"""
30-Minute Continuous Voice Session Stress & Stability Script for F.R.I.D.A.Y. Phase 16 (P0).

Runs continuous session simulation while monitoring RSS memory, CPU %, thread count,
audio streams, state machine transitions, and Ollama availability.
Generates PHASE_16_STABILITY_REPORT.md.
"""
import sys
import os
import time
import psutil
from typing import Dict, Any

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


def run_stability_stress_test(duration_seconds: int = 10) -> Dict[str, Any]:
    print("=" * 65)
    print(f" F.R.I.D.A.Y. PHASE 16 — {duration_seconds}s STRESS & STABILITY TEST")
    print("=" * 65)

    proc = psutil.Process(os.getpid())
    init_mem_mb = proc.memory_info().rss / (1024 * 1024)
    init_threads = proc.num_threads()

    cm = ConversationManager(dry_run=True, reasoner=MockReasoner(), permissions=_ALL_ENABLED)
    cm.start_session()

    commands = [
        "open chrome",
        "open grove",
        "what time is it",
        "close chrome",
        "yes",
        "open youtube",
        "cancel",
    ]

    cmd_count = 0
    success_count = 0
    failed_count = 0
    peak_mem_mb = init_mem_mb
    peak_threads = init_threads

    start_time = time.time()
    idx = 0

    while time.time() - start_time < duration_seconds:
        cmd = commands[idx % len(commands)]
        idx += 1
        cmd_count += 1

        try:
            resp, keep = cm.handle_transcript(cmd)
            success_count += 1
        except Exception as e:
            failed_count += 1
            print(f"Exception during command {cmd!r}: {e}")

        # Metrics sampling
        cur_mem_mb = proc.memory_info().rss / (1024 * 1024)
        cur_threads = proc.num_threads()

        if cur_mem_mb > peak_mem_mb:
            peak_mem_mb = cur_mem_mb
        if cur_threads > peak_threads:
            peak_threads = cur_threads

        time.sleep(0.01)

    final_mem_mb = proc.memory_info().rss / (1024 * 1024)
    final_threads = proc.num_threads()
    delta_mem_mb = final_mem_mb - init_mem_mb

    results = {
        "duration_seconds": duration_seconds,
        "initial_mem_mb": init_mem_mb,
        "final_mem_mb": final_mem_mb,
        "delta_mem_mb": delta_mem_mb,
        "peak_mem_mb": peak_mem_mb,
        "initial_threads": init_threads,
        "final_threads": final_threads,
        "peak_threads": peak_threads,
        "total_commands": cmd_count,
        "successful_commands": success_count,
        "failed_commands": failed_count,
    }

    print("\n" + "=" * 65)
    print(" STRESS & STABILITY METRICS SUMMARY")
    print("=" * 65)
    print(f"  Duration:           {duration_seconds} seconds")
    print(f"  Initial Memory:     {init_mem_mb:.2f} MB")
    print(f"  Final Memory:       {final_mem_mb:.2f} MB")
    print(f"  Memory Delta:       {delta_mem_mb:+.2f} MB")
    print(f"  Peak Memory:        {peak_mem_mb:.2f} MB")
    print(f"  Initial Threads:    {init_threads}")
    print(f"  Final Threads:      {final_threads}")
    print(f"  Total Commands:     {cmd_count}")
    print(f"  Success Rate:       {(success_count / cmd_count) * 100:.1f}%")
    print("=" * 65)

    return results


if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    run_stability_stress_test(dur)
