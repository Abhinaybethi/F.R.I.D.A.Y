"""
Voice / Text Runtime Architecture Tests (STEP 9 of the voice-unification task).

Proves that voice mode (Friday.run -> listen -> _handle) and text mode
(Friday.run_text -> input -> _process_transcript) both execute the SAME single
pipeline: _process_transcript -> ConversationManager.handle_transcript ->
router -> deterministic tool OR configured reasoner -> response string.

All tests are hermetic: microphone, STT, TTS, wake-word, reasoner, and the
llama.cpp server lifecycle are stubbed. No real tool execution occurs
(os.startfile / webbrowser.open are patched).
"""
import os
import sys
from pathlib import Path

import pytest
import psutil

import friday.core.assistant as assistant_mod
from friday.voice.session_manager import _NO_SPEECH

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class RecordingReasoner:
    """Replaces the real Bonsai/Ollama reasoner; records every request."""
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "test-model")
        self.base_url = kwargs.get("base_url", "http://test:1")
        self.endpoint = kwargs.get("endpoint", "http://test:1")
        self.timeout = kwargs.get("timeout", 30)
        self.requests = []

    def is_available(self):
        return True

    def health(self):
        return "test reasoner reachable"

    def close(self):
        pass

    def request(self, transcript, context, mode="action"):
        self.requests.append(transcript)
        return {
            "type": "response",
            "text": f"You asked about: {transcript}",
            "confidence": 0.9,
        }


class FakeServerManager:
    """Replaces LlamaCppServerManager; no real subprocess."""
    def __init__(self, **kwargs):
        self.start_calls = 0
        self.stop_calls = 0
        self.owned_flag = False

    def mark_owned(self):
        self.owned_flag = True

    def is_owned(self):
        return self.owned_flag

    def start(self):
        self.start_calls += 1
        return True

    def stop(self):
        self.stop_calls += 1

    def health(self):
        return "test"

    def is_already_running(self):
        return False


class StubTTS:
    def __init__(self, **kwargs):
        self.spoken = []
        self.stopped = False
        self._is_speaking = False
        self.abort_event = None

    def warmup(self):
        pass

    def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        self.stopped = True
        self._is_speaking = False

    def is_speaking(self):
        return self._is_speaking


class StubSessionManager:
    """Replaces VoiceSessionManager; plays back a scripted transcript list."""
    def __init__(self, **kwargs):
        self.transcripts = []
        self.started = False
        self.stopped = False

    def set_script(self, transcripts):
        self.transcripts = list(transcripts)

    def start_session(self):
        self.started = True
        return self

    def stop_session(self):
        self.stopped = True

    def __enter__(self):
        return self.start_session()

    def __exit__(self, *args):
        self.stop_session()
        return False

    def listen_once(self):
        if not self.transcripts:
            return ""
        return self.transcripts.pop(0)


class StubWakeWord:
    def __init__(self, session, wake_word="friday"):
        self.session = session
        self.wake_word = wake_word

    def wait_for_wake_word(self):
        return self.session.listen_once()


class Recorder:
    """Wraps a bound method and records every call (for duplicate checks)."""
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        return self.fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _install_stubs(monkeypatch):
    monkeypatch.setattr(assistant_mod, "TextToSpeech", StubTTS)
    monkeypatch.setattr(assistant_mod, "VoiceSessionManager", StubSessionManager)
    monkeypatch.setattr(assistant_mod, "WakeWordListener", StubWakeWord)
    monkeypatch.setattr(assistant_mod, "LlamaCppReasoner", RecordingReasoner)
    monkeypatch.setattr(assistant_mod, "LlamaCppServerManager", FakeServerManager)

    monkeypatch.setattr("friday.tools.apps.os.startfile", lambda *a, **k: None)
    monkeypatch.setattr("friday.tools.browser.webbrowser.open", lambda *a, **k: True)


class _FakeProc:
    def __init__(self, name):
        self.info = {"name": name}


@pytest.fixture()
def chrome_running(monkeypatch):
    """Make OPEN_APP verification succeed by faking a running chrome.exe."""
    monkeypatch.setattr(
        psutil, "process_iter",
        lambda *a, **k: iter([_FakeProc("chrome.exe")]),
    )


@pytest.fixture()
def friday_factory(monkeypatch):
    """Constructs a stub-backed Friday and hands back the useful handles."""
    def factory(text_mode=False, transcripts=None, owned_server=False):
        friday = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"), text_mode=text_mode)
        # Point conversation manager at the recording reasoner too (Friday holds
        # its own reference, but ConversationManager keeps its own copy).
        reasoner = RecordingReasoner()
        friday.reasoner = reasoner
        friday.conversation_manager.reasoner = reasoner

        if not text_mode:
            friday.session_manager.set_script(transcripts or [])
            if owned_server:
                friday.server_manager.mark_owned()

        spy = Recorder(friday.conversation_manager.handle_transcript)
        friday.conversation_manager.handle_transcript = spy
        return friday, reasoner, friday.session_manager, friday.tts, spy

    return factory


# ---------------------------------------------------------------------------
# STEP 2 & 9.1 â€” same Assistant pipeline in both modes
# ---------------------------------------------------------------------------

def test_text_and_voice_share_the_same_pipeline(friday_factory):
    voice_friday, v_reasoner, v_session, v_tts, v_spy = friday_factory(
        text_mode=False, transcripts=["hi", "goodbye"]
    )
    text_friday, t_reasoner, t_session, t_tts, t_spy = friday_factory(text_mode=True)

    v_resp, v_keep = voice_friday._process_transcript("hi")
    t_resp, t_keep = text_friday._process_transcript("hi")

    assert v_resp == t_resp == "Hello! How can I assist you today?"
    assert v_keep == t_keep is True
    # Both modes funnelled through the exact same ConversationManager entry point.
    assert [c[0] for c in v_spy.calls] == ["hi"]
    assert [c[0] for c in t_spy.calls] == ["hi"]
    # Text mode did not instantiate any voice stack.
    assert text_friday.text_mode is True
    assert text_friday.session_manager is None
    assert text_friday.tts is None


def test_voice_run_end_to_end_reaches_conversation_manager(friday_factory, chrome_running):
    friday, reasoner, session, tts, spy = friday_factory(
        transcripts=["hi", "open chrome", "goodbye"]
    )
    friday.run()

    assert [c[0] for c in spy.calls] == ["hi", "open chrome", "goodbye"], (
        "Voice transcripts must reach ConversationManager exactly once each"
    )
    assert tts.spoken[0] == "Friday online. Listening..."
    assert any("Hello!" in s for s in tts.spoken)
    assert any("Chrome" in s for s in tts.spoken)
    assert session.started and session.stopped


# ---------------------------------------------------------------------------
# STEP 9.3 / 9.4 â€” reasoning vs deterministic through the voice path
# ---------------------------------------------------------------------------

def test_voice_ambiguous_query_invokes_configured_reasoner(friday_factory):
    friday, reasoner, session, tts, spy = friday_factory(
        transcripts=["what is the difference between python and java", "goodbye"]
    )
    friday.run()

    assert reasoner.requests == ["what is the difference between python and java"]
    assert any("You asked about" in s for s in tts.spoken)


def test_voice_deterministic_command_bypasses_reasoner(friday_factory, chrome_running):
    friday, reasoner, session, tts, spy = friday_factory(
        transcripts=["open chrome", "goodbye"]
    )
    friday.run()

    assert reasoner.requests == [], "Deterministic voice command must not hit the reasoner"
    assert any("Chrome" in s for s in tts.spoken)
    assert any("Hello!" in s for s in tts.spoken) is False


# ---------------------------------------------------------------------------
# STEP 9.5 â€” response reaches TTS; 9.6 â€” no duplicate processing
# ---------------------------------------------------------------------------

def test_voice_response_reaches_tts(friday_factory):
    friday, reasoner, session, tts, spy = friday_factory(
        transcripts=["hi", "goodbye"]
    )
    friday.run()

    assert any("Hello! How can I assist you today?" in s for s in tts.spoken)


def test_no_duplicate_voice_session_processing(friday_factory, chrome_running):
    transcripts = ["hi", "open chrome", "open youtube", "goodbye"]
    friday, reasoner, session, tts, spy = friday_factory(transcripts=transcripts)
    friday.run()

    assert [c[0] for c in spy.calls] == transcripts, (
        "Each transcript must be handled exactly once â€” nothing double-processed"
    )
    assert session.transcripts == [], "Script must be fully consumed"


# ---------------------------------------------------------------------------
# STEP 8 â€” no-legible-speech and empty transcripts never reach the pipeline
# ---------------------------------------------------------------------------

def test_no_clear_speech_and_empty_transcripts_ignored(friday_factory):
    friday, reasoner, session, tts, spy = friday_factory(
        transcripts=["", "No clear speech detected.", "hi", "goodbye"]
    )
    friday.run()

    assert [c[0] for c in spy.calls] == ["hi", "goodbye"], (
        "Empty and _NO_SPEECH transcripts must be ignored (not sent to the reasoner)"
    )
    assert len(reasoner.requests) == 0


# ---------------------------------------------------------------------------
# STEP 3 / 9.7 â€” shutdown: idempotent, ownership-aware, stops TTS + session
# ---------------------------------------------------------------------------

def test_shutdown_is_ownership_aware(friday_factory):
    owned_friday, _, owned_session, owned_tts, _ = friday_factory(
        text_mode=False, transcripts=[], owned_server=True
    )
    owned_friday.shutdown()
    assert owned_friday.server_manager.stop_calls == 1
    owned_friday.shutdown()
    assert owned_friday.server_manager.stop_calls == 1, "shutdown() must be idempotent"
    assert owned_tts.stopped is True
    assert owned_session.stopped is True

    external_friday, _, ext_session, ext_tts, _ = friday_factory(
        text_mode=False, transcripts=[], owned_server=False
    )
    external_friday.shutdown()
    assert external_friday.server_manager.stop_calls == 0, (
        "Never stop a llama.cpp server not started by F.R.I.D.A.Y."
    )
    assert ext_tts.stopped is True
    assert ext_session.stopped is True


# ---------------------------------------------------------------------------
# STEP 3 / 9.8 â€” main startup auto-starts the server exactly once
# ---------------------------------------------------------------------------

def test_startup_autostarts_server_once(friday_factory, monkeypatch):
    monkeypatch.delenv("FRIDAY_SKIP_LLAMACPP_STARTUP", raising=False)
    friday, reasoner, session, tts, spy = friday_factory(text_mode=True)

    assert isinstance(friday.server_manager, FakeServerManager)
    assert friday.server_manager.start_calls == 1, "Server auto-start must fire exactly once"
    # A second instance must NOT reuse/duplicate the first manager's process.
    friday2 = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"), text_mode=True)
    assert friday2.server_manager is not friday.server_manager


# ---------------------------------------------------------------------------
# 9.9 â€” main.py always calls shutdown() on exit (voice + text)
# ---------------------------------------------------------------------------

def _replace_friday(monkeypatch):
    """Swap Friday for a spy at its definition site (main.py does a function-
    local `from friday.core.assistant import Friday`)."""
    fake = {}

    class FakeFriday:
        def __init__(self, **kwargs):
            fake["instance"] = self
            self._shutdown_called = False

        def run(self):
            pass

        def run_text(self):
            pass

        def shutdown(self):
            self._shutdown_called = True

    monkeypatch.setattr(assistant_mod, "Friday", FakeFriday)
    return fake


def test_main_calls_shutdown_on_voice_exit(monkeypatch):
    import main as main_mod

    fake = _replace_friday(monkeypatch)
    monkeypatch.setattr(main_mod, "print_user_startup", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py"])

    with pytest.raises(SystemExit):
        main_mod.main()

    assert fake["instance"]._shutdown_called is True, (
        "Voice mode must call assistant.shutdown() before exit"
    )


def test_main_calls_shutdown_on_text_exit(monkeypatch):
    import main as main_mod

    fake = _replace_friday(monkeypatch)
    monkeypatch.setattr(main_mod, "print_user_startup", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--text"])

    with pytest.raises(SystemExit):
        main_mod.main()

    assert fake["instance"]._shutdown_called is True, (
        "Text mode must call assistant.shutdown() before exit"
    )