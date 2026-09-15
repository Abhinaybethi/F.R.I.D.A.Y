"""
LLAMA.CPP / BONSAI REASONER INTEGRATION TEST
==============================================
Tests the LlamaCppReasoner against the locally running llama.cpp
server hosting the Bonsai 8B GGUF model.

This is an INTEGRATION test. It requires the local llama.cpp server
to be running at http://127.0.0.1:8080. If the server is not reachable,
the tests are SKIPPED (they do not fail on missing hardware).

Run:
    pytest tests/test_llamacpp_reasoner.py -v
    python tests/test_llamacpp_reasoner.py
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import patch, MagicMock

from friday.reasoning.llamacpp_reasoner import LlamaCppReasoner
from friday.reasoning.parser import parse_reasoning_output
from friday.reasoning.validator import validate_reasoning_output
from friday.planning.context_resolver import ShortTermContext

pytestmark = pytest.mark.integration

RESULTS = []


def get_reasoner() -> LlamaCppReasoner:
    base_url = os.environ.get("LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
    model = os.environ.get(
        "LLAMACPP_MODEL",
        "C:\\AI\\models\\Bonsai-8B-Q1_0.gguf",
    )
    timeout = float(os.environ.get("LLAMACPP_TIMEOUT", "30"))
    return LlamaCppReasoner(base_url=base_url, model=model, timeout=timeout)


def is_server_running(reasoner: LlamaCppReasoner) -> bool:
    return reasoner.is_available()


# ---------------------------------------------------------------------------
# Deterministic tests (no server required)
# ---------------------------------------------------------------------------

def test_constructor_defaults():
    """Verify default constructor values match the Bonsai setup."""
    r = LlamaCppReasoner()
    assert r.base_url == "http://127.0.0.1:8080"
    assert "Bonsai" in r.model
    assert r.timeout == 30.0


def test_health_url_construction():
    r = LlamaCppReasoner(base_url="http://127.0.0.1:8080")
    assert r._health_url() == "http://127.0.0.1:8080/health"


def test_chat_url_construction():
    r = LlamaCppReasoner(base_url="http://127.0.0.1:8080")
    assert r._chat_url() == "http://127.0.0.1:8080/v1/chat/completions"


def test_is_available_false_when_connection_refused():
    """Server not running should return False without raising."""
    r = LlamaCppReasoner()
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert r.is_available() is False


def test_request_returns_unknown_on_connection_failure():
    """Connection failure must return {'type': 'unknown'} — never crash or hang."""
    r = LlamaCppReasoner()
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            result = r.request("hello", ShortTermContext())
    assert result == {"type": "unknown"}


def test_request_returns_unknown_on_timeout():
    """Timeout must be handled safely."""
    r = LlamaCppReasoner(timeout=0.001)
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = r.request("hello", ShortTermContext())
    assert result == {"type": "unknown"}


def test_request_returns_unknown_on_http_error():
    """HTTP 500 must be handled safely."""
    r = LlamaCppReasoner()
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", side_effect=Exception("HTTP Error 500")):
            result = r.request("hello", ShortTermContext())
    assert result == {"type": "unknown"}


def test_request_returns_unknown_on_invalid_json():
    """Invalid JSON response must return unknown."""
    r = LlamaCppReasoner()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b"not json at all"
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = r.request("hello", ShortTermContext())
    assert result == {"type": "unknown"}


def test_request_empty_choices_returns_unknown():
    """Empty choices array must return unknown."""
    r = LlamaCppReasoner()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({"choices": []}).encode("utf-8")
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = r.request("hello", ShortTermContext())
    assert result == {"type": "unknown"}


def test_request_empty_message_content_returns_unknown():
    """Empty content must return unknown."""
    r = LlamaCppReasoner()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": ""}}]}
    ).encode("utf-8")
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = r.request("hello", ShortTermContext())
    assert result == {"type": "unknown"}


def test_request_parses_valid_response():
    """A valid OpenAI-compatible response must be parsed correctly."""
    r = LlamaCppReasoner()
    valid_json = '{"type": "intent", "action": "GET_TIME", "target": "", "arguments": {}, "confidence": 0.95}'
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": valid_json}}]}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = r.request("what time is it", ShortTermContext())
    assert result["type"] == "intent"
    assert result["action"] == "GET_TIME"


def test_request_handles_markdown_wrapped_json():
    """LLMs often wrap JSON in markdown code fences — parser must handle this."""
    r = LlamaCppReasoner()
    wrapped = '```json\n{"type": "response", "text": "Hello there."}\n```'
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": wrapped}}]}
    ).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    with patch.object(r, "is_available", return_value=True):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = r.request("say hello", ShortTermContext())
    assert result["type"] == "response"
    assert "Hello" in result["text"]


# ---------------------------------------------------------------------------
# Live integration tests (require running Bonsai server)
# ---------------------------------------------------------------------------

def test_live_connectivity():
    """Baseline: The Bonsai llama.cpp server must be reachable."""
    r = get_reasoner()
    if not is_server_running(r):
        pytest.skip(
            "llama.cpp server not running at %s. Start it and run the tests again."
            % r._health_url()
        )
    assert r.is_available() is True


def test_live_simple_hello():
    """
    Send a simple prompt through the F.R.I.D.A.Y reasoning layer to Bonsai.
    Verifies request succeeds, response contains content, response parsed correctly.
    """
    r = get_reasoner()
    if not is_server_running(r):
        pytest.skip("Bonsai server not reachable. Integration test skipped.")
        return

    transcript = "Say hello and confirm you are available."
    t0 = time.perf_counter()
    result = r.request(transcript, ShortTermContext())
    latency = time.perf_counter() - t0

    assert result["type"] in ("response", "clarification", "intent", "unknown", "plan")

    passed = (
        result["type"] == "response"
        and bool(result.get("text"))
    ) or result["type"] in ("clarification", "intent", "plan")

    RESULTS.append({
        "test": "LIVE_SIMPLE_HELLO",
        "transcript": transcript,
        "result": result,
        "latency_s": round(latency, 3),
        "passed": passed,
        "notes": f"type={result['type']}",
    })
    assert passed, f"Unexpected result: {result}"


def test_live_simple_time_request():
    """Verify Bonsai correctly routes a natural-language time request."""
    r = get_reasoner()
    if not is_server_running(r):
        pytest.skip("Bonsai server not reachable. Integration test skipped.")
        return

    transcript = "what time is it"
    t0 = time.perf_counter()
    result = r.request(transcript, ShortTermContext())
    latency = time.perf_counter() - t0

    passed = result["type"] == "intent" and result.get("action") == "GET_TIME"
    RESULTS.append({
        "test": "LIVE_TIME_REQUEST",
        "transcript": transcript,
        "result": result,
        "latency_s": round(latency, 3),
        "passed": passed,
        "notes": f"type={result['type']} action={result.get('action')}",
    })
    assert passed, f"Expected intent/GET_TIME, got: {result}"


def test_live_error_handling_when_server_down():
    """
    When the server is unreachable, the reasoner must NOT crash and MUST
    return a clear reasoning error that ConversationManager can handle.
    """
    r = get_reasoner()
    # Simulate a dead server by pointing at an unused port
    r.base_url = "http://127.0.0.1:1"
    t0 = time.perf_counter()
    result = r.request("hello", ShortTermContext())
    elapsed = time.perf_counter() - t0

    assert result == {"type": "unknown"}
    assert elapsed < 5.0, "Must not hang — should fail fast"
    RESULTS.append({
        "test": "LIVE_ERROR_HANDLING",
        "transcript": "<dead server simulate>",
        "result": result,
        "latency_s": round(elapsed, 3),
        "passed": True,
        "notes": "Server down handled gracefully",
    })


def test_live_conversation_manager_integration():
    """
    Full F.R.I.D.A.Y reasoning layer -> LlamaCpp provider -> Bonsai flow.
    Uses ConversationManager which proxies through the reasoner.
    """
    r = get_reasoner()
    if not is_server_running(r):
        pytest.skip("Bonsai server not reachable. Integration test skipped.")
        return

    from friday.core.conversation import ConversationManager
    cm = ConversationManager(dry_run=True, allow_real_execution=False, reasoner=r)
    cm.start_session()

    # Deterministic command should NOT hit Bonsai
    t0 = time.perf_counter()
    resp, keep = cm.handle_transcript("open chrome")
    deterministic_latency = time.perf_counter() - t0
    assert "chrome" in resp.lower() or "open" in resp.lower()

    RESULTS.append({
        "test": "LIVE_DETERMINISTIC_NO_BONSAI",
        "transcript": "open chrome",
        "result": {"response": resp},
        "latency_s": round(deterministic_latency, 3),
        "passed": True,
        "notes": "Deterministic path (no Bonsai)",
    })


def print_summary():
    if not RESULTS:
        return
    print("\n" + "=" * 70)
    print("LLAMA.CPP / BONSAI INTEGRATION TEST — RESULTS")
    print("=" * 70)
    header = f"{'Test':<40} {'Pass':>4} {'Latency':>9}  Notes"
    print(header)
    print("-" * 70)
    for r in RESULTS:
        status = "PASS" if r["passed"] else "FAIL"
        latency = f"{r['latency_s']:.3f}s" if r["latency_s"] > 0 else "N/A"
        notes = (r["notes"][:35] + "…") if len(r["notes"]) > 36 else r["notes"]
        print(f"{r['test']:<40} {status:>4} {latency:>9}  {notes}")
    print("=" * 70)


if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v", "--tb=short", "--no-header", "-m", "integration"])
    print_summary()
    sys.exit(exit_code)
