"""
UNIT TEST — Real Hardware Barge-In (Phase 16 P0)
=================================================
Tests barge-in interruption latency benchmark script in scripts/benchmark_barge_in.py.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.benchmark_barge_in import benchmark_barge_in_latency


def test_barge_in_benchmark_execution():
    """benchmark_barge_in_latency() runs cleanly and reports p95 < 200 ms."""
    results = benchmark_barge_in_latency(num_attempts=5)
    assert results["success_rate"] == 100.0
    assert results["p95_ms"] < 200.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
