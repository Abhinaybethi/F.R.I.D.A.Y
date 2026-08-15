import pytest
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.intent.models import Intent, Action

def test_resolve_context_multi_turn():
    ctx = ShortTermContext()
    # Turn 1: open vscode
    ctx.history.append({"intent": Intent(action=Action.OPEN_APP, target="vscode")})
    # Turn 2: what time is it?
    ctx.history.append({"intent": Intent(action=Action.GET_TIME)})
    
    # User says "close it"
    resolved, err = resolve_context("close it", ctx)
    assert resolved == "close vscode"
    assert err == ""

def test_resolve_context_search_results_multi_turn():
    ctx = ShortTermContext()
    # Turn 1: search results
    ctx.history.append({
        "intent": Intent(action=Action.SEARCH_WEB, target="news"),
        "tool_result": {"success": True, "results": [{"title": "News", "url": "https://news.com"}]}
    })
    # Turn 2: some other intent
    ctx.history.append({"intent": Intent(action=Action.GET_TIME)})
    
    # User says "open the first result"
    resolved, err = resolve_context("open the first result", ctx)
    assert resolved == "go to https://news.com"
    assert err == ""
