"""Offline tests for hands-free wake-word listening.

No microphone and no Whisper model are used: the energy gate is driven with
synthetic blocks, transcription and command handling are injected callbacks,
and the runtime integration uses a fake ``sounddevice`` module.
"""
from __future__ import annotations

import sys
import threading
import time
import types

import numpy as np
import pytest

from friday.web import metrics as metrics_mod
from friday.voice.audio_hub import AudioHub
from friday.web.handsfree import (
    HandsFreeConfig,
    HandsFreeListener,
    extract_wake_command,
)
from friday.core.wake_word import WakeWordListener
from friday.web.runtime import DashboardRuntime, reset_runtime


MINIMAL_CONFIG = """
wake_word: "friday"
security:
  dry_run: true
  allow_real_execution: false
tools:
  dry_run: true
  allow_real_execution: false
voice:
  offline_only: true
  hands_free:
    enabled: true
    wake_word: "friday"
    silence_ms: 60
    command_timeout_seconds: 5
"""


# ----------------------------------------------------------------------
# Wake-word parsing
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("hey friday what's the weather", (True, "what's the weather")),
        ("Hey Friday, play some music.", (True, "play some music")),
        ("ok friday", (True, "")),
        ("FRIDAY", (True, "")),
        ("frida what time is it", (True, "what time is it")),
        ("hey, ferdy.", (True, "")),
        ("hey freddy open the editor", (True, "open the editor")),
        ("free day tell me the news", (True, "tell me the news")),
        ("so, friday, what's the time", (True, "what's the time")),
        ("well um friday play music", (True, "play music")),
        ("i asked friday about the weather", (False, "")),
        ("they said friday works for them", (False, "")),
        ("how are you", (False, "")),
        ("", (False, "")),
    ],
)
def test_extract_wake_command_default(text, expected):
    assert extract_wake_command(text) == expected


def test_wake_word_must_open_the_utterance():
    # A mid-sentence mention must not wake the assistant...
    assert extract_wake_command("I was telling him Friday is busy") == (False, "")
    # ...but ordinary filler before the wake word is tolerated.
    assert extract_wake_command("uh, hey friday, what's up") == (True, "what's up")


def test_extract_wake_command_custom_word():
    assert extract_wake_command("hey jarvis open the editor", "jarvis") == (
        True,
        "open the editor",
    )
    assert extract_wake_command("hey friday open the editor", "jarvis") == (False, "")


# ----------------------------------------------------------------------
# CLI wake-word gate (friday/core/wake_word.py)
# ----------------------------------------------------------------------
class _StubSession:
    def __init__(self, utterances):
        self._utterances = list(utterances)

    def listen_once(self):
        return self._utterances.pop(0) if self._utterances else ""


def test_cli_wake_word_rejects_embedded_mentions():
    listener = WakeWordListener(_StubSession([]), "friday")

    assert listener._opens_with_wake_word("friday play music") is True
    assert listener._opens_with_wake_word("hey friday") is True
    assert listener._opens_with_wake_word("so friday, what's up") is True
    assert listener._opens_with_wake_word("I was telling him Friday is busy") is False
    assert listener._opens_with_wake_word("fridayish is not a word") is False
    assert listener._opens_with_wake_word("saturday is great") is False


def test_cli_wake_word_waits_for_an_utterance_that_starts_with_it():
    session = _StubSession([
        "I told him Friday is busy",
        "hey friday what time is it",
    ])

    assert WakeWordListener(session, "friday").wait_for_wake_word() == "hey friday what time is it"


# ----------------------------------------------------------------------
# Energy-gated segmentation
# ----------------------------------------------------------------------
def _blocks(amplitude: float, count: int, block: int = 320) -> list[np.ndarray]:
    return [np.full(block, amplitude, dtype=np.float32) for _ in range(count)]


def test_capture_utterance_segments_speech_then_silence():
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        max_utterance_ms=2000,
        pre_roll_ms=0,
    )
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=cfg,
        vad=False,
    )
    # 5 voiced blocks open the gate (96 ms onset), 10 silent blocks close it.
    for block in _blocks(0.2, 5) + _blocks(0.0, 10):
        listener._queue.put(block)

    utterance = listener._capture_utterance()

    assert utterance is not None
    assert utterance.dtype == np.float32
    assert float(np.max(np.abs(utterance))) > 0.1
    assert len(utterance) / cfg.sample_rate * 1000 >= 5 * cfg.block_ms


def test_capture_utterance_requires_onset_run():
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
    )
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=cfg,
        vad=False,
    )
    # A short click (3 blocks) never reaches the 96 ms onset run.
    for block in _blocks(0.2, 3) + _blocks(0.0, 12):
        listener._queue.put(block)

    # The gate keeps waiting for speech, so stop it after a moment.
    timer = threading.Timer(0.2, listener._stop.set)
    timer.start()
    try:
        assert listener._capture_utterance() is None
    finally:
        timer.cancel()


def test_capture_utterance_returns_when_the_queue_is_idle():
    """Idle waits must yield to _run so flush/session timers can fire."""
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=HandsFreeConfig(),
        vad=False,
    )
    started = time.monotonic()

    assert listener._capture_utterance() is None
    assert time.monotonic() - started < 1.0, "idle capture must not block forever"


def test_capture_utterance_keeps_partial_state_across_idle_returns():
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
    )
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=cfg,
        vad=False,
    )
    # Enough onset to open the utterance; feed returns None until it closes.
    for block in _blocks(0.2, 5):
        listener._queue.put(block)
    assert listener._capture_utterance() is None
    assert listener._segmenter.speaking is True, "partial utterance survives idle return"

    for block in _blocks(0.0, 10):
        listener._queue.put(block)
    utterance = listener._capture_utterance()

    assert utterance is not None
    assert listener._segmenter.speaking is False


def test_capture_utterance_time_slice_preserves_partial_utterance():
    """Continuous frames must not stop control returning to the main loop."""
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=800,
        min_speech_ms=100,
        pre_roll_ms=0,
    )
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=cfg,
        vad=False,
    )
    stop_feeder = threading.Event()

    def _feed_silence() -> None:
        while not stop_feeder.is_set():
            listener._queue.put(np.zeros(320, dtype=np.float32))
            time.sleep(0.02)

    # Open an utterance, then keep the queue permanently non-empty.
    for block in _blocks(0.2, 10):
        listener._queue.put(block)
    feeder = threading.Thread(target=_feed_silence, daemon=True)
    feeder.start()
    try:
        started = time.monotonic()
        assert listener._capture_utterance(max_wait_seconds=0.1) is None
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, "time slice must yield promptly"
        assert listener._segmenter.speaking is True, "partial utterance survives the yield"
    finally:
        stop_feeder.set()
        feeder.join(timeout=1.0)


# ----------------------------------------------------------------------
# Wake / command flow
# ----------------------------------------------------------------------
def _listener(**kwargs):
    commands: list[str] = []
    states: list[str] = []
    wakes: list[str] = []
    listener = HandsFreeListener(
        transcribe=kwargs.get("transcribe", lambda _samples: ""),
        on_command=commands.append,
        on_state=states.append,
        on_wake=wakes.append,
        config=kwargs.get("config", HandsFreeConfig()),
        vad=kwargs.get("vad", False),
    )
    return listener, commands, states, wakes


def test_one_shot_command_dispatches_immediately():
    listener, commands, states, wakes = _listener()

    listener._handle_text("hey friday what time is it")
    # Accumulated; flush to dispatch the single combined answer.
    listener._flush_pending()

    assert commands == ["what time is it"]
    assert wakes == ["hey friday what time is it"]
    assert "PROCESSING" in states


def test_bare_wake_word_then_command():
    listener, commands, states, _wakes = _listener()

    listener._handle_text("hey friday")
    assert commands == []
    assert listener.state == "COMMAND_LISTENING"

    listener._handle_text("open the dashboard")
    assert commands == []
    assert listener._pending_commands == ["open the dashboard"]

    listener._flush_pending()
    assert commands == ["open the dashboard"]


def test_repeated_bare_wake_mid_session_is_an_ack_not_a_question():
    listener, commands, states, wakes = _listener()
    listener._handle_text("hey friday what time is it")
    assert listener._pending_commands == ["what time is it"]
    wake_count = len(wakes)

    listener._handle_text("hey friday")
    listener._handle_text("fridays")

    assert listener._pending_commands == ["what time is it"], "bare wake must not be queued"
    assert len(wakes) == wake_count + 2, "each bare wake re-acks"
    assert states[-1] == "COMMAND_LISTENING"
    listener._flush_pending()
    assert commands == ["what time is it"]


def _ack_listener() -> tuple[HandsFreeListener, list[int]]:
    acknowledgements: list[int] = []
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_state=lambda _state: None,
        on_wake=lambda _text: None,
        on_acknowledge=lambda: acknowledgements.append(len(acknowledgements)),
        config=HandsFreeConfig(),
        vad=False,
    )
    return listener, acknowledgements


def test_bare_wake_word_speaks_acknowledgement():
    listener, acknowledgements = _ack_listener()

    listener._handle_text("hey friday")

    assert acknowledgements == [0]
    assert listener.state == "COMMAND_LISTENING"


def test_wake_with_a_command_does_not_acknowledge():
    listener, acknowledgements = _ack_listener()

    listener._handle_text("hey friday what time is it")

    assert acknowledgements == [], "only bare wake words are acknowledged"


def test_repeated_bare_wake_mid_session_acknowledges_each_time():
    listener, acknowledgements = _ack_listener()
    listener._handle_text("hey friday what time is it")

    listener._handle_text("hey friday")
    listener._handle_text("fridays")

    assert acknowledgements == [0, 1]


def test_acknowledgement_drops_queued_audio_and_partial_utterance():
    listener, acknowledgements = _ack_listener()
    # Open a partial utterance, then leave audio waiting in the queue: both
    # would otherwise be mistaken for the user's next command after playback.
    for block in _blocks(0.2, 10):
        listener._segmenter.feed(block)
    for block in _blocks(0.2, 4):
        listener._queue.put(block)
    assert listener._segmenter.speaking is True

    listener._handle_text("hey friday")

    assert acknowledgements == [0]
    assert listener._queue.empty(), "self-echo must not become the next command"
    assert listener._segmenter.speaking is False, "partial utterance is discarded"
    assert listener.session_active is True


def test_acknowledgement_failure_does_not_block_the_wake_session():
    wakes: list[str] = []
    states: list[str] = []

    def _broken_ack() -> None:
        raise RuntimeError("speaker unplugged")

    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_state=states.append,
        on_wake=wakes.append,
        on_acknowledge=_broken_ack,
        config=HandsFreeConfig(),
        vad=False,
    )

    listener._handle_text("hey friday")

    assert wakes == ["hey friday"]
    assert listener.session_active is True
    assert listener.state == "COMMAND_LISTENING"


def test_bare_wake_without_an_acknowledgement_callback_still_starts_session():
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=HandsFreeConfig(),
        vad=False,
    )

    listener._handle_text("hey friday")

    assert listener.session_active is True
    assert listener.state == "COMMAND_LISTENING"


def test_bare_wake_acknowledges_before_starting_the_assistant():
    """The ack must be quick; assistant startup can take seconds."""
    order: list[str] = []
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_wake=lambda _text: order.append("wake"),
        on_acknowledge=lambda: order.append("ack"),
        config=HandsFreeConfig(),
        vad=False,
    )

    listener._handle_text("hey friday")

    assert order == ["ack", "wake"]
    assert listener.session_active is True


def test_mid_session_bare_wake_records_heard_text_before_acking():
    order: list[str] = []
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_wake=lambda _text: order.append("wake"),
        on_acknowledge=lambda: order.append("ack"),
        config=HandsFreeConfig(),
        vad=False,
    )
    listener._handle_text("hey friday what time is it")
    order.clear()

    listener._handle_text("hey friday")

    assert order == ["wake", "ack"]


def test_non_wake_speech_is_ignored():
    listener, commands, _states, _wakes = _listener()

    listener._handle_text("the weather is nice today")

    assert commands == []


def test_stop_phrase_ends_active_session():
    listener, commands, states, _wakes = _listener()

    listener._handle_text("hey friday what time is it")
    assert listener.session_active is True
    assert listener._pending_commands == ["what time is it"]

    listener._handle_text("stop listening")
    # Accumulated questions flushed as a single combined command.
    assert commands and "what time is it" in commands[-1]
    assert listener.session_active is False
    assert states[-1] == "WAKE_LISTENING"


def test_end_session_notifies_owner_once():
    ended: list[bool] = []
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_session_end=lambda: ended.append(True),
        config=HandsFreeConfig(),
        vad=False,
    )

    listener.start_session()
    listener.end_session()
    listener.end_session()

    assert ended == [True], "owner is told exactly once per active session"


def test_stop_phrase_closes_owner_session():
    ended: list[bool] = []
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_session_end=lambda: ended.append(True),
        config=HandsFreeConfig(),
        vad=False,
    )

    listener._handle_text("hey friday what time is it")
    listener._handle_text("stop listening")

    assert ended == [True]
    assert listener.session_active is False


# ----------------------------------------------------------------------
# Runtime integration
# ----------------------------------------------------------------------
class _FakeStream:
    def __init__(self, **_kwargs):
        self.active = True

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.active = False


def test_run_flushes_a_multi_question_turn_while_idle():
    """The flush timer must fire without waiting for another utterance."""
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
        flush_timeout_seconds=1.5,
    )
    commands: list[str] = []
    hub = AudioHub(stream_factory=lambda **kwargs: _FakeStream(**kwargs))
    listener = HandsFreeListener(
        transcribe=lambda _samples: "hey friday what time is it",
        on_command=commands.append,
        config=cfg,
        vad=False,
        hub=hub,
    )

    listener.start()
    try:
        deadline = time.monotonic() + 3.0
        while not hub.owned_by("handsfree") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub.owned_by("handsfree")

        for block in _blocks(0.2, 10) + _blocks(0.0, 10):
            listener._queue.put(block)

        deadline = time.monotonic() + 8.0
        while not commands and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        listener.stop()

    assert commands == ["what time is it"]


def test_flush_fires_while_microphone_frames_keep_arriving():
    """A continuous mic stream must not starve the flush/session timers."""
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
        flush_timeout_seconds=1.5,
    )
    commands: list[str] = []
    hub = AudioHub(stream_factory=lambda **kwargs: _FakeStream(**kwargs))
    listener = HandsFreeListener(
        transcribe=lambda _samples: "hey friday what time is it",
        on_command=commands.append,
        config=cfg,
        vad=False,
        hub=hub,
    )
    stop_feeder = threading.Event()

    def _feed_silence() -> None:
        # The real AudioHub never lets the queue go empty; model that here.
        while not stop_feeder.is_set():
            listener._queue.put(np.zeros(320, dtype=np.float32))
            time.sleep(0.005)

    listener.start()
    feeder = threading.Thread(target=_feed_silence, daemon=True)
    try:
        deadline = time.monotonic() + 3.0
        while not hub.owned_by("handsfree") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub.owned_by("handsfree")

        for block in _blocks(0.2, 5) + _blocks(0.0, 10):
            listener._queue.put(block)
        feeder.start()

        deadline = time.monotonic() + 8.0
        while not commands and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop_feeder.set()
        feeder.join(timeout=1.0)
        listener.stop()

    assert commands == ["what time is it"], "flush must fire even with continuous frames"


def test_multi_question_flush_fires_with_continuous_frames():
    """Two in-session questions combine into one answer even while frames flow."""
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
        flush_timeout_seconds=1.5,
    )
    texts = iter(["hey friday what time is it", "and what's the weather"])
    commands: list[str] = []
    hub = AudioHub(stream_factory=lambda **kwargs: _FakeStream(**kwargs))
    listener = HandsFreeListener(
        transcribe=lambda _samples: next(texts, ""),
        on_command=commands.append,
        config=cfg,
        vad=False,
        hub=hub,
    )
    stop_feeder = threading.Event()

    def _feed_silence() -> None:
        while not stop_feeder.is_set():
            listener._queue.put(np.zeros(320, dtype=np.float32))
            time.sleep(0.005)

    listener.start()
    feeder = threading.Thread(target=_feed_silence, daemon=True)
    try:
        deadline = time.monotonic() + 3.0
        while not hub.owned_by("handsfree") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub.owned_by("handsfree")

        # Two separate utterances, queued back-to-back before the flush fires.
        for _ in range(2):
            for block in _blocks(0.2, 5) + _blocks(0.0, 10):
                listener._queue.put(block)

        deadline = time.monotonic() + 3.0
        while len(listener._pending_commands) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert listener._pending_commands == ["what time is it", "and what's the weather"]

        feeder.start()
        deadline = time.monotonic() + 6.0
        while not commands and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop_feeder.set()
        feeder.join(timeout=1.0)
        listener.stop()

    assert commands == ["what time is it and what's the weather"]


def test_session_expiry_fires_while_microphone_frames_keep_arriving():
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
        session_timeout_seconds=30,
    )
    ended: list[bool] = []
    hub = AudioHub(stream_factory=lambda **kwargs: _FakeStream(**kwargs))
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        on_session_end=lambda: ended.append(True),
        config=cfg,
        vad=False,
        hub=hub,
    )
    stop_feeder = threading.Event()

    def _feed_silence() -> None:
        while not stop_feeder.is_set():
            listener._queue.put(np.zeros(320, dtype=np.float32))
            time.sleep(0.005)

    listener.start()
    feeder = threading.Thread(target=_feed_silence, daemon=True)
    try:
        deadline = time.monotonic() + 3.0
        while not hub.owned_by("handsfree") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub.owned_by("handsfree")

        listener.start_session()
        listener._session_deadline = time.monotonic() - 1.0
        feeder.start()

        deadline = time.monotonic() + 4.0
        while listener.session_active and time.monotonic() < deadline:
            time.sleep(0.02)

        assert listener.session_active is False
        assert ended == [True], "owner is told the session expired"
        assert listener.state == "WAKE_LISTENING"
    finally:
        stop_feeder.set()
        feeder.join(timeout=1.0)
        listener.stop()


def test_command_window_expiry_fires_while_microphone_frames_keep_arriving():
    cfg = HandsFreeConfig(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        pre_roll_ms=0,
        command_timeout_seconds=3,
    )
    hub = AudioHub(stream_factory=lambda **kwargs: _FakeStream(**kwargs))
    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        config=cfg,
        vad=False,
        hub=hub,
    )
    stop_feeder = threading.Event()

    def _feed_silence() -> None:
        while not stop_feeder.is_set():
            listener._queue.put(np.zeros(320, dtype=np.float32))
            time.sleep(0.005)

    listener.start()
    feeder = threading.Thread(target=_feed_silence, daemon=True)
    try:
        deadline = time.monotonic() + 3.0
        while not hub.owned_by("handsfree") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub.owned_by("handsfree")

        listener._set_state("COMMAND_LISTENING")
        listener._mode = "command"
        listener._command_prompted = True
        listener._command_deadline = time.monotonic() - 1.0
        feeder.start()

        deadline = time.monotonic() + 4.0
        while listener.state != "WAKE_LISTENING" and time.monotonic() < deadline:
            time.sleep(0.02)

        assert listener._mode == "wake"
        assert listener._command_prompted is False
        assert listener.state == "WAKE_LISTENING"
    finally:
        stop_feeder.set()
        feeder.join(timeout=1.0)
        listener.stop()


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
    monkeypatch.setattr(metrics_mod, "prime_cpu", lambda: None)
    rt = DashboardRuntime(
        config_path=str(config_path),
        activity_path=str(tmp_path / "activity.json"),
    )
    reset_runtime(rt)
    yield rt
    reset_runtime(None)


@pytest.fixture()
def fake_sounddevice(monkeypatch):
    module = types.SimpleNamespace(
        query_devices=lambda: [{"max_input_channels": 1, "name": "Fake Mic"}],
        InputStream=_FakeStream,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


def test_runtime_start_and_stop_handsfree(runtime, fake_sounddevice):
    state = runtime.start_handsfree()

    assert state["active"] is True
    assert state["state"] == "WAKE_LISTENING"
    assert state["wake_word"] == "friday"
    assert runtime.voice_state()["hands_free_active"] is True

    stopped = runtime.stop_handsfree()

    assert stopped["active"] is False
    assert stopped["state"] == "STOPPED"


def test_voice_state_reports_real_capture_flag(runtime):
    assert runtime.voice_state()["capture_active"] is False

    runtime._capture_stream = object()
    try:
        assert runtime.voice_state()["capture_active"] is True
    finally:
        runtime._capture_stream = None

    assert runtime.voice_state()["capture_active"] is False


def test_stop_handsfree_resets_conversation_session(runtime, fake_sounddevice):
    class _Context:
        def __init__(self):
            self.stops = 0

        def stop_session(self):
            self.stops += 1

    context = _Context()
    runtime._assistant = types.SimpleNamespace(conversation_manager=context)

    runtime.start_handsfree()
    runtime.stop_handsfree()

    assert context.stops == 1


def test_runtime_handsfree_command_is_spoken(runtime, monkeypatch):
    submitted: list[str] = []
    spoken: list[str] = []

    monkeypatch.setattr(runtime, "submit_chat", lambda message: submitted.append(message) or {"response": "It is noon."})
    monkeypatch.setattr(
        runtime,
        "_get_tts",
        lambda: types.SimpleNamespace(speak=spoken.append),
    )

    runtime._handsfree_on_command("what time is it")

    assert submitted == ["what time is it"]
    assert spoken == ["It is noon."]


def test_runtime_acknowledgement_phrases_parse_string_and_list(runtime, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": "Yes boss"}},
    )
    assert runtime._acknowledgement_phrases() == ["Yes boss"]

    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": ["Yes Abhi", "  ", "Yes boss"]}},
    )
    assert runtime._acknowledgement_phrases() == ["Yes Abhi", "Yes boss"]

    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": False}},
    )
    assert runtime._acknowledgement_phrases() == []

    monkeypatch.setattr(runtime, "_voice_config", lambda: {"hands_free": {}})
    assert runtime._acknowledgement_phrases() == []


def test_runtime_acknowledgement_speaks_and_cycles_phrases(runtime, monkeypatch):
    spoken: list[str] = []
    statuses: list[str] = []

    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": ["Yes Abhi", "Yes boss"]}},
    )
    monkeypatch.setattr(
        runtime,
        "_get_tts",
        lambda: types.SimpleNamespace(speak=spoken.append),
    )
    monkeypatch.setattr(runtime, "_publish_handsfree", statuses.append)

    runtime._handsfree_on_acknowledge()
    runtime._handsfree_on_acknowledge()
    runtime._handsfree_on_acknowledge()

    assert spoken == ["Yes Abhi", "Yes boss", "Yes Abhi"]
    assert statuses == ["RESPONDING", "COMMAND_LISTENING"] * 3


def test_runtime_acknowledgement_disabled_does_not_speak(runtime, monkeypatch):
    spoken: list[str] = []

    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": False}},
    )
    monkeypatch.setattr(
        runtime,
        "_get_tts",
        lambda: types.SimpleNamespace(speak=spoken.append),
    )

    runtime._handsfree_on_acknowledge()

    assert spoken == []


def test_runtime_acknowledgement_tts_failure_keeps_listening(runtime, monkeypatch):
    statuses: list[str] = []

    def _broken():
        raise RuntimeError("no voice model")

    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": "Yes boss"}},
    )
    monkeypatch.setattr(runtime, "_get_tts", _broken)
    monkeypatch.setattr(runtime, "_publish_handsfree", statuses.append)

    runtime._handsfree_on_acknowledge()  # must not raise

    assert statuses == ["RESPONDING", "COMMAND_LISTENING"]
    assert "speech playback failed" in runtime._handsfree_error


def test_runtime_acknowledgement_does_not_enter_the_chat_pipeline(runtime, monkeypatch):
    spoken: list[str] = []

    def _fail_submit(_message):
        raise AssertionError("acknowledgement must not submit a chat turn")

    monkeypatch.setattr(runtime, "submit_chat", _fail_submit)
    monkeypatch.setattr(
        runtime,
        "_voice_config",
        lambda: {"hands_free": {"acknowledgement": "Yes boss"}},
    )
    monkeypatch.setattr(
        runtime,
        "_get_tts",
        lambda: types.SimpleNamespace(speak=spoken.append),
    )
    monkeypatch.setattr(runtime, "_publish_handsfree", lambda status=None: None)

    runtime._handsfree_on_acknowledge()

    assert spoken == ["Yes boss"]


def test_runtime_acknowledgement_reads_reloaded_config(runtime):
    with open(runtime.config_path, "w", encoding="utf-8") as fh:
        fh.write(
            MINIMAL_CONFIG.replace(
                "    command_timeout_seconds: 5",
                '    command_timeout_seconds: 5\n    acknowledgement: "Yes sir"',
            )
        )

    runtime.reload_config()

    assert runtime._acknowledgement_phrases() == ["Yes sir"]


def test_start_handsfree_wires_the_acknowledgement_callback(runtime, fake_sounddevice):
    runtime.start_handsfree()
    try:
        assert runtime._handsfree._on_acknowledge == runtime._handsfree_on_acknowledge
    finally:
        runtime.stop_handsfree()


def test_runtime_handsfree_disabled_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        MINIMAL_CONFIG.replace("enabled: true", "enabled: false"),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics_mod, "prime_cpu", lambda: None)
    rt = DashboardRuntime(
        config_path=str(config_path),
        activity_path=str(tmp_path / "activity.json"),
    )
    try:
        with pytest.raises(ValueError, match="disabled"):
            rt.start_handsfree()
    finally:
        rt.shutdown()
