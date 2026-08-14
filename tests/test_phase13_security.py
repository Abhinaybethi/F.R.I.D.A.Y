"""
UNIT TEST — Phase 13 Security Invariants Audit
===============================================
Audits safety gates, permission policy, fuzzy matching target constraints,
codebase safety invariants, and default config values.
No Ollama required. All deterministic.
"""
import sys
import os
import glob
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.router import route
from friday.intent.models import Action, Intent
from friday.safety.permissions import check_permission, PermissionResult

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def test_fuzzy_router_cannot_inject_unwhitelisted_commands():
    """Unrecognized targets (powershell, cmd.exe) have 0 target confidence or require confirmation."""
    malicious_transcripts = [
        "run powershell",
        "execute cmd.exe",
        "delete system32",
        "rm -rf /",
    ]
    for transcript in malicious_transcripts:
        intent = route(transcript)
        # Unrecognized targets have target_confidence == 0.0 or UNKNOWN action
        assert intent.target_confidence == 0.0 or intent.action == Action.UNKNOWN or intent.requires_confirmation is True


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
    assert tools.get("dry_run", True) is True
    assert tools.get("allow_real_execution", False) is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
