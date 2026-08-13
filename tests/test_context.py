import os
import sys

# Ensure friday is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.intent.models import Action

def test_context():
    # Test 1: No context
    ctx = ShortTermContext()
    res, err = resolve_context("search for java instead", ctx)
    assert res == "search for java"
    assert not err
    
    # Test 2: "open the first result" with no results
    res, err = resolve_context("open the first result", ctx)
    assert err == "I don't have a result list to open."
    assert not res
    
    # Test 3: "open the first result" with results
    ctx.last_tool_result = {"results": [{"url": "https://python.org"}]}
    res, err = resolve_context("open the first result", ctx)
    assert res == "go to https://python.org"
    assert not err
    
    # Test 4: "open that" without context
    ctx.last_tool_result = None
    res, err = resolve_context("open that", ctx)
    assert err == "I don't have enough context for that."
    assert not res
    
    print("ALL CONTEXT TESTS PASSED")

if __name__ == "__main__":
    test_context()
