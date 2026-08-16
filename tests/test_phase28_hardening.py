"""
PHASE 28 HARDENING & VOICE UX POLISH TEST SUITE
================================================
Verifies P0, P1, and P2 architecture hardening, permission propagation,
URL scheme restrictions, conversational prefix stripping, and security controls.
"""
import time
import pytest
from unittest.mock import patch, MagicMock

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.router import route
from friday.intent.models import Action
from friday.tools.browser import open_website
from friday.tools.memory import remember
from friday.reasoning.local_reasoner import OllamaReasoner


def test_p0_permission_parameter_propagation():
    """Verify permissions dictionary is passed down to registry.execute in safe single-turn path."""
    perms = {"open_app": False, "search_web": True}
    cm = ConversationManager(dry_run=True, permissions=perms)
    cm.start_session()
    resp, keep = cm.handle_transcript("open chrome")
    assert "not permitted" in resp.lower() or "blocked" in resp.lower()


def test_p0_passive_confirmation_timeout():
    """Verify WAITING_FOR_CONFIRMATION auto-reverts to LISTENING after 30 seconds of inactivity."""
    cm = ConversationManager(dry_run=True)
    cm.start_session()
    cm.handle_transcript("close chrome")
    assert cm.state_machine.current_state == ConversationState.WAITING_FOR_CONFIRMATION

    # Fast forward confirmation start time by 31 seconds
    cm.context.confirmation_start_time = time.time() - 31.0
    # Access state property
    current_state = cm.state
    assert current_state == ConversationState.LISTENING
    assert cm.context.pending_intent is None


def test_p0_url_scheme_restriction():
    """Verify open_website rejects file:/// and non-http/https schemes."""
    res_file = open_website("file:///C:/Windows/system32/cmd.exe", dry_run=True)
    assert res_file["success"] is False
    assert "Blocked scheme" in res_file["message"] or "Only http and https" in res_file["message"]

    res_http = open_website("youtube", dry_run=True)
    assert res_http["success"] is True


def test_p1_conversational_prefix_stripping():
    """Verify router strips conversational prefixes deterministically without LLM fallback."""
    intent1 = route("can you please open chrome")
    assert intent1.action == Action.OPEN_APP
    assert intent1.target == "chrome"

    intent2 = route("hey friday search python tutorials")
    assert intent2.action == Action.SEARCH_WEB
    assert intent2.target == "python tutorials"

    intent3 = route("could you tell me the time")
    assert intent3.action == Action.GET_TIME

    intent4 = route("i want to find my resume")
    assert intent4.action == Action.FIND_FILE
    assert intent4.target == "resume"


def test_p1_ollama_socket_timeout():
    """Verify OllamaReasoner uses 3.0s timeout in request call."""
    reasoner = OllamaReasoner()
    with patch.object(reasoner, "is_available", return_value=True):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = Exception("Timeout simulated")
            res = reasoner.request("test", MagicMock())
            assert res == {"type": "unknown"}
            assert mock_urlopen.call_count == 1
            _, kwargs = mock_urlopen.call_args
            assert kwargs.get("timeout") == 3.0


def test_p2_audio_and_media_intents():
    """Verify SET_VOLUME, MUTE_AUDIO, UNMUTE_AUDIO, and PAUSE_MEDIA intents and tool dispatches."""
    intent_vol = route("set volume to 75%")
    assert intent_vol.action == Action.SET_VOLUME
    assert intent_vol.target == "75"

    intent_mute = route("mute audio")
    assert intent_mute.action == Action.MUTE_AUDIO

    intent_unmute = route("unmute sound")
    assert intent_unmute.action == Action.UNMUTE_AUDIO

    intent_pause = route("pause media")
    assert intent_pause.action == Action.PAUSE_MEDIA

    cm = ConversationManager(dry_run=True)
    cm.start_session()
    resp_vol, _ = cm.handle_transcript("set volume to 50%")
    assert "50" in resp_vol and "volume" in resp_vol.lower()

    resp_mute, _ = cm.handle_transcript("mute audio")
    assert "mut" in resp_mute.lower()


def test_p2_expanded_secret_scrubbing():
    """Verify SSN, credit card numbers, GitHub tokens, and Bearer tokens are filtered in memory."""
    res_ssn = remember("My SSN is 123-45-6789", dry_run=True)
    assert res_ssn["success"] is False
    assert "secret" in res_ssn["message"].lower() or "sensitive" in res_ssn["message"].lower()

    res_card = remember("Card number 4111-1111-1111-1111", dry_run=True)
    assert res_card["success"] is False

    res_bearer = remember("Token is Bearer secret_auth_token_123456789", dry_run=True)
    assert res_bearer["success"] is False
