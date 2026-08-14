"""
UNIT TEST — Asynchronous Voice Session & Barge-In Listener (Phase 14 P0)
========================================================================
Tests AsyncVoiceSessionManager background VAD thread during TTS output.
No Ollama required. All deterministic.
"""
import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.async_session import AsyncVoiceSessionManager
from friday.voice.text_to_speech import TextToSpeech


class DummySessionManager:
    def __init__(self):
        self.vad = None
        self.audio_input = None


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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
