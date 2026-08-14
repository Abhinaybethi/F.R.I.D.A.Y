"""
PHASE 9 GATE TEST
==================
20-point verification of all Phase 9 safety invariants and architectural requirements.
All deterministic. No Ollama. No real OS execution.
"""
import sys
import os
import glob
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import registry, apps
from friday.intent.models import Action, Intent
from friday.safety.permissions import check_permission, PermissionResult
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.plan_validator import validate_plan
from friday.planning.executor import execute_plan_step
from friday.core.conversation import ConversationManager, ConversationState
from friday.verification.models import (
    ExecutionStatus,
    VerificationStatus,
    FinalStatus,
    ExecutionResult,
    VerificationResult,
    ActionOutcome,
)
from friday.verification.verifier import verify_execution

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


# Gate 1 — Verification layer exists
def test_gate1_verification_layer_exists():
    import friday.verification
    import friday.verification.models
    import friday.verification.verifier
    import friday.verification.action_verifiers
    import friday.verification.formatter
    print("[OK] Gate 1: Verification layer subsystem exists")


# Gate 2 — Execution and verification are separate
def test_gate2_execution_and_verification_are_separate():
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.SUCCESS,
        message="Opening Chrome.",
    )
    ver_res = VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message="Process chrome.exe found.",
    )
    assert exec_res.status != ver_res.status
    assert isinstance(exec_res, ExecutionResult)
    assert isinstance(ver_res, VerificationResult)
    print("[OK] Gate 2: Execution and verification results are separate")


# Gate 3 — Verification cannot execute actions
def test_gate3_verification_cannot_execute_actions():
    ver_dir = Path(__file__).parent.parent / "friday" / "verification"
    forbidden = ["shell=True", "os.system", "subprocess.Popen", "subprocess.run", "eval(", "exec("]
    for pyfile in glob.glob(str(ver_dir / "*.py")):
        with open(pyfile, encoding="utf-8") as f:
            src = f.read()
        for tok in forbidden:
            assert tok not in src, f"Forbidden token {tok!r} found in {pyfile}"
    print("[OK] Gate 3: Verification is strictly observational (read-only)")


# Gate 4 — Permission gate still works
def test_gate4_permission_gate_enforced():
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    outcome = registry.execute(_intent(Action.OPEN_APP, "chrome"), dry_run=False, allow_real_execution=True, permissions=perms)
    assert outcome.execution.status == ExecutionStatus.BLOCKED
    assert outcome.final_status == FinalStatus.BLOCKED
    print("[OK] Gate 4: Permission gate enforced before tool execution")


# Gate 5 — Confirmation gate still works
def test_gate5_confirmation_gate_enforced():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    print("[OK] Gate 5: CLOSE_APP requires confirmation")


# Gate 6 — Plan validation still works
def test_gate6_plan_validation_enforced():
    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False
    plan = ActionPlan(steps=[_intent(Action.OPEN_APP, "chrome"), _intent(Action.OPEN_WEBSITE, "youtube")])
    ok, reason = validate_plan(plan, perms)
    assert not ok
    print("[OK] Gate 6: Upfront plan validation enforced")


# Gate 7 — Reasoner plans still pass validation
def test_gate7_reasoner_plans_pass_validation():
    from friday.reasoning.interface import Reasoner
    from friday.planning.context_resolver import ShortTermContext

    class MockPlanReasoner(Reasoner):
        def request(self, transcript: str, context: ShortTermContext) -> dict:
            return {
                "type": "plan",
                "steps": [
                    {"action": "OPEN_APP", "target": "chrome"},
                    {"action": "OPEN_WEBSITE", "target": "youtube"},
                ],
                "confidence": 0.95,
            }
        def is_available(self) -> bool:
            return True
        def health(self) -> str:
            return "mock"
        def close(self):
            pass

    perms = dict(_ALL_ENABLED)
    perms["open_website"] = False
    cm = ConversationManager(dry_run=True, reasoner=MockPlanReasoner(), permissions=perms)
    cm.start_session()
    resp, keep = cm.handle_transcript("do multi-step stuff")
    # Plan rejected upfront because open_website is disabled
    assert cm.context.current_plan is None
    assert cm.state == ConversationState.LISTENING
    print("[OK] Gate 7: Reasoner-generated plans pass upfront plan validation")


# Gate 8 — Multi-step execution stops after failed verification or execution
def test_gate8_multistep_execution_stops_on_step_failure():
    plan = ActionPlan(steps=[
        _intent(Action.OPEN_APP, target="unknown_app_9999"),
        _intent(Action.OPEN_FOLDER, target="downloads"),
    ])
    response, requires_conf, is_completed, tool_res = execute_plan_step(
        plan, dry_run=True, permissions=_ALL_ENABLED
    )
    assert is_completed is True
    assert plan.state == PlanState.FAILED
    assert plan.current_step_index == 0
    print("[OK] Gate 8: Multi-step plan halts on step execution/verification failure")


# Gate 9 — Audit logging records execution + verification status + final status
def test_gate9_audit_logging_includes_verification():
    registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    audit_path = Path(__file__).parent.parent / "logs" / "friday_audit.log"
    assert audit_path.exists()
    with open(audit_path, encoding="utf-8") as f:
        content = f.read()
    assert "verification=" in content
    assert "final=" in content
    print("[OK] Gate 9: Audit log includes verification and final_status fields")


# Gate 10 — TTS receives final verified result
def test_gate10_tts_receives_final_verified_result():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("open chrome")
    assert resp == cm.context.last_response
    assert "DRY RUN" in resp or "Chrome" in resp
    print("[OK] Gate 10: TTS receives human-readable verified response")


# Gate 11 — dry_run remains true by default
def test_gate11_dry_run_default_is_true():
    cfg = _load_cfg()
    assert cfg.get("tools", {}).get("dry_run", True) is True
    print("[OK] Gate 11: dry_run remains True in default config")


# Gate 12 — allow_real_execution remains false by default
def test_gate12_allow_real_execution_default_is_false():
    cfg = _load_cfg()
    assert cfg.get("tools", {}).get("allow_real_execution", False) is False
    print("[OK] Gate 12: allow_real_execution remains False in default config")


# Gate 13 — No dangerous shell execution patterns
def test_gate13_no_dangerous_shell_execution():
    tools_dir = Path(__file__).parent.parent / "friday" / "tools"
    for pyfile in glob.glob(str(tools_dir / "*.py")):
        with open(pyfile, encoding="utf-8") as f:
            src = f.read()
        assert "shell=True" not in src
        assert "os.system" not in src
    print("[OK] Gate 13: Zero dangerous shell execution patterns in tool layer")


# Gate 14 — Legacy system_control is not wired into active pipeline
def test_gate14_legacy_system_control_not_wired():
    active_modules = [
        "main.py",
        "friday/core/conversation.py",
        "friday/tools/registry.py",
        "friday/tools/apps.py",
        "friday/tools/browser.py",
        "friday/tools/files.py",
        "friday/tools/system.py",
        "friday/planning/executor.py",
        "friday/planning/planner.py",
        "friday/intent/router.py",
        "friday/reasoning/local_reasoner.py",
    ]
    root_dir = Path(__file__).parent.parent
    for rel_path in active_modules:
        file_path = root_dir / rel_path
        if file_path.exists():
            with open(file_path, encoding="utf-8") as f:
                src = f.read()
            assert "friday.system_control" not in src, f"Legacy system_control imported in {rel_path}"
            assert "friday.skills" not in src, f"Legacy skills imported in {rel_path}"
    print("[OK] Gate 14: Legacy friday/system_control is not imported in active pipeline")


# Gate 15 — ExecutionStatus enum
def test_gate15_execution_status_enum():
    assert hasattr(ExecutionStatus, "SUCCESS")
    assert hasattr(ExecutionStatus, "FAILED")
    assert hasattr(ExecutionStatus, "BLOCKED")
    print("[OK] Gate 15: ExecutionStatus enum has required fields")


# Gate 16 — VerificationStatus enum
def test_gate16_verification_status_enum():
    assert hasattr(VerificationStatus, "VERIFIED_SUCCESS")
    assert hasattr(VerificationStatus, "FAILED")
    assert hasattr(VerificationStatus, "NOT_APPLICABLE")
    assert hasattr(VerificationStatus, "DRY_RUN")
    assert hasattr(VerificationStatus, "SKIPPED")
    print("[OK] Gate 16: VerificationStatus enum has required fields")


# Gate 17 — FinalStatus enum
def test_gate17_final_status_enum():
    assert hasattr(FinalStatus, "SUCCESS")
    assert hasattr(FinalStatus, "FAILED")
    assert hasattr(FinalStatus, "BLOCKED")
    assert hasattr(FinalStatus, "DRY_RUN")
    print("[OK] Gate 17: FinalStatus enum has required fields")


# Gate 18 — Single-intent execution returns ActionOutcome
def test_gate18_single_intent_returns_action_outcome():
    outcome = registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    assert isinstance(outcome, ActionOutcome)
    print("[OK] Gate 18: Single intent execution returns typed ActionOutcome")


# Gate 19 — Blocked execution skips verification
def test_gate19_blocked_execution_skips_verification():
    perms = dict(_ALL_ENABLED)
    perms["open_app"] = False
    outcome = registry.execute(_intent(Action.OPEN_APP, "chrome"), dry_run=False, allow_real_execution=True, permissions=perms)
    assert outcome.verification.status == VerificationStatus.SKIPPED
    print("[OK] Gate 19: Blocked execution skips verification")


# Gate 20 — ActionOutcome supports dict indexing
def test_gate20_action_outcome_dict_indexing():
    outcome = registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    assert outcome["success"] is True
    assert "message" in outcome
    assert outcome.get("blocked", False) is False
    print("[OK] Gate 20: ActionOutcome supports dict indexing for backward compatibility")


if __name__ == "__main__":
    import pytest
    print("=" * 60)
    print(" PHASE 9 GATE TEST")
    print("=" * 60)
    pytest.main([__file__, "-v", "--no-header", "--tb=short"])
