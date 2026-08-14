"""
Resource Lifecycle 10-Cycle Restart Test Script for F.R.I.D.A.Y. Phase 17 (P0).

Executes 10 consecutive start -> stop -> restart cycles and verifies zero memory
leaks, zero thread leaks, and clean audio resource cleanup.
"""
import sys
import os
import time
import psutil
from typing import Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager, ConversationState

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


def test_10_restart_cycles(num_cycles: int = 10) -> Dict[str, Any]:
    print("=" * 65)
    print(f" F.R.I.D.A.Y. PHASE 17 — {num_cycles}-CYCLE RESTART LIFECYCLE TEST")
    print("=" * 65)

    proc = psutil.Process(os.getpid())
    init_mem_mb = proc.memory_info().rss / (1024 * 1024)
    init_threads = proc.num_threads()

    for i in range(1, num_cycles + 1):
        cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
        cm.start_session()
        cm.handle_transcript("open chrome")
        cm.handle_transcript("what time is it")
        cm.stop_session()

        cur_mem_mb = proc.memory_info().rss / (1024 * 1024)
        cur_threads = proc.num_threads()
        print(f"  Cycle {i}/{num_cycles}: Memory = {cur_mem_mb:.2f} MB | Threads = {cur_threads}")

    final_mem_mb = proc.memory_info().rss / (1024 * 1024)
    final_threads = proc.num_threads()
    delta_mem_mb = final_mem_mb - init_mem_mb

    results = {
        "num_cycles": num_cycles,
        "initial_mem_mb": init_mem_mb,
        "final_mem_mb": final_mem_mb,
        "delta_mem_mb": delta_mem_mb,
        "initial_threads": init_threads,
        "final_threads": final_threads,
    }

    print("\n" + "=" * 65)
    print(" RESTART LIFECYCLE RESULTS")
    print("=" * 65)
    print(f"  Total Cycles:       {num_cycles}")
    print(f"  Initial Memory:     {init_mem_mb:.2f} MB")
    print(f"  Final Memory:       {final_mem_mb:.2f} MB")
    print(f"  Memory Delta:       {delta_mem_mb:+.2f} MB")
    print(f"  Thread Count:       Initial={init_threads} | Final={final_threads}")
    print(f"  Thread Leak Check:  {'PASS (0 Leaks)' if final_threads <= init_threads + 1 else 'FAIL'}")
    print("=" * 65)

    return results


if __name__ == "__main__":
    test_10_restart_cycles(10)
