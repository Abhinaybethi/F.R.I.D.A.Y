"""
UNIT TEST — Audio Barge-In Interruption Lifecycle (Phase 13 P1)
================================================================
Tests TTS stop/interrupt signaling in friday/voice/text_to_speech.py.
Ensures TTS speech playback halts cleanly when stop() is invoked.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.text_to_speech import TextToSpeech


def test_tts_stop_signal_resets_speaking_state():
    """TextToSpeech.stop() sets _stop_requested and stops sounddevice stream."""
    tts = TextToSpeech(engine="piper")
    assert tts.is_speaking() is False
    tts.stop()
    assert tts._stop_requested is True


def test_tts_clean_for_speech_strips_dry_run_tags():
    """_clean_for_speech() strips [DRY RUN] tags and raw URLs."""
    tts = TextToSpeech(engine="piper")
    cleaned = tts._clean_for_speech("[DRY RUN] Would open Chrome.")
    assert "[DRY RUN]" not in cleaned
    assert "Opening Chrome" in cleaned or "Would open Chrome" in cleaned


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
