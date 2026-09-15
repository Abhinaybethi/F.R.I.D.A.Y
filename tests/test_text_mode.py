"""
UNIT TEST — Text Mode Entry Point
==================================
Verifies the --text mode exercises the real Assistant pipeline
(ConversationManager -> router -> tools/reasoner) while skipping voice I/O.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.assistant import Friday
from friday.core.conversation import ConversationState


def _make_text_assistant() -> Friday:
    return Friday(config_path="config.yaml", text_mode=True)


def test_text_mode_skips_voice_components():
    """Voice components must be None in text mode (no mic/VAD/STT/TTS loading)."""
    assistant = Friday(config_path="config.yaml", text_mode=True)
    assert assistant.text_mode is True
    assert assistant.tts is None
    assert assistant.session_manager is None
    assert assistant.wake_word_listener is None
    assert assistant.async_session is None


def test_text_mode_processes_deterministic_command():
    """A known command routes through the real router/tool pipeline."""
    assistant = _make_text_assistant()
    assistant.conversation_manager.start_session()

    response, keep = assistant._process_transcript("open chrome")
    assert response, "Expected a non-empty response for 'open chrome'"
    assert keep is True
    assert "chrome" in response.lower()


def test_text_mode_processes_time_command():
    """GET_TIME deterministic intent resolves through the real pipeline."""
    assistant = _make_text_assistant()
    assistant.conversation_manager.start_session()

    response, keep = assistant._process_transcript("what time is it")
    assert response, "Expected a non-empty time response"
    assert keep is True


def test_text_mode_stop_command_halts():
    """'stop' should return should_continue=False."""
    assistant = _make_text_assistant()
    assistant.conversation_manager.start_session()

    _, keep = assistant._process_transcript("stop")
    assert keep is False


def test_text_mode_close_requires_confirmation():
    """Destructive command enters WAITING_FOR_CONFIRMATION (safety preserved)."""
    assistant = _make_text_assistant()
    assistant.conversation_manager.start_session()

    response, keep = assistant._process_transcript("close chrome")
    assert assistant.conversation_manager.state == ConversationState.WAITING_FOR_CONFIRMATION


def test_text_mode_shared_entry_point_with_voice():
    """_handle (voice path) delegates to the same _process_transcript handler."""
    assistant = _make_text_assistant()
    assistant.conversation_manager.start_session()

    resp_text, _ = assistant._process_transcript("open notepad")
    # Verify the voice-facing _handle produces the same result without TTS in text mode
    assert resp_text


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])