import os
import sys

# Ensure friday is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState
from friday.planning.planner import parse_plan
from friday.planning.context_resolver import ShortTermContext
from friday.intent.models import Intent, Action

def test_gate():
    print("========================================")
    print(" PHASE 6 GATE TEST")
    print("========================================")
    
    # 1. Maximum 5 steps
    ctx = ShortTermContext()
    long_cmd = "open chrome and open youtube and search for python and open github and open vscode and open downloads"
    plan, err = parse_plan(long_cmd, ctx)
    assert plan is None
    assert err is not None
    print("[OK] Max 5 steps enforced.")
    
    # 2. No execution after failed step
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    # Step 1: open chrome (SAFE)
    # Step 2: blood growing (UNKNOWN -> REJECT)
    # Step 3: open youtube (SAFE)
    # The planner itself will reject "blood growing" during parsing.
    resp, keep = cm.handle_transcript("open chrome and blood growing and open youtube")
    assert keep
    # Plan must be rejected at parse — no partial plan should be executing
    assert cm.context.current_plan is None
    # Response must be non-empty (deterministic rejection OR reasoner fallback)
    assert resp
    print("[OK] Failed step stops plan (rejected at parse).")
    
    # 3. Confirmation pauses correct step
    resp, keep = cm.handle_transcript("open chrome and close vscode and open youtube")
    assert keep
    assert "Would open Chrome" in resp or "Opening Chrome" in resp
    assert "Do you want me to close Vscode?" in resp
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    print("[OK] Confirmation pauses correct step.")
    
    # 4. Confirmation executes exactly once
    resp, keep = cm.handle_transcript("yes")
    assert keep
    assert "Would close VS Code" in resp or "Closing VS Code" in resp
    assert "Would open https://www.youtube.com" in resp or "Opening Youtube" in resp
    assert cm.state == ConversationState.LISTENING
    assert cm.context.current_plan is None
    
    # Send another "yes" — should not execute anything (no pending confirmation)
    resp, keep = cm.handle_transcript("yes")
    # Core invariant: no plan is active and no pending confirmation exists.
    # Response text may be a safe rejection OR a conversational response from the reasoner.
    assert cm.context.current_plan is None
    assert cm.context.pending_intent is None
    assert cm.state == ConversationState.LISTENING
    assert resp  # must say something
    print("[OK] Confirmation executes exactly once.")
    
    # 5. Cancel clears plan
    cm.handle_transcript("open chrome and close vscode")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    resp, keep = cm.handle_transcript("cancel")
    assert cm.context.current_plan is None
    assert cm.state == ConversationState.LISTENING
    assert "Cancelled" in resp
    print("[OK] Cancel clears plan.")
    
    # 6. Stop clears plan
    cm.handle_transcript("open chrome and close vscode")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    resp, keep = cm.handle_transcript("stop")
    assert cm.context.current_plan is None
    assert cm.state == ConversationState.STOPPING
    assert not keep
    print("[OK] Stop clears plan.")
    
    # 7. Unknown intents rejected
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    resp, keep = cm.handle_transcript("blood growing")
    # Core invariant: no execution, state back to LISTENING, some response given.
    assert keep
    assert cm.state == ConversationState.LISTENING
    assert cm.context.current_plan is None
    assert cm.context.pending_intent is None
    assert resp
    print("[OK] Unknown intents rejected.")
    
    # 8. Context does not leak between managers
    cm_a = ConversationManager(dry_run=True, allow_real_execution=False)
    cm_b = ConversationManager(dry_run=True, allow_real_execution=False)
    cm_a.start_session()
    cm_b.start_session()
    
    cm_a.handle_transcript("search for python tutorials")
    cm_b.handle_transcript("search for java tutorials")
    
    assert cm_a.context.last_search_query == "python tutorials"
    assert cm_b.context.last_search_query == "java tutorials"
    
    resp_a, _ = cm_a.handle_transcript("search for ruby instead")
    assert "ruby" in resp_a.lower() and "java" not in resp_a.lower()
    print("[OK] Context isolated.")
    
    # 9. Planner produces only Intent objects
    plan, err = parse_plan("open chrome and open youtube", ShortTermContext())
    for step in plan.steps:
        assert isinstance(step, Intent)
    print("[OK] Planner outputs strictly typed Intents.")
    
    # 10. Real execution remains disabled
    import yaml
    from pathlib import Path
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    tools_cfg = cfg.get("tools", {})
    assert tools_cfg.get("dry_run", True) == True
    assert tools_cfg.get("allow_real_execution", False) == False
    print("[OK] Safety locks verified in config.")
    
    print("========================================")
    print(" PHASE 6 GATE TEST PASSED")
    print("========================================")

if __name__ == "__main__":
    test_gate()
