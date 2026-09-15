"""
Voice action execution tests (STEP 6 & 7 of the voice-unification task).

Simulates the full voice pipeline so voice and text share the SAME canonical
entry point:

    STT transcript
        -> (optional wake gate) -> Friday._process_transcript()
        -> ConversationManager.handle_transcript()
        -> deterministic router / reasoner
        -> real action handler (mocked os.startfile / webbrowser.open)
        -> response -> TTS

HANDS-FREE (default, config `voice.wake_word_required: false`):
    Every legible command is streamed straight into the pipeline, exactly like
    text mode â€” no wake word needed.

GATED (config `voice.wake_word_required: true`):
    Commands only flow after the wake word (one-shot "hey friday open chrome"
    or two-stage "friday" then the command). The gate consumes and drops any
    utterance without the wake word; a pause between wake word and command
    must NOT lose the command.

Everything is hermetic: mic/SessionManager/STT/TTS/reasoner/server are stubs.
"""
from pathlib import Path

import psutil
import pytest

import friday.core.assistant as assistant_mod

ROOT = Path(__file__).resolve().parents[1]


class RecordingReasoner:
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "test-model")
        self.base_url = kwargs.get("base_url", "http://test:1")
        self.endpoint = kwargs.get("endpoint", "http://test:1")
        self.timeout = kwargs.get("timeout", 30)
        self.requests = []
        self.modes = []

    def is_available(self):
        return True

    def health(self):
        return "test reasoner reachable"

    def close(self):
        pass

    def request(self, transcript, context, mode="action"):
        self.requests.append(transcript)
        self.modes.append(mode)
        return {"type": "response", "text": f"You asked about: {transcript}", "confidence": 0.9}


class FakeServerManager:
    def __init__(self, **kwargs):
        self.start_calls = 0
        self.stop_calls = 0
        self.owned_flag = False

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


class GateWakeWord:
    """Mirrors the real wake-word gate: non-wake transcripts are consumed and dropped."""
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


class _FakeProc:
    def __init__(self, name):
        self.info = {"name": name}


class Recorder:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        return self.fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    monkeypatch.setattr(assistant_mod, "TextToSpeech", StubTTS)
    monkeypatch.setattr(assistant_mod, "VoiceSessionManager", StubSessionManager)
    monkeypatch.setattr(assistant_mod, "WakeWordListener", GateWakeWord)
    monkeypatch.setattr(assistant_mod, "LlamaCppReasoner", RecordingReasoner)
    monkeypatch.setattr(assistant_mod, "LlamaCppServerManager", FakeServerManager)
    # Fake a running chrome.exe so OPEN_APP verification reports success.
    monkeypatch.setattr(psutil, "process_iter", lambda *a, **k: iter([_FakeProc("chrome.exe")]))


@pytest.fixture()
def tools_spy(monkeypatch):
    """Record tool invocations (no real app/browser launches)."""
    spy = {"startfile": [], "webbrowser_open": []}
    monkeypatch.setattr(
        "friday.tools.apps.os.startfile",
        lambda *a, **k: spy["startfile"].append(a[0]) or None,
    )
    monkeypatch.setattr(
        "friday.tools.browser.webbrowser.open",
        lambda *a, **k: spy["webbrowser_open"].append(a[0]) or True,
    )
    return spy


@pytest.fixture()
def run_voice(monkeypatch):
    """Build a stub-backed Friday primed to execute a scripted voice session.

    ``gated=True`` enables the wake-word gate (one-shot / two-stage / blocked
    no-wake commands) as if `voice.wake_word_required: true` were set.
    """
    def _run(transcripts, gated=False, observer=None):
        friday = assistant_mod.Friday(config_path=str(ROOT / "config.yaml"))
        reasoner = RecordingReasoner()
        friday.reasoner = reasoner
        friday.conversation_manager.reasoner = reasoner
        friday._wake_word_required = gated
        friday.session_manager.set_script(transcripts)

        handle_spy = Recorder(friday.conversation_manager.handle_transcript)
        friday.conversation_manager.handle_transcript = handle_spy
        if observer is not None:
            friday.voice_state.set_observer(observer)
        friday.run()
        return friday, reasoner, friday.tts, handle_spy

    return _run


def _count(lst, needle):
    return sum(1 for s in lst if needle in s)


# --- TEST 1 â€” Greeting --------------------------------------------------------

def test_voice_greeting(run_voice):
    friday, reasoner, tts, handle_spy = run_voice(["hi", "goodbye"])
    assert handle_spy.calls == [("hi",), ("goodbye",)]
    assert _count(tts.spoken, "Hello! How can I assist you today?") == 1
    assert reasoner.requests == []


# --- TEST 2 â€” Open Chrome -----------------------------------------------------

def test_voice_open_chrome(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(["open chrome", "goodbye"])
    assert handle_spy.calls == [("open chrome",), ("goodbye",)]
    assert tools_spy["startfile"] == [r"C:\Program Files\Google\Chrome\Application\chrome.exe"], (
        "OPEN_APP must call open_app(chrome) exactly once via the real handler"
    )
    assert _count(tts.spoken, "Opening Chrome.") == 1, "TTS must speak 'Opening Chrome.'"
    assert reasoner.requests == []


# --- TEST 3 â€” Open YouTube ----------------------------------------------------

def test_voice_open_youtube(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(["open youtube", "goodbye"])
    assert handle_spy.calls == [("open youtube",), ("goodbye",)]
    assert tools_spy["webbrowser_open"] == ["https://www.youtube.com"], (
        "OPEN_WEBSITE must call browser.open_website('youtube') via the real handler"
    )
    assert _count(tts.spoken, "Opening https://www.youtube.com.") == 1
    assert reasoner.requests == []


# --- TEST 4 â€” Reasoning -------------------------------------------------------

def test_voice_reasoning_invokes_reasoner(run_voice):
    friday, reasoner, tts, handle_spy = run_voice(["what is java", "goodbye"])
    assert handle_spy.calls == [("what is java",), ("goodbye",)]
    assert reasoner.requests == ["what is java"], "Ambiguous voice query must hit the reasoner"
    assert reasoner.modes == ["chat"], "Knowledge questions must use reasoner CHAT mode (never tool JSON)"
    assert _count(tts.spoken, "You asked about: what is java") == 1


# --- TEST 5 â€” STT noise never reaches router/reasoner/tts ---------------------

def test_voice_stt_noise_ignored(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(
        ["No clear speech detected.", "hi", "goodbye"]
    )
    assert handle_spy.calls == [("hi",), ("goodbye",)], "Noise must never reach handle_transcript"
    assert reasoner.requests == []
    assert tools_spy["startfile"] == []
    assert _count(tts.spoken, "Hello! How can I assist you today?") == 1


# --- TEST 6 â€” Exact execution count (no duplicates) ---------------------------

def test_voice_exact_execution_count(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(["open chrome", "goodbye"])
    command_calls = [c for c in handle_spy.calls if c[0] == "open chrome"]
    assert len(command_calls) == 1, "ConversationManager must process the command exactly once"
    assert len(tools_spy["startfile"]) == 1, "Tool must execute exactly once"
    assert _count(tts.spoken, "Opening Chrome.") == 1, "Spoken response must be exactly once"
    assert len(reasoner.requests) == 0


# ==============================================================================
# GATED MODE (voice.wake_word_required: true) â€” wake phrase still supported
# ==============================================================================

def test_voice_gated_one_shot_executes(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(
        ["hey friday open chrome", "friday goodbye"], gated=True
    )
    assert handle_spy.calls == [("open chrome",), ("goodbye",)], (
        "Wake phrase must be stripped BEFORE the pipeline sees the command"
    )
    assert len(tools_spy["startfile"]) == 1
    assert reasoner.requests == []


def test_voice_gated_two_stage_executes(run_voice, tools_spy):
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday", "open chrome", "friday goodbye"], gated=True
    )
    assert handle_spy.calls == [("open chrome",), ("goodbye",)], (
        "Command spoken after a bare wake word must reach the assistant"
    )
    assert len(tools_spy["startfile"]) == 1


def test_voice_gated_two_stage_survives_silent_gap(run_voice, tools_spy):
    # A silent listen (timeout) between wake word and command must NOT drop
    # the follow-up command back into the wake gate.
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday", "", "No clear speech detected.", "open chrome", "friday goodbye"],
        gated=True,
    )
    assert handle_spy.calls == [("open chrome",), ("goodbye",)]
    assert len(tools_spy["startfile"]) == 1
    assert len(reasoner.requests) == 0


def test_voice_gated_blocks_no_wake_command(run_voice, tools_spy):
    # Only the wake-bearing command may execute; the bare "open chrome" is
    # consumed by the gate and never reaches the assistant.
    friday, reasoner, tts, handle_spy = run_voice(
        ["open chrome", "friday open chrome", "friday goodbye"], gated=True
    )
    assert len(handle_spy.calls) == 2, "Only wake-bearing transcripts reach the assistant"
    assert handle_spy.calls[0][0] == "open chrome"
    assert len(tools_spy["startfile"]) == 1, "The no-wake 'open chrome' must never execute a tool"
    assert len(reasoner.requests) == 0


def test_voice_gated_bare_wake_acknowledges_then_executes(run_voice, tools_spy):
    # Bare wake word -> "Yes?" ack -> command window captures the command.
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday", "open chrome", "friday goodbye"], gated=True
    )
    assert handle_spy.calls == [("open chrome",), ("goodbye",)]
    assert "Yes?" in tts.spoken, "Bare wake word must be acknowledged (Yes?)"
    assert len(tools_spy["startfile"]) == 1


def test_voice_gated_state_machine_transitions(run_voice, tools_spy):
    from friday.voice.state_machine import VoiceState
    # Full voice lifecycle for a two-stage wake gated session:
    # WAKE_DETECTED -> COMMAND_LISTENING -> PROCESSING -> EXECUTING -> SPEAKING -> IDLE
    seen = []
    friday, reasoner, tts, handle_spy = run_voice(
        ["friday", "open chrome", "friday goodbye"],
        gated=True,
        observer=lambda s: seen.append(s.name),
    )
    assert seen[0] == "WAKE_DETECTED"
    assert "COMMAND_LISTENING" in seen, "Bare wake must enter the command listening window"
    assert "PROCESSING" in seen
    assert "EXECUTING" in seen
    assert "SPEAKING" in seen
    assert seen[-1] == "IDLE", "Loop must return to IDLE standby after responding"

    machine = friday.voice_state
    assert isinstance(machine.state, VoiceState)
    assert machine.state == VoiceState.IDLE


def test_voice_idle_ignores_non_wake_speech_in_gated_mode(run_voice, tools_spy):
    # Non-wake speech while IDLE is consumed by the gate and ignored —
    # it must never become a command (STEP 5 behaviour).
    friday, reasoner, tts, handle_spy = run_voice(
        ["open youtube", "play kalyani song on youtube", "friday hello", "friday goodbye"],
        gated=True,
    )
    # Only "friday hello" (-> greeting) and "friday goodbye" reach the assistant.
    assert handle_spy.calls == [("hello",), ("goodbye",)]
    assert tools_spy["webbrowser_open"] == [], (
        "Non-wake speech must NEVER open a browser while IDLE / gated"
    )
    assert len(reasoner.requests) == 0