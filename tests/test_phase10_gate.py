"""
PHASE 10 GATE TEST
===================
20-point verification of Production Hardening, Legacy Isolation,
Configuration Safety, and Observability Invariants.
All deterministic. No Ollama required.
"""
import sys
import os
import glob
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.utils.config_validator import validate_config, VALID_PERMISSION_KEYS
from friday.utils.health_diagnostics import check_system_health
from friday.intent.models import Action, Intent
from friday.safety.permissions import check_permission, PermissionResult
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.plan_validator import validate_plan
from friday.core.conversation import ConversationManager, ConversationState
from friday.verification.models import ExecutionStatus, VerificationStatus, FinalStatus, ActionOutcome
from friday.tools import registry

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "", conf: float = 0.95) -> Intent:
    return Intent(
        action=action,
        target=target,
        intent_confidence=conf,
        target_confidence=conf,
        confidence=conf,
    )


def _load_cfg():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Gate 1 — config_validator exists & validates config
def test_gate1_config_validator_exists():
    is_valid, sanitized, msgs = validate_config(_load_cfg())
    assert is_valid is True
    assert "tools" in sanitized
    print("[OK] Gate 1: Config validator subsystem exists and passes default config")


# Gate 2 — dry_run fails closed to True
def test_gate2_dry_run_fails_closed():
    _, sanitized, _ = validate_config({"tools": {"dry_run": "invalid"}})
    assert sanitized["tools"]["dry_run"] is True
    print("[OK] Gate 2: dry_run fails closed to True on invalid type")


# Gate 3 — allow_real_execution fails closed to False
def test_gate3_allow_real_fails_closed():
    _, sanitized, _ = validate_config({"tools": {"allow_real_execution": "invalid"}})
    assert sanitized["tools"]["allow_real_execution"] is False
    print("[OK] Gate 3: allow_real_execution fails closed to False on invalid type")


# Gate 4 — Unknown permission keys are rejected
def test_gate4_unknown_permission_keys_rejected():
    _, sanitized, _ = validate_config({"tools": {"permissions": {"invalid_key_xyz": True}}})
    assert "invalid_key_xyz" not in sanitized["tools"]["permissions"]
    print("[OK] Gate 4: Unknown permission keys rejected")


# Gate 5 — Invalid permission values fail closed to False
def test_gate5_invalid_permission_value_fails_closed():
    _, sanitized, _ = validate_config({"tools": {"permissions": {"open_app": "invalid"}}})
    assert sanitized["tools"]["permissions"]["open_app"] is False
    print("[OK] Gate 5: Invalid permission value fails closed to False")


# Gate 6 — Legacy deprecation package exists
def test_gate6_legacy_deprecation_package_exists():
    import friday.legacy_deprecated
    assert hasattr(friday.legacy_deprecated, "__deprecated__")
    print("[OK] Gate 6: Legacy deprecation package friday.legacy_deprecated exists")


# Gate 7 — Active pipeline imports zero legacy code
def test_gate7_active_pipeline_imports_zero_legacy_code():
    active_files = [
        "main.py", "friday/core/assistant.py", "friday/core/conversation.py",
        "friday/tools/registry.py", "friday/planning/executor.py",
        "friday/intent/router.py", "friday/reasoning/local_reasoner.py",
    ]
    root = Path(__file__).parent.parent
    forbidden = ["friday.system_control", "friday.skills", "friday.brain", "command_router"]

    for rel in active_files:
        path = root / rel
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            for bad in forbidden:
                assert bad not in src, f"Forbidden legacy import {bad!r} found in {rel}"
    print("[OK] Gate 7: Active pipeline imports zero legacy code")


# Gate 8 — Health diagnostics subsystem exists
def test_gate8_health_diagnostics_subsystem_exists():
    health = check_system_health()
    assert "overall_status" in health
    assert "components" in health
    print("[OK] Gate 8: Health diagnostics subsystem exists and returns structured health map")


# Gate 9 — Assistant validates config on startup
def test_gate9_assistant_validates_config_on_startup():
    from friday.core.assistant import Friday
    assistant = Friday(config_path=str(CONFIG_PATH))
    assert hasattr(assistant, "config")
    assert assistant._dry_run is True
    assert assistant._allow_real_execution is False
    print("[OK] Gate 9: Friday assistant validates config on startup")


# Gate 10 — shell=True absent across friday/
def test_gate10_no_shell_true_in_friday():
    tools_dir = Path(__file__).parent.parent / "friday"
    for pyfile in glob.glob(str(tools_dir / "**" / "*.py"), recursive=True):
        with open(pyfile, encoding="utf-8") as f:
            src = f.read()
        assert "shell=True" not in src, f"shell=True found in {pyfile}"
    print("[OK] Gate 10: shell=True absent across friday/")


# Gate 11 — os.system absent across friday/
def test_gate11_no_os_system_in_friday():
    tools_dir = Path(__file__).parent.parent / "friday"
    for pyfile in glob.glob(str(tools_dir / "**" / "*.py"), recursive=True):
        with open(pyfile, encoding="utf-8") as f:
            src = f.read()
        assert "os.system" not in src, f"os.system found in {pyfile}"
    print("[OK] Gate 11: os.system absent across friday/")


# Gate 12 — eval( and exec( absent across friday/
def test_gate12_no_eval_exec_in_friday():
    tools_dir = Path(__file__).parent.parent / "friday"
    for pyfile in glob.glob(str(tools_dir / "**" / "*.py"), recursive=True):
        with open(pyfile, encoding="utf-8") as f:
            src = f.read()
        assert "eval(" not in src, f"eval( found in {pyfile}"
        assert "exec(" not in src, f"exec( found in {pyfile}"
    print("[OK] Gate 12: eval() and exec() absent across friday/")


# Gate 13 — Unrecognized shell commands fail closed
def test_gate13_unrecognized_commands_fail_closed():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("execute cmd")
    assert cm.state != ConversationState.EXECUTING
    print("[OK] Gate 13: Unrecognized shell commands fail closed")


# Gate 14 — Audit log contains structured [ACTION] lines
def test_gate14_audit_log_structured_lines():
    registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    audit_path = Path(__file__).parent.parent / "logs" / "friday_audit.log"
    assert audit_path.exists()
    with open(audit_path, encoding="utf-8") as f:
        content = f.read()
    assert "[ACTION]" in content
    print("[OK] Gate 14: Audit log contains structured [ACTION] lines")


# Gate 15 — ActionOutcome maintains dict indexing
def test_gate15_action_outcome_dict_indexing():
    outcome = registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    assert outcome["success"] is True
    assert "message" in outcome
    print("[OK] Gate 15: ActionOutcome maintains dict indexing for backward compatibility")


# Gate 16 — Upfront plan validation enforced
def test_gate16_upfront_plan_validation_enforced():
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False
    plan = ActionPlan(steps=[_intent(Action.OPEN_APP, "chrome"), _intent(Action.OPEN_WEBSITE, "youtube")])
    ok, reason = validate_plan(plan, perms)
    assert not ok
    print("[OK] Gate 16: Upfront plan validation enforced")


# Gate 17 — Safety policy enforced
def test_gate17_safety_policy_enforced():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    print("[OK] Gate 17: Safety policy enforced before tool execution")


# Gate 18 — CLOSE_APP requires confirmation
def test_gate18_close_app_requires_confirmation():
    perm = check_permission(_intent(Action.CLOSE_APP, "chrome"), _ALL_ENABLED)
    assert perm == PermissionResult.CONFIRM_REQUIRED
    print("[OK] Gate 18: CLOSE_APP requires explicit confirmation")


# Gate 19 — Multi-step plan halts on step failure
def test_gate19_multistep_plan_halts_on_step_failure():
    plan = ActionPlan(steps=[_intent(Action.OPEN_APP, "unknown_app_12345"), _intent(Action.OPEN_FOLDER, "downloads")])
    from friday.planning.executor import execute_plan_step
    resp, req_conf, completed, tool_res = execute_plan_step(plan, dry_run=True, permissions=_ALL_ENABLED)
    assert completed is True
    assert plan.state == PlanState.FAILED
    print("[OK] Gate 19: Multi-step plan halts execution on step failure")


# Gate 20 — dry_run: true and allow_real_execution: false defaults in config.yaml
def test_gate20_config_yaml_defaults():
    cfg = _load_cfg()
    tools = cfg.get("tools", {})
    assert tools.get("dry_run", True) is True
    assert tools.get("allow_real_execution", False) is False
    print("[OK] Gate 20: config.yaml defaults remain dry_run: true and allow_real_execution: false")


if __name__ == "__main__":
    import pytest
    print("=" * 60)
    print(" PHASE 10 GATE TEST")
    print("=" * 60)
    pytest.main([__file__, "-v", "--no-header", "--tb=short"])
