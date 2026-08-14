"""
PHASE 8 GATE TEST
==================
17-point verification of all Phase 8 safety invariants.
All deterministic. No Ollama. No real OS calls.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from pathlib import Path

from friday.tools import registry, apps, browser
from friday.intent.models import Action, Intent
from friday.safety.permissions import check_permission, PermissionResult
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.plan_validator import validate_plan
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "", conf: float = 0.95) -> Intent:
    return Intent(action=action, target=target,
                  intent_confidence=conf, target_confidence=conf)


def _load_cfg():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Gate 1 — Default config is safe
def test_gate1_default_config_is_safe():
    """Config must have dry_run=True and allow_real_execution=False by default."""
    cfg = _load_cfg()
    t = cfg.get("tools", {})
    assert t.get("dry_run", True) is True, "dry_run must be True in default config"
    assert t.get("allow_real_execution", False) is False, "allow_real_execution must be False in default config"
    print("[OK] Gate 1: default config is safe")


# Gate 2 — dry_run=True prevents real execution
def test_gate2_dry_run_prevents_execution():
    result = registry.execute(_intent(Action.OPEN_APP, "notepad"), dry_run=True,
                              allow_real_execution=True, permissions=_ALL_ENABLED)
    assert "DRY RUN" in result["message"] or "Would" in result["message"]
    print("[OK] Gate 2: dry_run=True prevents real execution")


# Gate 3 — allow_real_execution=False prevents execution
def test_gate3_allow_real_false_prevents_execution():
    result = registry.execute(_intent(Action.OPEN_APP, "notepad"), dry_run=False,
                              allow_real_execution=False, permissions=_ALL_ENABLED)
    assert "DRY RUN" in result["message"] or "Would" in result["message"]
    print("[OK] Gate 3: allow_real_execution=False prevents real execution")


# Gate 4 — Both gates must pass
def test_gate4_both_gates_required():
    # With dry_run=True only
    r = registry.execute(_intent(Action.OPEN_APP, "notepad"), dry_run=True,
                         allow_real_execution=False, permissions=_ALL_ENABLED)
    assert "DRY RUN" in r["message"] or "Would" in r["message"]
    print("[OK] Gate 4: both gates required for real execution")


# Gate 5 — Unknown action is denied
def test_gate5_unknown_action_denied():
    result = registry.execute(_intent(Action.UNKNOWN), dry_run=True,
                              permissions=_ALL_ENABLED)
    assert result.get("blocked") is True
    print("[OK] Gate 5: UNKNOWN action is blocked")


# Gate 6 — Unknown target is denied at tool level
def test_gate6_unknown_target_denied():
    result = apps.open_app("notarealapp", dry_run=True)
    assert not result["success"]
    print("[OK] Gate 6: unknown target rejected by tool whitelist")


# Gate 7 — Arbitrary executable paths are denied
def test_gate7_arbitrary_exe_denied():
    result = apps.open_app(r"C:\evil\malware.exe", dry_run=True)
    assert not result["success"]
    print("[OK] Gate 7: arbitrary executable paths denied")


# Gate 8 — Shell commands are denied (no shell=True in codebase)
def test_gate8_no_shell_true_in_tools():
    import glob
    tools_dir = Path(__file__).parent.parent / "friday" / "tools"
    for pyfile in glob.glob(str(tools_dir / "*.py")):
        with open(pyfile, encoding="utf-8") as f:
            src = f.read()
        assert "shell=True" not in src, f"shell=True found in {pyfile}"
    print("[OK] Gate 8: shell=True absent from all tool files")


# Gate 9 — PowerShell is denied
def test_gate9_powershell_denied():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("run powershell")
    assert cm.state != ConversationState.EXECUTING
    print("[OK] Gate 9: PowerShell command rejected")


# Gate 10 — File deletion is denied (action doesn't exist)
def test_gate10_file_deletion_not_implemented():
    """DELETE_FILE does not exist in Action enum — structurally impossible."""
    action_names = {a.name for a in Action}
    assert "DELETE_FILE" not in action_names
    assert "MOVE_FILE" not in action_names
    assert "RUN_COMMAND" not in action_names
    assert "RUN_POWERSHELL" not in action_names
    print("[OK] Gate 10: destructive actions not in Action enum")


# Gate 11 — CLOSE_APP requires confirmation
def test_gate11_close_app_requires_confirmation():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert keep
    print("[OK] Gate 11: CLOSE_APP requires confirmation")


# Gate 12 — Confirmation cannot be bypassed by LLM (mock reasoner test)
def test_gate12_llm_cannot_bypass_confirmation():
    """Even if the LLM produces CLOSE_APP, the safety validator enforces CONFIRM."""
    from friday.reasoning.interface import Reasoner
    from friday.planning.context_resolver import ShortTermContext

    class MockReasoner(Reasoner):
        def request(self, transcript: str, context: ShortTermContext) -> dict:
            return {"type": "intent", "action": "CLOSE_APP",
                    "target": "chrome", "confidence": 0.99}
        def is_available(self) -> bool:
            return True
        def health(self) -> str:
            return "mock"
        def close(self):
            pass

    cm = ConversationManager(dry_run=True, reasoner=MockReasoner(), permissions=_ALL_ENABLED)
    cm.start_session()
    # Input not matched by deterministic router → falls through to MockReasoner
    cm.handle_transcript("please close chrome for me immediately")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    print("[OK] Gate 12: LLM cannot bypass confirmation for CLOSE_APP")


# Gate 13 — Confirmation cannot be bypassed by planner
def test_gate13_planner_cannot_bypass_confirmation():
    """Multi-step plan with CLOSE_APP must pause for confirmation."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("open chrome and close vscode")
    # Must be waiting for confirmation on the close step
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    print("[OK] Gate 13: planner cannot bypass confirmation for CLOSE_APP")


# Gate 14 — Multi-step plans independently validate each step
def test_gate14_plan_steps_independently_validated():
    """Each plan step is validated; a DENIED step rejects the whole plan."""
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False
    steps = [_intent(Action.OPEN_APP, "chrome"), _intent(Action.OPEN_WEBSITE, "youtube")]
    plan = ActionPlan(steps=steps)
    ok, reason = validate_plan(plan, perms)
    assert not ok
    print("[OK] Gate 14: plan steps independently validated; denied step rejects plan")


# Gate 15 — One denied step aborts remaining execution
def test_gate15_denied_step_aborts_plan():
    """validate_plan with a denied step returns False — entire plan is rejected."""
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    steps = [_intent(Action.OPEN_APP, "chrome"), _intent(Action.GET_TIME)]
    plan = ActionPlan(steps=steps)
    ok, _ = validate_plan(plan, perms)
    assert not ok
    print("[OK] Gate 15: denied step aborts entire plan before execution")


# Gate 16 — Real execution produces audit log
def test_gate16_audit_log_written():
    """registry.execute() must write to the audit log."""
    registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    audit_path = Path(__file__).parent.parent / "logs" / "friday_audit.log"
    assert audit_path.exists()
    with open(audit_path, encoding="utf-8") as f:
        content = f.read()
    assert "GET_TIME" in content
    print("[OK] Gate 16: audit log written with action details")


# Gate 17 — Permission config present in config.yaml
def test_gate17_permission_config_in_yaml():
    """config.yaml must have a tools.permissions section."""
    cfg = _load_cfg()
    t = cfg.get("tools", {})
    perms = t.get("permissions", {})
    assert isinstance(perms, dict), "tools.permissions must be a dict"
    assert "open_app" in perms
    assert "close_app" in perms
    assert "open_website" in perms
    print("[OK] Gate 17: permissions section present in config.yaml")


if __name__ == "__main__":
    import pytest
    print("=" * 60)
    print(" PHASE 8 GATE TEST")
    print("=" * 60)
    pytest.main([__file__, "-v", "--no-header", "--tb=short"])
