"""
UNIT TEST — Phase 16 Security & Performance Audit (P0)
======================================================
Audits trust boundaries, security invariants, config defaults, and zero dangerous tokens.
"""
import sys
import os
import glob
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def test_security_zero_dangerous_tokens():
    """Verify zero shell=True, os.system, eval(, or exec( in friday/ or main.py."""
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
