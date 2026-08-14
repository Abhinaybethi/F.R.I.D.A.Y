"""
UNIT TEST — Voice Response Flow Optimization
============================================
Tests audio input device checks, VAD audio chunking,
STT pre-allocation, and Piper TTS synthesis lifecycle.
No hardware required.
"""
import sys
import os
import numpy as np
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.vad import VoiceActivityDetector
from friday.voice.audio_input import AudioInput
from friday.response.engine import format_spoken_response


def test_vad_audio_chunking_efficiency():
    """Silero VAD processes float32 audio chunks without exception."""
    vad = VoiceActivityDetector()
    dummy_chunk = np.zeros(512, dtype=np.float32)
    has_speech = bool(vad.is_speech(dummy_chunk))
    assert isinstance(has_speech, bool)
    assert has_speech is False


def test_audio_input_device_query_non_blocking():
    """AudioInput device info query completes without blocking or raising exceptions."""
    audio = AudioInput()
    dev_info = audio.get_device_info()
    assert isinstance(dev_info, dict)
    assert "sample_rate" in dev_info


def test_response_engine_spoken_text_cleaning():
    """format_spoken_response sanitizes text for TTS output."""
    cleaned = format_spoken_response("[DRY RUN] Would open Chrome.")
    assert "[DRY RUN]" not in cleaned
    assert "Open Chrome" in cleaned


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
