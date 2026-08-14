"""
F.R.I.D.A.Y. v1.0.0 Release Candidate Automated Smoke Test.

Non-destructive verification of all core subsystems.
"""
import sys
import os
import yaml
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday import __version__
from friday.utils.config_validator import validate_config
from friday.intent.router import route
from friday.tools import registry
from friday.intent.models import Action, Intent
from friday.core.conversation import ConversationManager, ConversationState
from friday.voice.text_to_speech import TextToSpeech

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "minimize_app": True,
    "maximize_app": True, "take_screenshot": True,
}


def run_release_smoke_test() -> bool:
    print("=" * 60)
    print(f" F.R.I.D.A.Y. v{__version__} RELEASE SMOKE TEST")
    print("=" * 60)

    # 1. Version Check
    assert __version__ == "1.0.0"
    print("  [OK] 1. Version check: v1.0.0")

    # 2. Config Validation
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    valid, _, _ = validate_config(cfg)
    assert valid is True
    print("  [OK] 2. Configuration validation: PASSED")

    # 3. Router & Registry
    intent = route("open chrome")
    assert intent.action == Action.OPEN_APP
    res = registry.execute(intent, dry_run=True, permissions=_ALL_ENABLED)
    assert res.is_success is True
    print("  [OK] 3. Router & Tool Registry: PASSED")

    # 4. Conversation Manager Lifecycle
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    cm.handle_transcript("what time is it")
    cm.stop_session()
    assert cm.state in (ConversationState.STOPPING, ConversationState.IDLE)
    print("  [OK] 4. Conversation Manager lifecycle: PASSED")

    # 5. TTS Engine
    tts = TextToSpeech(engine="piper")
    assert tts.piper is not None or tts.kokoro is not None
    print("  [OK] 5. TTS Engine initialization: PASSED")

    print("-" * 60)
    print(" ALL RELEASE SMOKE TESTS PASSED (100% READY)")
    print("=" * 60)
    return True


if __name__ == "__main__":
    ok = run_release_smoke_test()
    sys.exit(0 if ok else 1)
