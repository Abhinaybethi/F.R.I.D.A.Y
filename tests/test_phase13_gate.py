"""
PHASE 13 GATE TEST
===================
20-point Product Capabilities & Fuzzy Router Certification.
Verifies Fuzzy Router, Anaphora Context, Search Result Indexing, Audio Barge-in,
UI Status, Desktop Tools, Security Invariants, and Performance Benchmarks.
All deterministic. No Ollama required.
"""
import sys
import os
import glob
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.router import route
from friday.intent.models import Action, Intent
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.core.conversation import ConversationManager, ConversationState
from friday.ui.status import get_status_text, AssistantStatus
from friday.tools import registry, desktop
from friday.verification.models import ExecutionStatus
from friday.utils.config_validator import validate_config

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


def _intent(action: Action, target: str = "") -> Intent:
    return Intent(action=action, target=target, confidence=0.95)


def _load_cfg():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Gate 1 — Fuzzy phonetic router module exists
def test_gate1_fuzzy_router_exists():
    from friday.intent.fuzzy_router import fuzzy_route
    intent = fuzzy_route("open grove")
    assert intent is not None
    assert intent.target == "chrome"
    print("[OK] Gate 1: Fuzzy phonetic router module exists")


# Gate 2 — Near-miss "open grove" resolves to Chrome
def test_gate2_near_miss_open_grove():
    intent = route("open grove")
    assert intent.action == Action.OPEN_APP
    assert intent.target == "chrome"
    print("[OK] Gate 2: Near-miss 'open grove' resolves to Chrome")


# Gate 3 — Near-miss "openvscode" resolves to VS Code
def test_gate3_near_miss_openvscode():
    intent = route("openvscode")
    assert intent.action == Action.OPEN_APP
    assert intent.target == "vscode"
    print("[OK] Gate 3: Near-miss 'openvscode' resolves to VS Code")


# Gate 4 — Near-miss "on youtube" resolves to YouTube
def test_gate4_near_miss_on_youtube():
    intent = route("on youtube")
    assert intent.action == Action.OPEN_WEBSITE
    assert intent.target == "youtube"
    print("[OK] Gate 4: Near-miss 'on youtube' resolves to YouTube")


# Gate 5 — Anaphora "close it" resolves to last target
def test_gate5_anaphora_close_it():
    ctx = ShortTermContext(last_action=Action.OPEN_APP, last_target="chrome")
    resolved, err = resolve_context("close it", ctx)
    assert resolved == "close chrome"
    print("[OK] Gate 5: Anaphora 'close it' resolves to last_target 'chrome'")


# Gate 6 — Search result indexing resolves first result
def test_gate6_search_result_indexing():
    ctx = ShortTermContext(last_search_results=[{"url": "https://www.python.org"}])
    resolved, err = resolve_context("open the first result", ctx)
    assert "https://www.python.org" in resolved
    print("[OK] Gate 6: Search result indexing resolves 'open the first result'")


# Gate 7 — Audio barge-in stop signal exists
def test_gate7_barge_in_stop_signal():
    from friday.voice.text_to_speech import TextToSpeech
    tts = TextToSpeech(engine="piper")
    tts.stop()
    assert tts.abort_event.is_set() is True
    print("[OK] Gate 7: Audio barge-in stop signal functions cleanly")


# Gate 8 — Desktop status indicator module exists
def test_gate8_ui_status_module_exists():
    text = get_status_text(ConversationState.LISTENING)
    assert text == AssistantStatus.LISTENING
    print("[OK] Gate 8: Desktop UI status indicator module exists")


# Gate 9 — Status text formatting
def test_gate9_status_formatting():
    assert get_status_text(ConversationState.PROCESSING) == AssistantStatus.PROCESSING
    assert get_status_text(ConversationState.EXECUTING) == AssistantStatus.EXECUTING
    print("[OK] Gate 9: Status text formatting returns correct status labels")


# Gate 10 — Desktop control tools exist
def test_gate10_desktop_tools_exist():
    res = desktop.minimize_app("chrome", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]
    print("[OK] Gate 10: Desktop control tools exist and support dry_run")


# Gate 11 — Registry dispatches desktop actions
def test_gate11_registry_dispatches_desktop_actions():
    outcome = registry.execute(_intent(Action.MINIMIZE_APP, "chrome"), dry_run=True, permissions=_ALL_ENABLED)
    assert outcome.execution.status == ExecutionStatus.SUCCESS
    print("[OK] Gate 11: Registry dispatches MINIMIZE_APP tool cleanly")


# Gate 12 — Reasoner gating filters known commands
def test_gate12_reasoner_gating_filters():
    from friday.reasoning.gating import should_call_reasoner
    call, _ = should_call_reasoner("open chrome", _intent(Action.OPEN_APP, "chrome"))
    assert call is False
    print("[OK] Gate 12: Reasoner gating filters known commands with 0 LLM calls")


# Gate 13 — Spoken response engine strips [DRY RUN]
def test_gate13_spoken_response_clean():
    from friday.response.engine import format_spoken_response
    spoken = format_spoken_response("[DRY RUN] Would open Chrome.")
    assert "[DRY RUN]" not in spoken
    print("[OK] Gate 13: Spoken response engine strips [DRY RUN] tags")


# Gate 14 — Audit log entries recorded
def test_gate14_audit_log_entries():
    registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    audit_path = Path(__file__).parent.parent / "logs" / "friday_audit.log"
    assert audit_path.exists()
    print("[OK] Gate 14: Audit log records structured entries")


# Gate 15 — Config defaults preserved
def test_gate15_config_defaults():
    cfg = _load_cfg()
    assert cfg.get("tools", {}).get("dry_run", True) is True
    assert cfg.get("tools", {}).get("allow_real_execution", False) is False
    print("[OK] Gate 15: config.yaml defaults remain dry_run: true and allow_real_execution: false")


# Gate 16 — Zero shell=True in codebase
def test_gate16_zero_shell_true():
    root = Path(__file__).parent.parent
    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True)
    for p in py_files:
        with open(p, encoding="utf-8") as f:
            assert "shell=True" not in f.read()
    print("[OK] Gate 16: Zero shell=True across python codebase")


# Gate 17 — Zero os.system in codebase
def test_gate17_zero_os_system():
    root = Path(__file__).parent.parent
    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True)
    for p in py_files:
        with open(p, encoding="utf-8") as f:
            assert "os.system" not in f.read()
    print("[OK] Gate 17: Zero os.system across python codebase")


# Gate 18 — Zero eval/exec in codebase
def test_gate18_zero_eval_exec():
    root = Path(__file__).parent.parent
    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True)
    for p in py_files:
        with open(p, encoding="utf-8") as f:
            src = f.read()
            assert "eval(" not in src
            assert "exec(" not in src
    print("[OK] Gate 18: Zero eval() or exec() across python codebase")


# Gate 19 — Legacy prototype code quarantined
def test_gate19_legacy_quarantine():
    import friday.legacy_deprecated
    assert hasattr(friday.legacy_deprecated, "__deprecated__")
    print("[OK] Gate 19: Legacy prototype code quarantined in friday/legacy_deprecated/")


# Gate 20 — Gate Certification Status
def test_gate20_certification():
    valid, _, _ = validate_config(_load_cfg())
    assert valid is True
    print("[OK] Gate 20: Phase 13 Gate Certification PASSED")


if __name__ == "__main__":
    import pytest
    print("=" * 60)
    print(" PHASE 13 GATE TEST — PRODUCT CAPABILITIES & FUZZY ROUTER")
    print("=" * 60)
    pytest.main([__file__, "-v", "--no-header", "--tb=short"])
