"""
UNIT TEST — Real Voice Pipeline Latency (Phase 16 P0)
======================================================
Tests pipeline latency benchmark script in scripts/benchmark_voice_pipeline.py.
Target: < 800 ms voice-to-response latency for deterministic commands.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.benchmark_voice_pipeline import benchmark_voice_to_response_pipeline


def test_voice_pipeline_benchmark_execution():
    """benchmark_voice_to_response_pipeline() runs cleanly and reports p95 < 800 ms."""
    results = benchmark_voice_to_response_pipeline(num_samples=5)
    for cat_name, metrics in results.items():
        assert metrics["p95"] < 800.0, f"{cat_name} exceeded 800 ms target ({metrics['p95']:.2f} ms)"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
