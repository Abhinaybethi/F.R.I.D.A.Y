"""Tests for the shared Milestone 1 audio pipeline.

Covers the pieces that every voice body now depends on:

* :class:`friday.voice.audio_hub.AudioHub` — one stream, explicit owner,
  frame fan-out, safe unsubscribe;
* :class:`friday.voice.echo.EchoSuppressor` — playback gate, learned echo
  floor, hangover, threshold ceiling;
* :class:`friday.voice.segmenter.SpeechSegmenter` in deterministic energy-only
  mode (``vad=False``);
* barge-in capture in :class:`friday.web.handsfree.HandsFreeListener`, with
  and without TTS echo;
* the CLI :class:`friday.voice.audio_input.AudioInput` wrapper sharing the hub.

Everything here is hardware-free: audio is injected as numpy blocks and the
hub stream is a fake, so these tests are fast and deterministic.
"""
from __future__ import annotations

import threading
import time
from typing import List

import numpy as np
import pytest

from friday.voice.audio_hub import AudioHub
from friday.voice.audio_input import AudioInput
from friday.voice.echo import EchoSuppressor
from friday.voice.segmenter import SegmenterConfig, SpeechSegmenter
from friday.web.handsfree import HandsFreeConfig, HandsFreeListener

BLOCK = 320  # 20 ms at 16 kHz


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.active = False
        self.starts = 0
        self.stops = 0
        self.closes = 0

    def start(self):
        self.active = True
        self.starts += 1

    def stop(self):
        self.active = False
        self.stops += 1

    def close(self):
        self.active = False
        self.closes += 1


def _make_hub():
    """AudioHub with a fake stream factory; returns (hub, created_streams)."""
    created: List[_FakeStream] = []

    def factory(**kwargs):
        stream = _FakeStream(**kwargs)
        created.append(stream)
        return stream

    return AudioHub(stream_factory=factory), created


def _blocks(amplitude: float, count: int, size: int = BLOCK) -> List[np.ndarray]:
    return [np.full(size, amplitude, dtype=np.float32) for _ in range(count)]


def _feed(segmenter: SpeechSegmenter, frames) -> List[np.ndarray]:
    results = []
    for frame in frames:
        utterance = segmenter.feed(frame)
        if utterance is not None:
            results.append(utterance)
    return results


# ---------------------------------------------------------------------------
# AudioHub: single owner
# ---------------------------------------------------------------------------
def test_hub_opens_one_stream_and_honours_block_size():
    hub, created = _make_hub()

    assert hub.acquire("handsfree", block_ms=20) is True

    assert len(created) == 1
    assert created[0].kwargs["blocksize"] == BLOCK
    assert created[0].kwargs["samplerate"] == 16000
    assert created[0].starts == 1
    assert hub.owner == "handsfree"
    assert hub.active() is True
    state = hub.state()
    assert state["owner"] == "handsfree"
    assert state["blocksize"] == BLOCK
    assert state["block_ms"] == pytest.approx(20.0)


def test_hub_rejects_a_second_owner():
    hub, created = _make_hub()
    hub.acquire("handsfree", block_ms=20)

    with pytest.raises(RuntimeError, match="already owned"):
        hub.acquire("cli", blocksize=512)

    assert hub.owner == "handsfree"
    assert len(created) == 1
    assert created[0].active is True


def test_hub_same_owner_reacquire_is_idempotent():
    hub, created = _make_hub()
    assert hub.acquire("handsfree", block_ms=20) is True
    assert hub.acquire("handsfree", block_ms=20) is True

    assert len(created) == 1
    assert created[0].closes == 0


def test_hub_same_owner_new_block_size_restarts_the_stream():
    hub, created = _make_hub()
    hub.acquire("handsfree", block_ms=20)
    hub.acquire("handsfree", block_ms=32)

    assert len(created) == 2
    assert created[0].closes == 1
    assert created[1].kwargs["blocksize"] == 512
    assert hub.state()["blocksize"] == 512


def test_hub_release_from_wrong_owner_is_a_noop():
    hub, created = _make_hub()
    hub.acquire("handsfree", block_ms=20)

    assert hub.release("cli") is False
    assert hub.owner == "handsfree"
    assert created[0].active is True


def test_hub_release_closes_the_stream():
    hub, created = _make_hub()
    hub.acquire("handsfree", block_ms=20)

    assert hub.release("handsfree") is True
    assert hub.owner is None
    assert hub.active() is False
    assert created[0].closes == 1

    # Releasing again is harmless.
    assert hub.release("handsfree") is False


def test_hub_stop_force_closes_regardless_of_owner():
    hub, created = _make_hub()
    hub.acquire("handsfree", block_ms=20)

    hub.stop()

    assert hub.owner is None
    assert hub.stream is None
    assert created[0].closes == 1


def test_hub_requires_a_non_empty_owner():
    hub, _created = _make_hub()
    with pytest.raises(ValueError):
        hub.acquire("")


def test_hub_failed_open_rolls_back_ownership():
    def factory(**_kwargs):
        raise OSError("no device")

    hub = AudioHub(stream_factory=factory)
    with pytest.raises(OSError):
        hub.acquire("handsfree", block_ms=20)

    assert hub.owner is None
    assert hub.stream is None


# ---------------------------------------------------------------------------
# AudioHub: frame fan-out
# ---------------------------------------------------------------------------
def test_hub_fans_out_every_frame_to_all_subscribers():
    hub, _created = _make_hub()
    first: List[np.ndarray] = []
    second: List[np.ndarray] = []
    hub.subscribe(first.append)
    hub.subscribe(second.append)

    frame = np.full((BLOCK, 1), 0.25, dtype=np.float32)
    hub._on_audio(frame, BLOCK, None, None)

    assert len(first) == 1 and len(second) == 1
    assert first[0].shape == (BLOCK,)
    assert np.allclose(first[0], 0.25)
    assert hub.state()["frames"] == 1


def test_hub_isolates_a_failing_subscriber():
    hub, _created = _make_hub()
    received: List[np.ndarray] = []

    def boom(_frame):
        raise RuntimeError("subscriber bug")

    hub.subscribe(boom)
    hub.subscribe(received.append)

    hub._on_audio(np.ones(BLOCK, dtype=np.float32), BLOCK, None, None)

    assert len(received) == 1


def test_hub_unsubscribe_stops_delivery():
    hub, _created = _make_hub()
    received: List[np.ndarray] = []
    token = hub.subscribe(received.append)
    assert hub.subscriber_count == 1

    hub._on_audio(np.ones(BLOCK, dtype=np.float32), BLOCK, None, None)
    assert len(received) == 1

    assert hub.unsubscribe(token) is True
    assert hub.subscriber_count == 0

    hub._on_audio(np.ones(BLOCK, dtype=np.float32), BLOCK, None, None)
    assert len(received) == 1
    assert hub.unsubscribe(token) is False


def test_hub_subscribe_requires_a_callable():
    hub, _created = _make_hub()
    with pytest.raises(TypeError):
        hub.subscribe("not callable")


# ---------------------------------------------------------------------------
# EchoSuppressor
# ---------------------------------------------------------------------------
class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_echo_inactive_gate_returns_the_base_threshold():
    gate = EchoSuppressor()
    assert gate.active() is False
    assert gate.threshold(0.01, 0.5) == pytest.approx(0.01)


def test_echo_playback_raises_threshold_above_the_echo_level():
    gate = EchoSuppressor()
    gate.mark_started()

    threshold = gate.threshold(0.01, 0.02)

    assert gate.playing is True
    assert threshold > 0.02
    assert threshold <= gate.threshold_scale


def test_echo_floor_tracks_playback_but_lets_speech_through():
    gate = EchoSuppressor()
    gate.mark_started()
    for _ in range(5):
        gate.threshold(0.01, 0.02)

    floor = gate.echo_floor
    assert floor == pytest.approx(0.02, rel=0.2)

    quiet_threshold = gate.threshold(0.01, 0.02)
    speech_threshold = gate.threshold(0.01, 0.6)

    assert 0.02 < quiet_threshold
    assert speech_threshold < 0.6, "real speech must remain above the gate"


def test_echo_hangover_keeps_the_gate_active_then_expires():
    clock = _Clock()
    gate = EchoSuppressor(hangover_seconds=0.25, clock=clock)
    gate.mark_started()
    gate.mark_stopped()

    clock.now = 0.10
    assert gate.active() is True

    clock.now = 0.30
    assert gate.active() is False


def test_echo_threshold_never_exceeds_the_ceiling():
    gate = EchoSuppressor(threshold_scale=0.5)
    gate.mark_started()

    # An absurdly loud echo floor must still leave the assistant interruptible.
    assert gate.threshold(0.01, 10.0) <= 0.5


def test_echo_nested_playback_stays_active_until_the_outer_exit():
    gate = EchoSuppressor()
    with gate.playback():
        assert gate.playing is True
        with gate.playback():
            assert gate.playing is True
        assert gate.playing is True
    assert gate.playing is False


def test_echo_reset_clears_all_tracking_state():
    gate = EchoSuppressor()
    gate.mark_started()
    gate.threshold(0.01, 0.05)

    gate.reset()

    assert gate.playing is False
    assert gate.active() is False
    assert gate.echo_floor is None


# ---------------------------------------------------------------------------
# SpeechSegmenter (energy-only mode)
# ---------------------------------------------------------------------------
def _segmenter(**overrides) -> SpeechSegmenter:
    config = dict(
        sample_rate=16000,
        onset_ms=64,
        silence_ms=200,
        min_speech_ms=100,
        max_utterance_ms=1000,
        pre_roll_ms=0,
        rms_floor=0.004,
        speech_ratio=2.5,
    )
    config.update(overrides)
    return SpeechSegmenter(SegmenterConfig(**config), vad=False)


def test_segmenter_energy_returns_a_complete_utterance():
    segmenter = _segmenter()

    results = _feed(segmenter, _blocks(0.2, 10) + _blocks(0.0, 10))

    assert len(results) == 1
    assert results[0].size >= segmenter.cfg.samples(segmenter.cfg.min_speech_ms)
    assert segmenter.speaking is False


def test_segmenter_ignores_a_short_click():
    segmenter = _segmenter()

    results = _feed(segmenter, _blocks(0.2, 2) + _blocks(0.0, 15))

    assert results == []
    assert segmenter.speaking is False


def test_segmenter_rejects_an_utterance_below_min_speech():
    segmenter = _segmenter(min_speech_ms=500, silence_ms=200)

    # 5 voiced blocks (100 ms) open the gate, but 100 ms is below the 500 ms
    # minimum, so the completed segment must be discarded.
    results = _feed(segmenter, _blocks(0.2, 5) + _blocks(0.0, 10))

    assert results == []


def test_segmenter_caps_an_overlong_utterance():
    segmenter = _segmenter(max_utterance_ms=200)

    utterance = None
    for frame in _blocks(0.2, 30):
        utterance = segmenter.feed(frame)
        if utterance is not None:
            break

    assert utterance is not None
    assert utterance.size <= segmenter.cfg.samples(200)
    assert segmenter.speaking is False


def test_segmenter_speaking_tracks_onset_and_finish():
    segmenter = _segmenter()
    assert segmenter.speaking is False

    for frame in _blocks(0.2, 5):
        segmenter.feed(frame)
    assert segmenter.speaking is True

    for frame in _blocks(0.0, 10):
        segmenter.feed(frame)
    assert segmenter.speaking is False


def test_segmenter_reset_drops_a_partial_utterance():
    segmenter = _segmenter()
    for frame in _blocks(0.2, 5):
        segmenter.feed(frame)
    assert segmenter.speaking is True

    segmenter.reset()

    assert segmenter.speaking is False
    assert _feed(segmenter, _blocks(0.0, 10)) == []


def test_segmenter_flush_returns_partial_speech():
    segmenter = _segmenter()
    for frame in _blocks(0.2, 6):
        segmenter.feed(frame)
    assert segmenter.speaking is True

    utterance = segmenter.flush()

    assert utterance is not None
    assert segmenter.speaking is False


def test_segmenter_ignores_flat_ambient_noise():
    segmenter = _segmenter()

    assert _feed(segmenter, _blocks(0.001, 40)) == []
    assert segmenter.speaking is False


# ---------------------------------------------------------------------------
# Barge-in capture (hands-free listener)
# ---------------------------------------------------------------------------
def _barge_config(**overrides) -> HandsFreeConfig:
    config = dict(
        block_ms=20,
        silence_ms=200,
        min_speech_ms=100,
        max_utterance_ms=2000,
        pre_roll_ms=0,
    )
    config.update(overrides)
    return HandsFreeConfig(**config)


def _barge_listener(gate: EchoSuppressor, **overrides):
    calls = {"interrupt": 0}
    hub, _created = _make_hub()

    def interrupt():
        calls["interrupt"] += 1

    listener = HandsFreeListener(
        transcribe=lambda _samples: "",
        on_command=lambda _command: None,
        interrupt=interrupt,
        config=_barge_config(**overrides),
        vad=False,
        hub=hub,
        gate=gate,
    )
    return listener, calls


def test_barge_capture_returns_the_next_command_without_rewaking():
    listener, calls = _barge_listener(EchoSuppressor())
    for frame in _blocks(0.2, 10) + _blocks(0.0, 10):
        listener._queue.put(frame)

    listener._barge_monitor()

    assert listener._pending_audio is not None
    assert listener._pending_audio.size >= listener.cfg.sample_rate // 10
    assert calls["interrupt"] == 1


def test_barge_ignores_tts_echo_while_playing():
    gate = EchoSuppressor()
    gate.mark_started()
    listener, calls = _barge_listener(gate)

    # Feed the echo, then silence. None of it may open the gate.
    for frame in _blocks(0.02, 30) + _blocks(0.0, 10):
        listener._queue.put(frame)

    worker = threading.Thread(target=listener._barge_monitor, daemon=True)
    worker.start()
    time.sleep(0.4)
    listener._barge_stop.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert listener._pending_audio is None
    assert calls["interrupt"] == 0


def test_barge_still_hears_speech_over_the_echo_floor():
    gate = EchoSuppressor()
    gate.mark_started()
    listener, calls = _barge_listener(gate)

    # A few echo frames establish the floor, then clearly louder speech.
    for frame in _blocks(0.02, 5) + _blocks(0.3, 10) + _blocks(0.0, 10):
        listener._queue.put(frame)

    listener._barge_monitor()

    assert listener._pending_audio is not None
    assert calls["interrupt"] == 1


# ---------------------------------------------------------------------------
# CLI wrapper shares the hub
# ---------------------------------------------------------------------------
def test_audio_input_acquires_the_hub_as_the_cli_owner():
    hub, created = _make_hub()
    audio = AudioInput(hub=hub)

    audio.start()

    assert hub.owner == "cli"
    assert audio.is_active() is True
    assert len(created) == 1

    # Idempotent start must not reopen the stream.
    audio.start()
    assert len(created) == 1


def test_audio_input_receives_frames_and_drains_them():
    hub, _created = _make_hub()
    audio = AudioInput(hub=hub)
    audio.start()

    hub._on_audio(np.ones(BLOCK, dtype=np.float32), BLOCK, None, None)
    chunk = audio.queue.get(timeout=1.0)
    assert chunk.shape == (BLOCK,)

    hub._on_audio(np.ones(BLOCK, dtype=np.float32), BLOCK, None, None)
    audio.drain()
    assert audio.queue.empty()


def test_audio_input_stop_releases_the_hub():
    hub, created = _make_hub()
    audio = AudioInput(hub=hub)
    audio.start()

    audio.stop()

    assert hub.owner is None
    assert audio.is_active() is False
    assert created[0].closes == 1
