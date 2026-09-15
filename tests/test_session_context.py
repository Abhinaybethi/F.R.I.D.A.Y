"""
Session / conversation context unit tests.

Verifies voice action context fields (last_opened_application,
last_opened_website, active_media) are populated and that screen questions and
knowledge questions take the truthful / chat paths.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.core.conversation import ConversationManager


class RecordingReasoner:
    def __init__(self):
        self.requests = []
        self.modes = []

    def is_available(self):
        return True

    def request(self, transcript, context, mode="action"):
        self.requests.append(transcript)
        self.modes.append(mode)
        return {"type": "response", "text": f"You asked about: {transcript}", "confidence": 0.9}

    def health(self):
        return "ok"

    def close(self):
        pass


def _cm(reasoner=None):
    cm = ConversationManager(dry_run=True, allow_real_execution=False, reasoner=reasoner or RecordingReasoner())
    cm.start_session()
    return cm


def test_open_app_tracks_last_opened_application():
    cm = _cm()
    resp, _ = cm.handle_transcript("open chrome")
    assert cm.context.last_opened_application == "chrome"
    assert "chrome" in resp.lower() or "[dry run]" in resp.lower()


def test_open_website_tracks_last_opened_website():
    cm = _cm()
    resp, _ = cm.handle_transcript("open youtube")
    assert cm.context.last_opened_website == "youtube"
    assert "youtube" in resp.lower()


def test_play_video_tracks_active_media():
    cm = _cm()
    resp, _ = cm.handle_transcript("play kalyani song on youtube")
    assert cm.context.active_media == "kalyani song"
    assert cm.context.last_search_query == "kalyani song"


def test_play_it_resolves_via_active_media():
    cm = _cm()
    cm.handle_transcript("play kalyani song on youtube")
    resp2, _ = cm.handle_transcript("play it")
    assert "kalyani song" in resp2.lower(), "Follow-up 'play it' must reuse last media query"
    assert "chrome" not in resp2.lower()


def test_screen_question_is_truthful(run_reasoner=None):
    reasoner = RecordingReasoner()
    cm = _cm(reasoner)
    resp, _ = cm.handle_transcript("what is on my screen")
    assert "don't currently have access to your screen" in resp.lower()
    assert reasoner.requests == [], "Screen questions must not invoke the reasoner"


def test_knowledge_question_uses_chat_mode():
    reasoner = RecordingReasoner()
    cm = _cm(reasoner)
    resp, _ = cm.handle_transcript("what is java")
    assert reasoner.requests == ["what is java"], "Knowledge questions must reach the reasoner"
    assert reasoner.modes == ["chat"], "Knowledge questions must use CHAT mode"
    assert "java" in resp.lower() or "didn't understand" in resp.lower()


def test_deterministic_command_never_invokes_reasoner():
    reasoner = RecordingReasoner()
    cm = _cm(reasoner)
    cm.handle_transcript("open chrome")
    assert reasoner.requests == [], "Deterministic commands must bypass the reasoner"
    assert cm.context.last_opened_application == "chrome"