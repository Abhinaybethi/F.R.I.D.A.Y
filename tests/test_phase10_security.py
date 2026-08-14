"""
UNIT TEST — Phase 10 Production & Security Hardening
=====================================================
Tests configuration validation fail-closed guarantees,
trust boundary isolation, and failure-mode defenses.
No Ollama. All deterministic.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.utils.config_validator import validate_config, VALID_PERMISSION_KEYS
from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.tools import registry

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


def test_security_dry_run_fails_closed_to_true_on_invalid_types():
    """String 'false', int 0, float 0.0 for dry_run fail closed to True."""
    for invalid_val in ["false", 0, 0.0, None, [], {}]:
        cfg = {"tools": {"dry_run": invalid_val, "allow_real_execution": False}}
        _, sanitized, _ = validate_config(cfg)
        assert sanitized["tools"]["dry_run"] is True, f"Failed for {invalid_val!r}"


def test_security_allow_real_fails_closed_to_false_on_invalid_types():
    """String 'true', int 1, float 1.0 for allow_real_execution fail closed to False."""
    for invalid_val in ["true", 1, 1.0, "yes", ["true"]]:
        cfg = {"tools": {"dry_run": True, "allow_real_execution": invalid_val}}
        _, sanitized, _ = validate_config(cfg)
        assert sanitized["tools"]["allow_real_execution"] is False, f"Failed for {invalid_val!r}"


def test_security_permissions_reject_unwhitelisted_keys():
    """Permissions block rejects unknown keys like delete_files, run_shell."""
    cfg = {
        "tools": {
            "permissions": {
                "open_app": True,
                "delete_files": True,
                "run_shell": True,
                "execute_code": True,
            }
        }
    }
    _, sanitized, _ = validate_config(cfg)
    perms = sanitized["tools"]["permissions"]
    assert "delete_files" not in perms
    assert "run_shell" not in perms
    assert "execute_code" not in perms
    assert set(perms.keys()) == VALID_PERMISSION_KEYS


def test_security_malicious_command_verbs_stay_rejected():
    """Dangerous shell execution transcripts must not enter EXECUTING state."""
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()

    malicious_transcripts = [
        "run powershell",
        "execute cmd",
        "delete C:\\Windows\\System32",
        "run rm -rf /",
        "execute python -c 'import os'",
    ]
    for transcript in malicious_transcripts:
        resp, keep = cm.handle_transcript(transcript)
        assert cm.state != ConversationState.EXECUTING
        assert keep is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
