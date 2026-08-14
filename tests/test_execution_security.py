"""
UNIT TEST — Execution Security
================================
Tests that malicious inputs, injection attempts, and denied actions
are blocked at every layer. No Ollama. No real execution.

All tests are DRY RUN UNIT TESTS — no real OS calls.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import registry
from friday.intent.models import Action, Intent
from friday.safety.permissions import check_permission, PermissionResult
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.plan_validator import validate_plan
from friday.reasoning.validator import validate_reasoning_output
from friday.reasoning.parser import parse_reasoning_output
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "", conf: float = 0.95) -> Intent:
    return Intent(action=action, target=target,
                  intent_confidence=conf, target_confidence=conf)


# ---------------------------------------------------------------------------
# Denied command strings through the full deterministic pipeline
# ---------------------------------------------------------------------------

def test_run_powershell_denied():
    """'run powershell' must not produce an executable action."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, _ = cm.handle_transcript("run powershell")
    # Must not be in EXECUTING state
    assert cm.state != ConversationState.EXECUTING


def test_execute_cmd_denied():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("execute cmd")
    assert cm.state != ConversationState.EXECUTING


def test_run_rm_rf_denied():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("run rm -rf on my computer")
    assert cm.state != ConversationState.EXECUTING


def test_delete_files_denied():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("delete my files")
    assert cm.state != ConversationState.EXECUTING


def test_delete_c_users_denied():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("delete C:\\Users")
    assert cm.state != ConversationState.EXECUTING


def test_open_malicious_exe_denied():
    """Arbitrary .exe paths are not in the app whitelist → denied at tool level."""
    result = registry.execute(
        _intent(Action.OPEN_APP, r"C:\malicious.exe"),
        dry_run=True,
        permissions=_ALL_ENABLED,
    )
    # The tool layer rejects unknown app names
    assert not result["success"] or "DRY RUN" in result.get("message", "")
    # Even in dry-run: unknown app name means the tool returns success=False OR a dry-run message
    # The key invariant: if NOT in the whitelist, success must be False
    if "DRY RUN" not in result.get("message", ""):
        assert not result["success"]


def test_open_malicious_exe_not_in_whitelist():
    """Directly test that the app layer rejects names not in _APP_EXECUTABLES."""
    from friday.tools.apps import open_app
    result = open_app(r"C:\malicious.exe", dry_run=True)
    assert not result["success"]
    assert "Not in registry" in result["message"]


def test_run_shell_command_verb():
    """Any shell-command-like transcript must not reach the tool layer as executable."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("execute shell command dir /s")
    assert cm.state != ConversationState.EXECUTING


def test_execute_python_denied():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("execute python")
    assert cm.state != ConversationState.EXECUTING


# ---------------------------------------------------------------------------
# LLM-generated malicious JSON rejected by reasoning validator
# ---------------------------------------------------------------------------

def test_llm_run_command_json_rejected():
    """LLM output with RUN_COMMAND action must be rejected by the validator."""
    raw = '{"type":"intent","action":"RUN_COMMAND","target":"powershell","arguments":{"command":"rm -rf /"},"confidence":0.95}'
    parsed = parse_reasoning_output(raw)
    validated = validate_reasoning_output(parsed)
    assert validated == {"type": "unknown"}, f"Expected unknown, got: {validated}"


def test_llm_shell_true_json_rejected():
    """LLM output with shell argument key must be rejected."""
    raw = '{"type":"intent","action":"OPEN_APP","target":"chrome","arguments":{"shell":"powershell -c malicious"},"confidence":0.9}'
    validated = validate_reasoning_output(parse_reasoning_output(raw))
    assert validated == {"type": "unknown"}


def test_llm_eval_in_target_goes_through_whitelist():
    """Even if LLM puts eval() in a target, the app whitelist blocks it."""
    result = registry.execute(
        _intent(Action.OPEN_APP, "eval(os.system('rm -rf /'))"),
        dry_run=True,
        permissions=_ALL_ENABLED,
    )
    assert not result["success"]


# ---------------------------------------------------------------------------
# Permission gate blocks denied categories
# ---------------------------------------------------------------------------

def test_permission_gate_blocks_search_web():
    """If search_web permission is disabled, SEARCH_WEB must be blocked."""
    perms = dict(_ALL_ENABLED)
    perms["search_web"] = False
    result = registry.execute(
        _intent(Action.SEARCH_WEB, "python tutorials"),
        dry_run=True,
        permissions=perms,
    )
    assert result.get("blocked") is True


def test_permission_gate_blocks_open_website():
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False
    result = registry.execute(
        _intent(Action.OPEN_WEBSITE, "youtube"),
        dry_run=True,
        permissions=perms,
    )
    assert result.get("blocked") is True


# ---------------------------------------------------------------------------
# Plan pre-validation blocks plans with denied steps
# ---------------------------------------------------------------------------

def test_plan_prevalidation_rejects_denied_step():
    """A plan with a DENIED step must be rejected before any step executes."""
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False  # deny one action

    steps = [
        _intent(Action.OPEN_APP, "chrome"),
        _intent(Action.OPEN_WEBSITE, "youtube"),  # denied
    ]
    plan = ActionPlan(steps=steps)
    ok, reason = validate_plan(plan, perms)
    assert not ok
    assert "OPEN_WEBSITE" in reason or "not permitted" in reason


def test_plan_prevalidation_accepts_confirm_required_step():
    """A plan with a CLOSE_APP (CONFIRM_REQUIRED) step must be accepted."""
    steps = [
        _intent(Action.OPEN_APP, "chrome"),
        _intent(Action.CLOSE_APP, "chrome"),  # confirm required, not denied
    ]
    plan = ActionPlan(steps=steps)
    ok, reason = validate_plan(plan, _ALL_ENABLED)
    assert ok, f"Plan with CONFIRM_REQUIRED step should be accepted: {reason}"


def test_conversation_plan_denied_step_rejected():
    """ConversationManager must reject a plan where one step is permission-denied."""
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False

    cm = ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        permissions=perms,
    )
    cm.start_session()
    # "open chrome and open youtube" — chrome OK, youtube blocked by permission
    resp, keep = cm.handle_transcript("open chrome and open youtube")
    # Plan must be rejected — state returns to LISTENING
    assert cm.state == ConversationState.LISTENING
    assert cm.context.current_plan is None
    assert keep


# ---------------------------------------------------------------------------
# Multi-step plans: safe step + denied step aborts entire plan
# ---------------------------------------------------------------------------

def test_multistep_safe_then_denied_aborts_plan():
    """Entire plan rejected if any step is denied — no partial execution."""
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False

    steps = [
        _intent(Action.OPEN_APP, "chrome"),
        _intent(Action.OPEN_APP, "notepad"),
        _intent(Action.OPEN_WEBSITE, "youtube"),   # denied
    ]
    plan = ActionPlan(steps=steps)
    ok, reason = validate_plan(plan, perms)
    assert not ok


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
