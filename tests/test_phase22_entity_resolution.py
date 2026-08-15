"""
UNIT TEST — Phase 22 Entity & Reference Resolution Engine
===========================================================
Tests ordinal indexing (#1..#N), pronouns ("it", "that"), and multi-turn reference resolution in context_resolver.py.
"""
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.intent.models import Action, Intent


def test_ordinal_search_result_resolution():
    results = [
        {"title": "Result 1", "url": "https://example.com/1"},
        {"title": "Result 2", "url": "https://example.com/2"},
        {"title": "Result 3", "url": "https://example.com/3"},
    ]
    ctx = ShortTermContext(last_search_results=results)

    # First result
    res, err = resolve_context("open the first result", ctx)
    assert res == "go to https://example.com/1"
    assert not err

    # Second result
    res, err = resolve_context("open the second result", ctx)
    assert res == "go to https://example.com/2"
    assert not err

    # Third result via "use third result"
    res, err = resolve_context("use 3rd result", ctx)
    assert res == "go to https://example.com/3"
    assert not err

    # Read second result
    res, err = resolve_context("read the second result", ctx)
    assert res == "read website https://example.com/2"
    assert not err


def test_pronoun_anaphora_resolution():
    ctx = ShortTermContext(
        last_target="chrome",
        last_action=Action.OPEN_APP,
        history=[{"intent": Intent(action=Action.OPEN_APP, target="chrome", confidence=1.0)}]
    )

    # close it
    res, err = resolve_context("close it", ctx)
    assert res == "close chrome"
    assert not err

    # open it
    res, err = resolve_context("open it", ctx)
    assert res == "open chrome"
    assert not err


def test_save_it_resolution():
    ctx = ShortTermContext(
        last_target="https://example.com/article",
        last_action=Action.READ_WEBSITE
    )
    res, err = resolve_context("save it", ctx)
    assert res == "remember https://example.com/article"
    assert not err
