"""
UNIT TEST — Phase 11 Release Candidate Security Audit
======================================================
Verifies trust boundaries, RELEASE_TEST_MODE isolation,
codebase safety invariants, and release candidate readiness.
No Ollama required. All deterministic.
"""
import sys
import os
import glob
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.tools import registry, apps, browser, files
from friday.intent.models import Action, Intent
from friday.verification.models import VerificationStatus, FinalStatus

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def _intent(action: Action, target: str = "") -> Intent:
    return Intent(action=action, target=target, confidence=0.95)


def test_security_release_test_mode_whitelist_isolation():
    """RELEASE_TEST_MODE permits real execution ONLY for (OPEN_APP, chrome), (OPEN_WEBSITE, youtube), (OPEN_FOLDER, downloads)."""
    # Allowed in RELEASE_TEST_MODE whitelist:
    outcome_chrome = registry.execute(_intent(Action.OPEN_APP, "chrome"), dry_run=True, permissions=_ALL_ENABLED, release_test_mode=True)
    assert outcome_chrome.verification.status in (VerificationStatus.VERIFIED_SUCCESS, VerificationStatus.FAILED)

    # NOT in RELEASE_TEST_MODE whitelist -> forced dry_run:
    outcome_notepad = registry.execute(_intent(Action.OPEN_APP, "notepad"), dry_run=True, permissions=_ALL_ENABLED, release_test_mode=True)
    assert outcome_notepad.verification.status == VerificationStatus.DRY_RUN

    outcome_close = registry.execute(_intent(Action.CLOSE_APP, "chrome"), dry_run=True, permissions=_ALL_ENABLED, release_test_mode=True)
    assert outcome_close.verification.status == VerificationStatus.DRY_RUN


def test_security_zero_dangerous_execution_tokens_in_codebase():
    """Verify zero shell=True, os.system, eval(, or exec( anywhere in friday/ or main.py."""
    root = Path(__file__).parent.parent
    forbidden = ["shell=True", "os.system", "eval(", "exec("]

    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True) + [str(root / "main.py")]

    for py_path in py_files:
        with open(py_path, "r", encoding="utf-8") as f:
            src = f.read()
        for tok in forbidden:
            assert tok not in src, f"Forbidden security token {tok!r} found in {py_path}"


def test_security_config_defaults_are_safe():
    """config.yaml defaults MUST remain dry_run: true and allow_real_execution: false."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    tools = cfg.get("tools", {})
    assert tools.get("dry_run", True) is True, "dry_run MUST default to True in config.yaml"
    assert tools.get("allow_real_execution", False) is False, "allow_real_execution MUST default to False in config.yaml"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
