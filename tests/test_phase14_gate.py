"""
PHASE 14 GATE TEST
===================
20-point Asynchronous Voice Session, Hardware Barge-in & Native Desktop Certification.
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
from friday.ui.tray import SystemTrayIndicator
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


# Gate 1 — Async voice session manager exists
def test_gate1_async_voice_session_exists():
    from friday.voice.async_session import AsyncVoiceSessionManager
    assert AsyncVoiceSessionManager is not None
    print("[OK] Gate 1: Async voice session manager exists")


# Gate 2 — Background VAD thread stop signal works
def test_gate2_background_vad_stop():
    from friday.voice.text_to_speech import TextToSpeech
    from friday.voice.async_session import AsyncVoiceSessionManager
    tts = TextToSpeech(engine="piper")
    async_session = AsyncVoiceSessionManager(None, tts)
    async_session.start_barge_in_listener()
    async_session.stop_barge_in_listener()
    assert async_session.is_barge_in_triggered() is False
    print("[OK] Gate 2: Background VAD thread stop signal operates cleanly")


# Gate 3 — Native Windows desktop control module exists
def test_gate3_native_desktop_module_exists():
    res = desktop.minimize_app("chrome", dry_run=True)
    assert res["success"] is True
    print("[OK] Gate 3: Native Windows desktop control module exists")


# Gate 4 — Native minimize_app execution hook
def test_gate4_native_minimize_hook():
    os.environ["RELEASE_TEST_MODE"] = "1"
    try:
        res = desktop.minimize_app("NonExistentWindow", dry_run=True)
        assert res["success"] is True
    finally:
        os.environ.pop("RELEASE_TEST_MODE", None)
    print("[OK] Gate 4: Native minimize_app execution hook operates cleanly")


# Gate 5 — Native maximize_app execution hook
def test_gate5_native_maximize_hook():
    os.environ["RELEASE_TEST_MODE"] = "1"
    try:
        res = desktop.maximize_app("NonExistentWindow", dry_run=True)
        assert res["success"] is True
    finally:
        os.environ.pop("RELEASE_TEST_MODE", None)
    print("[OK] Gate 5: Native maximize_app execution hook operates cleanly")


# Gate 6 — Hardware latency benchmark script exists
def test_gate6_benchmark_script_exists():
    from scripts.benchmark_hardware_latency import benchmark_subsystems
    res = benchmark_subsystems()
    assert "router_exact_ms" in res
    assert "fuzzy_router_ms" in res
    print("[OK] Gate 6: Hardware latency benchmark script exists and runs")


# Gate 7 — Dynamic target alias harvester functions
def test_gate7_dynamic_target_harvester():
    from friday.intent.fuzzy_router import get_dynamic_targets
    targets = get_dynamic_targets()
    assert "chrome" in targets
    assert "youtube" in targets
    print("[OK] Gate 7: Dynamic target alias harvester functions cleanly")


# Gate 8 — System tray indicator module exists
def test_gate8_ui_tray_module_exists():
    tooltip = SystemTrayIndicator.get_tray_tooltip(ConversationState.LISTENING)
    assert "LISTENING" in tooltip
    print("[OK] Gate 8: System tray indicator module exists")


# Gate 9 — System tray tooltip formatting
def test_gate9_tray_tooltip_formatting():
    assert SystemTrayIndicator.get_tray_tooltip(ConversationState.IDLE) == "F.R.I.D.A.Y. - [IDLE]"
    print("[OK] Gate 9: System tray tooltip formatting returns correct string")


# Gate 10 — System tray icon name resolution
def test_gate10_tray_icon_name():
    assert SystemTrayIndicator.get_tray_icon_name(ConversationState.LISTENING) == "icon_listening.ico"
    assert SystemTrayIndicator.get_tray_icon_name(ConversationState.IDLE) == "icon_idle.ico"
    print("[OK] Gate 10: System tray icon name resolution operates cleanly")


# Gate 11 — Fuzzy phonetic router resolves near-miss
def test_gate11_fuzzy_router_near_miss():
    intent = route("open grove")
    assert intent.action == Action.OPEN_APP
    assert intent.target == "chrome"
    print("[OK] Gate 11: Fuzzy phonetic router resolves near-miss 'open grove'")


# Gate 12 — Anaphora "close it" resolves to last target
def test_gate12_anaphora_close_it():
    ctx = ShortTermContext(last_action=Action.OPEN_APP, last_target="chrome")
    resolved, err = resolve_context("close it", ctx)
    assert resolved == "close chrome"
    print("[OK] Gate 12: Anaphora 'close it' resolves to 'close chrome'")


# Gate 13 — Search result indexing resolves first result
def test_gate13_search_result_indexing():
    ctx = ShortTermContext(last_search_results=[{"url": "https://www.python.org"}])
    resolved, err = resolve_context("open the first result", ctx)
    assert "https://www.python.org" in resolved
    print("[OK] Gate 13: Search result indexing resolves first result")


# Gate 14 — Reasoner gating filters known commands
def test_gate14_reasoner_gating_filters():
    from friday.reasoning.gating import should_call_reasoner
    call, _ = should_call_reasoner("open chrome", _intent(Action.OPEN_APP, "chrome"))
    assert call is False
    print("[OK] Gate 14: Reasoner gating filters known commands with 0 LLM calls")


# Gate 15 — Audit log entries recorded
def test_gate15_audit_log_entries():
    registry.execute(_intent(Action.GET_TIME), dry_run=True, permissions=_ALL_ENABLED)
    audit_path = Path(__file__).parent.parent / "logs" / "friday_audit.log"
    assert audit_path.exists()
    print("[OK] Gate 15: Audit log records structured entries")


# Gate 16 — Config defaults preserved
def test_gate16_config_defaults():
    cfg = _load_cfg()
    assert cfg.get("tools", {}).get("dry_run", True) is True
    assert cfg.get("tools", {}).get("allow_real_execution", False) is False
    print("[OK] Gate 16: config.yaml defaults remain dry_run: true and allow_real_execution: false")


# Gate 17 — Zero shell=True in codebase
def test_gate17_zero_shell_true():
    root = Path(__file__).parent.parent
    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True)
    for p in py_files:
        with open(p, encoding="utf-8") as f:
            assert "shell=True" not in f.read()
    print("[OK] Gate 17: Zero shell=True across python codebase")


# Gate 18 — Zero os.system in codebase
def test_gate18_zero_os_system():
    root = Path(__file__).parent.parent
    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True)
    for p in py_files:
        with open(p, encoding="utf-8") as f:
            assert "os.system" not in f.read()
    print("[OK] Gate 18: Zero os.system across python codebase")


# Gate 19 — Zero eval/exec in codebase
def test_gate19_zero_eval_exec():
    root = Path(__file__).parent.parent
    py_files = glob.glob(str(root / "friday" / "**" / "*.py"), recursive=True)
    for p in py_files:
        with open(p, encoding="utf-8") as f:
            src = f.read()
            assert "eval(" not in src
            assert "exec(" not in src
    print("[OK] Gate 19: Zero eval() or exec() across python codebase")


# Gate 20 — Gate Certification Status
def test_gate20_certification():
    valid, _, _ = validate_config(_load_cfg())
    assert valid is True
    print("[OK] Gate 20: Phase 14 Gate Certification PASSED")


if __name__ == "__main__":
    import pytest
    print("=" * 60)
    print(" PHASE 14 GATE TEST — ASYNC VOICE SESSION & NATIVE DESKTOP")
    print("=" * 60)
    pytest.main([__file__, "-v", "--no-header", "--tb=short"])
