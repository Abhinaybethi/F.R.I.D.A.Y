"""
UNIT TEST — Verification Subsystem Security
============================================
Tests verification layer isolation and safety constraints.
No Ollama. No OS execution.
"""
import sys
import os
import glob
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.models import Action, Intent
from friday.verification import action_verifiers, verifier
from friday.verification.models import (
    ExecutionStatus,
    ExecutionResult,
    VerificationStatus,
)


def test_verifiers_contain_no_dangerous_execution_tokens():
    """Verify friday/verification/*.py files contain no dangerous execution tokens."""
    ver_dir = Path(__file__).parent.parent / "friday" / "verification"
    dangerous_tokens = ["shell=True", "os.system", "eval(", "exec(", "subprocess.Popen", "subprocess.run"]

    for py_file in glob.glob(str(ver_dir / "*.py")):
        with open(py_file, "r", encoding="utf-8") as f:
            content = f.read()
        for token in dangerous_tokens:
            assert token not in content, f"Forbidden token {token!r} found in {py_file}"


def test_verification_does_not_mutate_intent_or_execution():
    """verify_execution() must be observational and not alter intent or execution result."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.SUCCESS,
        message="Opening Chrome.",
    )
    intent_copy_target = intent.target
    exec_status_copy = exec_res.status

    v_res = verifier.verify_execution(intent, exec_res, is_dry_run=True)

    assert intent.target == intent_copy_target
    assert exec_res.status == exec_status_copy
    assert v_res.status == VerificationStatus.DRY_RUN


def test_verifier_skips_execution_when_exec_failed():
    """Verification is skipped when execution is FAILED or BLOCKED."""
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_failed = ExecutionResult(
        action=Action.OPEN_APP,
        target="chrome",
        status=ExecutionStatus.FAILED,
        message="Failed",
    )
    v_res = verifier.verify_execution(intent, exec_failed, is_dry_run=False)
    assert v_res.status == VerificationStatus.SKIPPED


def test_verifier_handles_arbitrary_untrusted_target_strings():
    """Action verifiers fail safely without exception when given arbitrary injection strings."""
    malicious_targets = [
        "chrome; rm -rf /",
        "../../etc/passwd",
        "powershell -c evil",
        "eval(os.system('id'))",
        "",
        "   ",
    ]
    for bad_target in malicious_targets:
        # OPEN_APP verifier
        res_app = action_verifiers.verify_open_app(bad_target, is_dry_run=False)
        assert res_app.status == VerificationStatus.FAILED

        # OPEN_FOLDER verifier
        res_folder = action_verifiers.verify_open_folder(bad_target, is_dry_run=False)
        assert res_folder.status == VerificationStatus.FAILED

        # OPEN_WEBSITE verifier
        res_site = action_verifiers.verify_open_website(bad_target, is_dry_run=False)
        assert res_site.status == VerificationStatus.FAILED


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
