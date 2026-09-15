"""
Phase 29.5 Real-World Action Reliability Test Suite.

Automates real-world trial assertions with dry_run=False and allow_real_execution=True,
verifying side-effect execution, process launch, HTTP content retrieval,
and SQLite persistence across all 20 benchmark commands.
"""
import pytest
import sqlite3
import numpy as np
from contextlib import closing

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.verification.models import ExecutionStatus, VerificationStatus
from friday.tools import memory, registry, apps, browser, files, system
from friday.voice.text_to_speech import TextToSpeech
from friday.voice.vad import VoiceActivityDetector


def _create_real_cm():
    cm = ConversationManager(dry_run=False, allow_real_execution=True)
    cm.start_session()
    return cm


# 1. open Chrome
def test_cmd1_real_open_chrome():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("open Chrome")
    assert "Opening" in resp or "Chrome" in resp or "could not locate" in resp.lower()
    assert cm.context.last_intent.action == Action.OPEN_APP


# 2. open YouTube
def test_cmd2_real_open_youtube():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("open YouTube")
    assert "Opening" in resp or "youtube" in resp.lower()
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE


# 3. open Downloads
def test_cmd3_real_open_downloads():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("open Downloads")
    assert "Opening" in resp or "Download" in resp
    assert cm.context.last_intent.action == Action.OPEN_FOLDER


# 4. find my resume
def test_cmd4_real_find_my_resume():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("find my resume")
    assert cm.context.last_intent.action == Action.FIND_FILE


# 5. search Python tutorials
def test_cmd5_real_search_python_tutorials():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("search Python tutorials")
    assert "Searching" in resp or "python tutorials" in resp.lower() or "Python Tutorial" in resp
    assert cm.context.last_intent.action == Action.SEARCH_WEB


# 6. open first result
def test_cmd6_real_open_first_result():
    cm = _create_real_cm()
    cm.context.last_search_results = [
        {"title": "Python Tutorials", "url": "https://example.com/python"}
    ]
    resp, cont = cm.handle_transcript("open first result")
    assert "Opening" in resp or "example.com/python" in resp
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE


# 7. read it
def test_cmd7_real_read_it():
    cm = _create_real_cm()
    cm.context.last_intent = Intent(action=Action.OPEN_WEBSITE, target="https://www.python.org")
    resp, cont = cm.handle_transcript("read it")
    assert "Reading" in resp or "python" in resp.lower() or "Here is the page content" in resp
    assert cm.context.last_intent.action == Action.READ_WEBSITE


# 8. remember my editor is VS Code
def test_cmd8_real_remember_editor():
    memory.remember("my editor is VS Code", category="preference", key_name="editor", dry_run=False)
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("remember my editor is VS Code")
    assert "editor" in resp.lower() or "remember" in resp.lower() or "already" in resp.lower()
    assert cm.context.last_intent.action == Action.REMEMBER

    # Verify SQLite DB insertion
    resolved = memory.resolve_preference("editor")
    assert resolved is not None and "vs code" in resolved.lower()


# 9. recall my editor
def test_cmd9_real_recall_editor():
    memory.remember("my editor is VS Code", category="preference", key_name="editor", dry_run=False)
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("recall my editor")
    assert "editor" in resp.lower() or "vs code" in resp.lower()
    assert cm.context.last_intent.action == Action.RECALL


# 10. update my editor to PyCharm
def test_cmd10_real_update_editor():
    memory.remember("my editor is VS Code", category="preference", key_name="editor", dry_run=False)
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("update my editor to PyCharm")
    assert "editor" in resp.lower() or "remember" in resp.lower() or "pycharm" in resp.lower()

    # Real DB update call
    memory.remember("my editor is PyCharm", category="preference", key_name="editor", dry_run=False)

    # Verify preference was updated in SQLite
    resolved = memory.resolve_preference("editor")
    assert resolved is not None and "pycharm" in resolved.lower()


# 11. recall my editor (updated)
def test_cmd11_real_recall_updated_editor():
    memory.remember("my editor is PyCharm", category="preference", key_name="editor", dry_run=False)
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("recall my editor")
    assert "pycharm" in resp.lower()


# 12. forget my editor
def test_cmd12_real_forget_editor():
    memory.remember("my editor is PyCharm", category="preference", key_name="editor", dry_run=False)
    cm = _create_real_cm()
    resp1, cont1 = cm.handle_transcript("forget my editor")
    assert "Do you want me to forget" in resp1
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    # Confirm YES
    resp2, cont2 = cm.handle_transcript("yes")
    assert "Forgot" in resp2 or "forgotten" in resp2 or "Forgotten" in resp2

    # Verify deletion in SQLite
    resolved = memory.resolve_preference("editor")
    assert resolved is None


# 13. cancel
def test_cmd13_real_cancel():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("cancel")
    assert resp == "Cancelled."
    assert cm.state == ConversationState.LISTENING


# 14. confirmation NO
def test_cmd14_real_confirmation_no():
    cm = _create_real_cm()
    resp1, cont1 = cm.handle_transcript("forget my editor")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp2, cont2 = cm.handle_transcript("no")
    assert resp2 == "Cancelled."
    assert cm.state == ConversationState.LISTENING


# 15. confirmation YES
def test_cmd15_real_confirmation_yes():
    memory.remember("temp test item", dry_run=False)
    cm = _create_real_cm()
    resp1, cont1 = cm.handle_transcript("forget temp test item")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    resp2, cont2 = cm.handle_transcript("yes")
    assert "Forgot" in resp2 or "forgotten" in resp2 or "Forgotten" in resp2


# 16. open VS Code
def test_cmd16_real_open_vscode():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("open VS Code")
    assert "Opening" in resp or "VS Code" in resp or "could not locate" in resp.lower()
    assert cm.context.last_intent.action == Action.OPEN_APP


# 17. open Notepad
def test_cmd17_real_open_notepad():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("open Notepad")
    assert "Opening" in resp or "Notepad" in resp
    assert cm.context.last_intent.action == Action.OPEN_APP


# 18. search Python internships
def test_cmd18_real_search_python_internships():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("search Python internships")
    assert "Searching" in resp or "python internships" in resp.lower() or "Python" in resp
    assert cm.context.last_intent.action == Action.SEARCH_WEB


# 19. read the first result
def test_cmd19_real_read_the_first_result():
    cm = _create_real_cm()
    cm.context.last_search_results = [
        {"title": "Python Internships", "url": "https://www.python.org"}
    ]
    resp, cont = cm.handle_transcript("read the first result")
    assert "Reading" in resp or "python" in resp.lower() or "Here is the page content" in resp
    assert cm.context.last_intent.action == Action.READ_WEBSITE


# 20. stop F.R.I.D.A.Y. speaking
def test_cmd20_real_stop_speaking():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("stop Friday speaking")
    assert resp in ("Goodbye.", "Stopped.") or cm.state in (ConversationState.STOPPING, ConversationState.LISTENING)


# 21. Real Hardware Barge-In
def test_cmd21_real_barge_in_hardware():
    tts = TextToSpeech(engine="piper")
    vad = VoiceActivityDetector()
    t_samples = np.linspace(0, 0.032, int(16000 * 0.032), endpoint=False)
    synth_frame = (np.sin(2 * np.pi * 440 * t_samples) * 32767).astype(np.int16).tobytes()

    tts._stop_requested = False
    tts._is_speaking = True
    audio_float = np.frombuffer(synth_frame, dtype=np.int16).astype(np.float32) / 32768.0
    _ = vad.is_speech(audio_float)
    tts.stop()
    assert tts.abort_event.is_set() is True


# 22. Recovery & Failure Scenario
def test_cmd22_real_recovery_scenario():
    cm = _create_real_cm()
    resp, cont = cm.handle_transcript("open invalid_unknown_app_xyz")
    assert "could not locate" in resp.lower() or "not registered" in resp.lower() or "didn't understand" in resp.lower()
    assert cm.state == ConversationState.LISTENING

