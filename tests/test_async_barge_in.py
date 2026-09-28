"""
UNIT TEST — Asynchronous Voice Session & Barge-In Listener (Phase 14 P0)
========================================================================
Tests AsyncVoiceSessionManager background VAD thread during TTS output.
Also verifies barge-in continuity: interrupt audio captured by the monitor
is retained and re-seeded into listen_once() so the user's interruption is
not lost to AudioInput.drain().
No Ollama required. All deterministic.
"""
import sys
import os
import time
import queue
import threading
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from friday.voice.async_session import AsyncVoiceSessionManager
from friday.voice.text_to_speech import TextToSpeech
from friday.voice.session_manager import VoiceSessionManager


class DummySessionManager:
    def __init__(self):
        self.vad = None
        self.audio_input = None


class ScriptedVAD:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0
        self.resets = 0

    def reset_states(self):
        self.resets += 1

    def is_speech(self, chunk):
        self.calls += 1
        if not self.decisions:
            return False
        return self.decisions.pop(0)


class FakeQueueAudio:
    def __init__(self, chunks):
        self.queue = queue.Queue()
        for c in chunks:
            self.queue.put(c)
        self.sample_rate = 16000
        self.chunk_size = 512
        self._drain_calls = 0

    def is_active(self):
        return True

    def drain(self):
        self._drain_calls += 1

    def read_chunks(self):
        while not self.queue.empty():
            yield self.queue.get()


class FakeStt:
    def transcribe_detailed(self, audio_data):
        from types import SimpleNamespace
        meta = SimpleNamespace(
            avg_logprob=0.5, no_speech_prob=0.1, quality_ok=True,
        )
        return "okay anyway", 1.0, meta


class FakeDebugSaver:
    def save(self, audio, rate):
        return None

    def maybe_playback(self, path):
        return None


def _chunks(n):
    return [np.zeros(512, dtype=np.float32) for _ in range(n)]


def test_async_voice_session_start_stop():
    """AsyncVoiceSessionManager starts and stops background VAD thread cleanly."""
    tts = TextToSpeech(engine="piper")
    dummy_session = DummySessionManager()
    async_session = AsyncVoiceSessionManager(dummy_session, tts)

    assert async_session.is_barge_in_triggered() is False
    async_session.start_barge_in_listener()
    time.sleep(0.1)
    async_session.stop_barge_in_listener()
    assert async_session.is_barge_in_triggered() is False


def test_monitor_captures_interrupt_audio_past_trigger():
    """The monitor keeps the interrupt head + tail and stops TTS immediately."""
    tts = object.__new__(TextToSpeech)
    tts.abort_event = threading.Event()
    tts._is_speaking = True

    chunk_list = _chunks(5)
    vad = ScriptedVAD([True, False, False, False, False])
    sm = DummySessionManager()
    sm.vad = vad
    sm.audio = FakeQueueAudio(chunk_list)

    mon = AsyncVoiceSessionManager(sm, tts)
    mon._monitor_loop()

    assert tts.abort_event.is_set(), "TTS stop must be invoked on barge-in"
    assert mon.is_barge_in_triggered() is True
    assert len(mon._barge_in_chunks) == 5, "first speech chunk must be retained"

    captured = mon.take_barge_in_audio()
    assert len(captured) == 5
    assert mon.is_barge_in_triggered() is False
    assert mon._barge_in_chunks == []


def test_monitor_without_speech_never_triggers():
    tts = object.__new__(TextToSpeech)
    tts.abort_event = threading.Event()
    tts._is_speaking = True

    sm = DummySessionManager()
    sm.vad = ScriptedVAD([False, False, False])
    sm.audio = FakeQueueAudio(_chunks(3))

    mon = AsyncVoiceSessionManager(sm, tts)
    mon._monitor_loop()

    assert mon.is_barge_in_triggered() is False
    assert mon.take_barge_in_audio() == []


def test_listen_once_seeds_captured_barge_in_audio_without_draining():
    """listen_once(initial_chunks=...) skips drain() and transcribes seed + tail."""
    sm = object.__new__(VoiceSessionManager)
    sm.audio = FakeQueueAudio(_chunks(2))
    sm.vad = ScriptedVAD([])
    sm.stt = FakeStt()
    sm._debug_saver = FakeDebugSaver()
    sm.max_silence = 2.0
    sm.max_listen = 10.0

    seed = _chunks(3)
    text = sm.listen_once(initial_chunks=seed)

    assert text == "okay anyway"
    assert sm.audio._drain_calls == 0, "drain must be skipped for seeded listens"
    assert sm.vad.calls == 5, "3 seed + 2 tail chunks must flow through VAD state"


def test_listen_once_drains_when_no_captured_audio():
    """Without captured audio the old drain-first behaviour is preserved."""
    sm = object.__new__(VoiceSessionManager)
    sm.audio = FakeQueueAudio(_chunks(2))
    sm.vad = ScriptedVAD([])
    sm.stt = FakeStt()
    sm._debug_saver = FakeDebugSaver()
    sm.max_silence = 2.0
    sm.max_listen = 10.0

    text = sm.listen_once()
    assert text == ""
    assert sm.audio._drain_calls == 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
