"""
UNIT TEST — Configuration Validation Subsystem
===============================================
Tests friday/utils/config_validator.py in isolation.
No Ollama. No OS execution.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.utils.config_validator import validate_config, VALID_PERMISSION_KEYS


def test_valid_config_passes():
    """Valid configuration passes without modification or warnings."""
    cfg = {
        "tools": {
            "dry_run": True,
            "allow_real_execution": False,
            "permissions": {"open_app": True, "close_app": True},
        },
        "reasoning": {
            "endpoint": "http://localhost:11434/api/generate",
            "model": "llama3:latest",
        },
    }
    is_valid, sanitized, msgs = validate_config(cfg)
    assert is_valid is True
    assert sanitized["tools"]["dry_run"] is True
    assert sanitized["tools"]["allow_real_execution"] is False
    assert sanitized["tools"]["permissions"]["open_app"] is True
    assert len(msgs) == 0


def test_invalid_dry_run_type_fails_closed_to_true():
    """Non-boolean dry_run (e.g. 'false' string or int 1) must fail closed to True."""
    cfg = {"tools": {"dry_run": "false", "allow_real_execution": False}}
    is_valid, sanitized, msgs = validate_config(cfg)
    assert sanitized["tools"]["dry_run"] is True
    assert any("dry_run" in m for m in msgs)

    cfg_int = {"tools": {"dry_run": 0}}
    is_valid, sanitized, msgs = validate_config(cfg_int)
    assert sanitized["tools"]["dry_run"] is True


def test_invalid_allow_real_type_fails_closed_to_false():
    """Non-boolean allow_real_execution (e.g. 'true' string or int 1) must fail closed to False."""
    cfg = {"tools": {"dry_run": False, "allow_real_execution": "true"}}
    is_valid, sanitized, msgs = validate_config(cfg)
    assert sanitized["tools"]["allow_real_execution"] is False
    assert any("allow_real_execution" in m for m in msgs)


def test_unknown_permission_keys_ignored():
    """Unknown permission keys (e.g. delete_files) must be rejected/ignored."""
    cfg = {
        "tools": {
            "permissions": {
                "open_app": True,
                "delete_files": True,  # Unknown!
                "run_cmd": True,        # Unknown!
            }
        }
    }
    is_valid, sanitized, msgs = validate_config(cfg)
    perms = sanitized["tools"]["permissions"]
    assert "delete_files" not in perms
    assert "run_cmd" not in perms
    assert perms["open_app"] is True


def test_invalid_permission_value_fails_closed_to_false():
    """Non-boolean permission value (e.g. 'yes') must fail closed to False."""
    cfg = {"tools": {"permissions": {"open_app": "yes"}}}
    is_valid, sanitized, msgs = validate_config(cfg)
    assert sanitized["tools"]["permissions"]["open_app"] is False
    assert any("open_app" in m for m in msgs)


def test_empty_config_populates_safe_defaults():
    """Empty or None config dict initializes safe defaults."""
    is_valid, sanitized, msgs = validate_config({})
    assert sanitized["tools"]["dry_run"] is True
    assert sanitized["tools"]["allow_real_execution"] is False
    assert set(sanitized["tools"]["permissions"].keys()) == VALID_PERMISSION_KEYS


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
