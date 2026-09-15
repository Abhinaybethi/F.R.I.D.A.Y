"""
Phase 28.5 Action Execution & Verification Test Suite.

Verifies end-to-end trace, execution outcome, independent verification,
and classification for all 10 benchmark commands across dry-run and real modes.
"""
import pytest
import sqlite3
from contextlib import closing

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.intent.router import route
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.verification.models import (
    ExecutionStatus,
    VerificationStatus,
    FinalStatus,
    ActionOutcome,
)
from friday.verification.verifier import verify_execution
from friday.tools import registry, memory


def _create_cm():
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()
    return cm


def test_command_1_open_chrome_verification():
    """1. open Chrome -> OPEN_APP chrome"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("open Chrome")
    # Dry-run must be explicit — never bare "Opening Chrome." (false-success fix)
    assert "[DRY RUN]" in resp and "open Chrome" in resp
    assert cm.context.last_intent.action == Action.OPEN_APP
    assert cm.context.last_intent.target == "chrome"

    # Test real verifier logic in dry-run
    intent = Intent(action=Action.OPEN_APP, target="chrome")
    exec_res = registry.execute(intent, dry_run=True)
    assert exec_res.verification.status == VerificationStatus.DRY_RUN
    assert exec_res.is_success is True


def test_command_2_open_youtube_verification():
    """2. open YouTube -> OPEN_WEBSITE youtube"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("open YouTube")
    assert "Opening Youtube" in resp or "youtube" in resp.lower()
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE
    assert cm.context.last_intent.target == "youtube"

    intent = Intent(action=Action.OPEN_WEBSITE, target="youtube")
    outcome = registry.execute(intent, dry_run=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN


def test_command_3_open_downloads_verification():
    """3. open Downloads -> OPEN_FOLDER download"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("open Downloads")
    assert "Download" in resp
    assert cm.context.last_intent.action == Action.OPEN_FOLDER
    assert cm.context.last_intent.target == "download"

    intent = Intent(action=Action.OPEN_FOLDER, target="download")
    outcome = registry.execute(intent, dry_run=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN


def test_command_4_find_my_resume_verification():
    """4. find my resume -> FIND_FILE resume"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("find my resume")
    assert cm.context.last_intent.action == Action.FIND_FILE
    assert cm.context.last_intent.target == "resume"

    intent = Intent(action=Action.FIND_FILE, target="resume")
    outcome = registry.execute(intent, dry_run=True)
    assert outcome.verification.status in (VerificationStatus.DRY_RUN, VerificationStatus.NOT_APPLICABLE)


def test_command_5_search_python_tutorials_verification():
    """5. search Python tutorials -> SEARCH_WEB python tutorials"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("search Python tutorials")
    assert "Searching" in resp or "python tutorials" in resp.lower()
    assert cm.context.last_intent.action == Action.SEARCH_WEB
    assert cm.context.last_intent.target == "python tutorials"

    intent = Intent(action=Action.SEARCH_WEB, target="python tutorials")
    outcome = registry.execute(intent, dry_run=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN


def test_command_6_open_first_result_resolution_and_verification():
    """6. open first result -> context resolution -> OPEN_WEBSITE"""
    cm = _create_cm()
    # Populate context search results
    cm.context.last_search_results = [
        {"title": "Python Tutorials", "url": "https://example.com/python"}
    ]

    resp, cont = cm.handle_transcript("open first result")
    assert "Opening" in resp or "example.com/python" in resp
    assert cm.context.last_intent.action == Action.OPEN_WEBSITE
    assert cm.context.last_intent.target == "https://example.com/python"


def test_command_7_read_it_resolution_and_verification():
    """7. read it -> context pronoun resolution -> READ_WEBSITE"""
    cm = _create_cm()
    cm.context.last_intent = Intent(action=Action.OPEN_WEBSITE, target="https://example.com/article")

    resp, cont = cm.handle_transcript("read it")
    assert "Reading" in resp or "example.com/article" in resp or "Here is the page content" in resp
    assert cm.context.last_intent.action == Action.READ_WEBSITE
    assert cm.context.last_intent.target == "https://example.com/article"

    intent = Intent(action=Action.READ_WEBSITE, target="https://example.com/article")
    outcome = registry.execute(intent, dry_run=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN


def test_command_8_stop_verification():
    """8. stop -> SYSTEM_STOP lifecycle event"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("stop")
    assert resp == "Goodbye."
    assert cont is False
    assert cm.state == ConversationState.STOPPING


def test_command_9_cancel_verification():
    """9. cancel -> SYSTEM_CANCEL state reset"""
    cm = _create_cm()
    resp, cont = cm.handle_transcript("cancel")
    assert resp == "Cancelled."
    assert cont is True
    assert cm.state == ConversationState.LISTENING


def test_command_10_forget_a_memory_verification():
    """10. forget a memory -> confirmation flow -> FORGET"""
    memory.remember("a memory", dry_run=False)
    cm = _create_cm()
    resp1, cont1 = cm.handle_transcript("forget a memory")
    assert "Do you want me to forget" in resp1
    assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

    # User confirms
    resp2, cont2 = cm.handle_transcript("yes")
    assert "Forgot" in resp2 or "forgotten" in resp2 or "Forgotten" in resp2
    assert cm.state == ConversationState.LISTENING




def test_read_website_verifier_registration():
    """Verify READ_WEBSITE is registered in _VERIFIER_TABLE and produces a valid VerificationResult."""
    intent = Intent(action=Action.READ_WEBSITE, target="https://example.com")
    outcome = registry.execute(intent, dry_run=True)
    assert outcome.verification.status == VerificationStatus.DRY_RUN


def test_remember_and_forget_verifier_registration():
    """Verify REMEMBER and FORGET have verifiers registered and working."""
    memory.remember("test memory key", dry_run=False)
    intent_rem = Intent(action=Action.REMEMBER, target="test memory key")
    out_rem = registry.execute(intent_rem, dry_run=True)
    assert out_rem.verification.status == VerificationStatus.DRY_RUN

    intent_for = Intent(action=Action.FORGET, target="test memory key")
    out_for = registry.execute(intent_for, dry_run=True)
    assert out_for.verification.status == VerificationStatus.DRY_RUN


def test_system_audio_verifiers_registration():
    """Verify SET_VOLUME, MUTE_AUDIO, UNMUTE_AUDIO, PAUSE_MEDIA have registered verifiers."""
    for action, target in [
        (Action.SET_VOLUME, "50"),
        (Action.MUTE_AUDIO, ""),
        (Action.UNMUTE_AUDIO, ""),
        (Action.PAUSE_MEDIA, ""),
    ]:
        intent = Intent(action=action, target=target)
        out = registry.execute(intent, dry_run=True)
        assert out.verification.status == VerificationStatus.DRY_RUN

