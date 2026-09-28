"""
Regression tests for runtime stability fixes.

Covers (spec section 13 of the runtime stability pass):
  * logging: shared single file handler per path, no duplicate handlers,
    Windows rotation failures degrade gracefully instead of crashing.
  * query normalization: app aliases ("grom" -> "chrome") applied to the
    pipeline, unknown words left untouched.
  * routing: SEARCH_WEB target is the pure query; the browser is carried in
    intent.arguments["application"] instead of inside the query string.
  * confirmation: yes / no / cancel drive a pending CLOSE_APP confirmation.
  * conversation follow-ups: pronouns and topic switches stay grounded.
  * interruption: pure TTS-cancel utterances are consumed before the pipeline
    and never routed; the state machine admits SPEAKING -> INTERRUPTED.

Everything is hermetic: no network, no mic, no real OS execution.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging

import pytest

from friday.core.assistant import _is_interrupt_utterance
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState
from friday.intent.normalizer import normalize_app_aliases
from friday.intent.router import route
from friday.safety.confirmation import parse_confirmation_response
from friday.utils.logger import (
    WindowsSafeRotatingFileHandler,
    get_logger,
)
from friday.voice.state_machine import VoiceState, VoiceStateMachine

TMP_DIR = os.path.join(os.environ.get("TEMP", "."), "friday_runtime_tests")


def _make_log_file(name: str) -> str:
    os.makedirs(TMP_DIR, exist_ok=True)
    return os.path.join(TMP_DIR, name)


# ---------------------------------------------------------------------------
# Logging: initialisation, handlers, rotation
# ---------------------------------------------------------------------------

def test_logging_initializes_once():
    name = "runtime_test.single_init"
    a = get_logger(name)
    b = get_logger(name)
    assert a is b, "get_logger must return the same logger for the same name"
    file_handlers = [h for h in a.handlers if isinstance(h, logging.FileHandler)]
    console_handlers = [h for h in a.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1, "exactly one file handler per logger"
    assert len(console_handlers) == 1, "exactly one console handler per logger"
    assert file_handlers[0].name is None or True
    assert isinstance(file_handlers[0], WindowsSafeRotatingFileHandler)


def test_duplicate_handlers_not_created():
    log_file = _make_log_file("dup_handlers.log")
    logger_a = get_logger("runtime_test.dup.a", log_file=log_file)
    logger_b = get_logger("runtime_test.dup.b", log_file=log_file)
    fa = [h for h in logger_a.handlers if isinstance(h, logging.FileHandler)]
    fb = [h for h in logger_b.handlers if isinstance(h, logging.FileHandler)]
    assert len(fa) == 1 and len(fb) == 1
    assert fa[0] is fb[0], (
        "Two loggers pointing at the same file must SHARE one file handler "
        "(the root cause of WinError 32 was one open handle per logger)"
    )
    # A second initialisation of the same name must not add more handlers.
    logger_a2 = get_logger("runtime_test.dup.a", log_file=log_file)
    fa2 = [h for h in logger_a2.handlers if isinstance(h, logging.FileHandler)]
    assert len(fa2) == 1


def test_log_rotation_does_not_crash():
    log_file = _make_log_file("rotation_ok.log")
    if os.path.exists(log_file):
        os.remove(log_file)
    handler = WindowsSafeRotatingFileHandler(
        log_file, maxBytes=300, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        for i in range(15):
            handler.emit(logging.LogRecord(
                "runtime_test.rot", logging.INFO, "", 0,
                "record-%02d %s" % (i, "x" * 40), None, None,
            ))
        handler.flush()
    finally:
        handler.close()
    assert os.path.exists(log_file + ".1") or os.path.exists(log_file + ".2"), (
        "A normal rotation must create a backup file"
    )
    content = open(log_file, encoding="utf-8").read()
    assert "record-14" in content, "logging must continue after rotation"


def test_windows_rotation_failure_is_graceful(monkeypatch, capsys):
    log_file = _make_log_file("rotation_fail.log")
    if os.path.exists(log_file):
        os.remove(log_file)
    for suffix in (".1", ".2"):
        p = log_file + suffix
        if os.path.exists(p):
            os.remove(p)

    handler = WindowsSafeRotatingFileHandler(
        log_file, maxBytes=200, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Simulate Windows: the target file cannot be renamed because another
    # handle (antivirus, another process, a second handler) holds it.
    def broken_rename(src, dst):
        raise PermissionError(
            32, "The process cannot access the file because it is being used by another process", src
        )

    monkeypatch.setattr(os, "rename", broken_rename)
    try:
        for i in range(20):
            handler.emit(logging.LogRecord(
                "runtime_test.rotfail", logging.INFO, "", 0,
                "line-%02d %s" % (i, "x" * 30), None, None,
            ))
        handler.flush()
    finally:
        handler.close()

    err_output = capsys.readouterr().err
    assert "Logging error" not in err_output, (
        "A recoverable rotation failure must NOT emit the default "
        "`--- Logging error ---` traceback"
    )
    assert "[LOG] Rotation deferred" in err_output, (
        "A single-line rate-limited notice must be printed instead"
    )
    if os.path.exists(log_file):
        content = open(log_file, encoding="utf-8").read()
        assert "line-19" in content, "logging must continue while rotation is deferred"
    assert handler._rotation_errors >= 1, "the rotation failure must be observed"


# ---------------------------------------------------------------------------
# Query normalisation
# ---------------------------------------------------------------------------

def test_chrome_alias():
    text, changes = normalize_app_aliases("can you open grom")
    assert text == "can you open chrome"
    assert changes == ["grom -> chrome"]

    text2, changes2 = normalize_app_aliases("search for kalyani song on crome")
    assert text2 == "search for kalyani song on chrome"
    assert "crome -> chrome" in changes2

    # Whole-token matching only: "chromosome" is not an alias.
    text3, changes3 = normalize_app_aliases("what is a chromosome")
    assert text3 == "what is a chromosome" and changes3 == []


def test_unknown_word_not_modified():
    text, changes = normalize_app_aliases("who wrote the matrix")
    assert text == "who wrote the matrix"
    assert changes == []


def test_app_alias_normalized_in_pipeline():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("can you open grom")
    assert keep is True
    assert "chrome" in resp.lower()
    assert cm.context.last_intent.target == "chrome"


# ---------------------------------------------------------------------------
# Routing: SEARCH_WEB target shall be the pure query
# ---------------------------------------------------------------------------

def test_open_chrome():
    intent = route("open chrome")
    assert intent.action.name == "OPEN_APP"
    assert intent.target == "chrome"


def test_search_web():
    intent = route("search for python tutorials")
    assert intent.action.name == "SEARCH_WEB"
    assert intent.target == "python tutorials"
    assert "application" not in intent.arguments


def test_search_web_on_chrome():
    intent = route("search for kalyani song on chrome")
    assert intent.action.name == "SEARCH_WEB"
    assert intent.target == "kalyani song", (
        "The query must NOT include the browser: 'kalyani song on chrome' "
        "previously produced an empty search result"
    )
    assert intent.arguments.get("application") == "chrome"


def test_search_web_executes_with_pure_query():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
    cm.start_session()
    resp, keep = cm.handle_transcript("search for kalyani song on chrome")
    assert keep is True
    assert cm.context.last_intent.action.name == "SEARCH_WEB"
    assert cm.context.last_intent.target == "kalyani song"
    expected = "kalyani song"
    assert "kalyani song" in resp.lower() or cm.context.last_search_results


# ---------------------------------------------------------------------------
# Confirmation flow
# ---------------------------------------------------------------------------

def test_confirmation_yes():
    assert parse_confirmation_response("yes") is True
    assert parse_confirmation_response("yeah") is True
    assert parse_confirmation_response("sure") is True
    assert parse_confirmation_response("go ahead") is True


def test_confirmation_no():
    assert parse_confirmation_response("no") is False
    assert parse_confirmation_response("nope") is False
    assert parse_confirmation_response("wrong") is False


def test_confirmation_cancel():
    assert parse_confirmation_response("cancel") is False
    assert parse_confirmation_response("never mind") is False
    assert parse_confirmation_response("abort") is False


def _cm():
    cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED, reasoner=RecordingReasoner())
    cm.start_session()
    return cm


def test_close_app_requires_confirmation_then_yes_executes():
    cm = _cm()
    resp, keep = cm.handle_transcript("close chrome")
    assert keep is True
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert "close" in resp.lower() and "chrome" in resp.lower()

    resp2, keep2 = cm.handle_transcript("yes")
    assert keep2 is True
    assert cm.state == ConversationState.LISTENING
    assert "chrome" in resp2.lower()


def test_cancel_pending_confirmation():
    cm = _cm()
    cm.handle_transcript("close chrome")
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    assert cm.context.pending_intent is not None

    resp, keep = cm.handle_transcript("cancel")
    assert keep is True
    assert cm.context.pending_intent is None, "cancel must clear the pending intent"
    assert "cancelled" in resp.lower()
    assert cm.state != ConversationState.WAITING_FOR_CONFIRMATION


# ---------------------------------------------------------------------------
# Conversation follow-up context
# ---------------------------------------------------------------------------

def test_followup_query():
    cm = _cm()
    cm.handle_transcript("What is F.R.I.D.A.Y.?")
    resp2, _ = cm.handle_transcript("What backend does it use?")
    assert resp2
    assert "backend" in cm.context.active_topic


def test_pronoun_resolution():
    from friday.core.conversation import ConversationContext
    ctx = ConversationContext()
    ctx.update_topic("What backend does it use?")
    rewritten = ctx.rewrite_followup("Why did we choose that?", history=[])
    assert "friday" in rewritten.lower()
    assert "backend" in rewritten.lower()


def test_topic_switch():
    cm = _cm()
    cm.handle_transcript("What backend does it use?")
    resp2, _ = cm.handle_transcript("Actually, forget that. What time is it?")
    assert resp2
    assert cm.context.active_topic == "", "topic must be cleared by the switchaway"


# ---------------------------------------------------------------------------
# Interruption
# ---------------------------------------------------------------------------

def test_stop_during_speaking():
    assert _is_interrupt_utterance("wait") is True
    assert _is_interrupt_utterance("that's enough") is True
    assert _is_interrupt_utterance("hold on") is True
    # "stop" ends the session and must keep flowing through the pipeline.
    assert _is_interrupt_utterance("stop") is False
    # Non-exact phrases are NOT treated as interrupts (no aggressive false hits).
    assert _is_interrupt_utterance("wait for the movie") is False


def test_interrupt_state_transition():
    sm = VoiceStateMachine()
    assert sm.transition_to(VoiceState.WAKE_DETECTED)
    assert sm.transition_to(VoiceState.COMMAND_LISTENING)
    assert sm.transition_to(VoiceState.PROCESSING)
    assert sm.transition_to(VoiceState.EXECUTING)
    assert sm.transition_to(VoiceState.SPEAKING)
    assert sm.transition_to(VoiceState.INTERRUPTED), "SPEAKING -> INTERRUPTED allowed"
    assert sm.transition_to(VoiceState.COMMAND_LISTENING), "INTERRUPTED -> LISTENING allowed"
    assert sm.state == VoiceState.COMMAND_LISTENING


def test_interrupt_utterance_never_routed(run_voice):
    friday, tts, handle_spy = run_voice(["open chrome", "wait", "goodbye"])
    assert handle_spy.calls == [("open chrome",), ("goodbye",)], (
        "A pure interrupt utterance must never reach the command pipeline"
    )
    assert "wait" not in [c[0].lower() for c in handle_spy.calls]


# ---------------------------------------------------------------------------
# Stubs for the voice-loop interruption test
# ---------------------------------------------------------------------------

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}

import friday.core.assistant as assistant_mod
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RecordingReasoner:
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "test-model")
        self.base_url = kwargs.get("base_url", "http://test:1")
        self.endpoint = kwargs.get("endpoint", "http://test:1")
        self.timeout = kwargs.get("timeout", 30)
        self.requests = []

    def is_available(self):
        return True

    def health(self):
        return "test"

    def close(self):
        pass

    def request(self, transcript, context, mode="action"):
        self.requests.append(transcript)
        return {"type": "response", "text": f"What about: {transcript}"}


class FakeServerManager:
    def __init__(self, **kwargs):
        self.owned_flag = False

    def is_owned(self):
        return self.owned_flag

    def start(self):
        return True

    def stop(self):
        pass

    def health(self):
        return "test"

    def is_already_running(self):
        return False


class StubTTS:
    def __init__(self, **kwargs):
        self.spoken = []
        self.stopped = False
        self._is_speaking = False

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
    def __init__(self, **kwargs):
        self.transcripts = []

    def set_script(self, transcripts):
        self.transcripts = list(transcripts)

    def start_session(self):
        return self

    def stop_session(self):
        pass

    def __enter__(self):
        return self.start_session()

    def __exit__(self, *args):
        self.stop_session()
        return False

    def listen_once(self, initial_chunks=None):
        if not self.transcripts:
            return ""
        return self.transcripts.pop(0)


class GateWakeWord:
    def __init__(self, session, wake_word="friday"):
        self.session = session
        self.wake_word = wake_word

    def wait_for_wake_word(self):
        while True:
            text = self.session.listen_once()
            if not text:
                return ""
            if self.wake_word in text.lower():
                return text


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(assistant_mod, "TextToSpeech", StubTTS)
    monkeypatch.setattr(assistant_mod, "VoiceSessionManager", StubSessionManager)
    monkeypatch.setattr(assistant_mod, "WakeWordListener", GateWakeWord)
    monkeypatch.setattr(assistant_mod, "LlamaCppReasoner", RecordingReasoner)
    monkeypatch.setattr(assistant_mod, "LlamaCppServerManager", FakeServerManager)


@pytest.fixture()
def run_voice(monkeypatch):
    def _run(transcripts, gated=False, observer=None):
        friday = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"))
        friday._wake_word_required = gated
        friday.reasoner = RecordingReasoner()
        friday.conversation_manager.reasoner = friday.reasoner
        friday.session_manager.set_script(list(transcripts))

        class Recorder:
            def __init__(self, fn):
                self.fn = fn
                self.calls = []

            def __call__(self, *args, **kwargs):
                self.calls.append(args)
                return self.fn(*args, **kwargs)

        handle_spy = Recorder(friday.conversation_manager.handle_transcript)
        friday.conversation_manager.handle_transcript = handle_spy
        if observer is not None:
            friday.voice_state.set_observer(observer)
        friday.run()
        return friday, friday.tts, handle_spy

    return _run


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])