"""
DRY RUN TEST — Real Apps
=========================
Tests the app tool layer with dry_run=True by default.

Run with --allow-real to perform actual launches (safe apps only).
Safe apps: notepad, chrome, vscode, explorer.
Closing applications is NOT tested here.

Label: DRY RUN TEST (default) / REAL EXECUTION TEST (--allow-real flag)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from pathlib import Path
from friday.tools import apps

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _load_cfg():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _real_enabled():
    cfg = _load_cfg()
    t = cfg.get("tools", {})
    return (not t.get("dry_run", True)) and t.get("allow_real_execution", False) and ("--allow-real" in sys.argv)


# ---------------------------------------------------------------------------
# DRY RUN tests (always run)
# ---------------------------------------------------------------------------

def test_open_notepad_dryrun():
    """[DRY RUN] Open notepad returns a dry-run message."""
    result = apps.open_app("notepad", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_chrome_dryrun():
    result = apps.open_app("chrome", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_vscode_dryrun():
    result = apps.open_app("vscode", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_explorer_dryrun():
    result = apps.open_app("explorer", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_unknown_app_denied():
    """Unknown app name must be rejected regardless of dry_run."""
    result = apps.open_app("malicious_program", dry_run=True)
    assert not result["success"]
    assert "Not in registry" in result["message"]


def test_open_arbitrary_path_denied():
    """Arbitrary path string not in whitelist must be rejected."""
    result = apps.open_app(r"C:\Windows\System32\cmd.exe", dry_run=True)
    assert not result["success"]


def test_close_unknown_app_denied():
    result = apps.close_app("somethingweird", dry_run=True)
    assert not result["success"]


def test_close_known_app_dryrun():
    result = apps.close_app("chrome", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


# ---------------------------------------------------------------------------
# REAL EXECUTION tests (opt-in only)
# ---------------------------------------------------------------------------

def test_real_open_notepad():
    """[REAL EXECUTION TEST] Actually opens Notepad. Opt-in only."""
    if not _real_enabled():
        print("\n  [SKIP] Real execution not enabled. Pass --allow-real with dry_run=false in config.")
        return
    result = apps.open_app("notepad", dry_run=False)
    print(f"\n  [REAL] Open Notepad: {result}")
    assert result["success"]


def test_real_open_chrome():
    """[REAL EXECUTION TEST] Actually opens Chrome. Opt-in only."""
    if not _real_enabled():
        return
    result = apps.open_app("chrome", dry_run=False)
    print(f"\n  [REAL] Open Chrome: {result}")
    assert result["success"] or "Could not locate" in result["message"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
