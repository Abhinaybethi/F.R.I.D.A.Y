"""
UNIT TEST — Greetings, YouTube deterministic commands & contextual follow-ups.
No reasoner, no browser network calls required (dry_run=True everywhere).
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest

from friday.core.conversation import ConversationManager
from friday.intent.models import Action, Intent
from friday.intent.router import route
from friday.planning.context_resolver import resolve_context, ShortTermContext
from friday.tools.browser import play_youtube


class TestGreetings(unittest.TestCase):
    """Deterministic greetings never fall through to 'didn't understand'."""

    def test_router_greeting(self):
        for text in ("hi", "hello", "hey", "good morning", "good evening"):
            intent = route(text)
            self.assertEqual(intent.action, Action.GREETING, text)

    def test_conversation_greeting_response(self):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()
        resp, keep = cm.handle_transcript("hi")
        self.assertNotIn("didn't understand", resp.lower())
        self.assertIn("Hello", resp)
        self.assertTrue(keep)

    def test_hello_never_recall(self):
        intent = route("hello")
        self.assertEqual(intent.action, Action.GREETING)


class TestYouTubeCommands(unittest.TestCase):
    """'play X on youtube' routes deterministically to PLAY_VIDEO."""

    def test_router_play_on_youtube(self):
        intent = route("play kalyani song on youtube")
        self.assertEqual(intent.action, Action.PLAY_VIDEO)
        self.assertEqual(intent.target, "kalyani song")
        self.assertGreaterEqual(intent.confidence, 0.85)

    def test_router_play_plain(self):
        intent = route("play despacito")
        self.assertEqual(intent.action, Action.PLAY_VIDEO)
        self.assertEqual(intent.target, "despacito")

    def test_router_search_on_youtube(self):
        intent = route("search for kalyani song on youtube")
        self.assertEqual(intent.action, Action.PLAY_VIDEO)
        self.assertEqual(intent.target, "kalyani song")

    def test_conversation_play_dry_run(self):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()
        resp, keep = cm.handle_transcript("play kalyani song on youtube")
        self.assertIn("[DRY RUN]", resp)
        self.assertIn("kalyani song", resp.lower())


class TestPlayYouTubeTool(unittest.TestCase):
    """play_youtube builds the correct search URL and stays truthful."""

    def test_dry_run_builds_youtube_search_url(self):
        result = play_youtube("kalyani song", dry_run=True)
        self.assertTrue(result["success"])
        self.assertIn("youtube.com/results", result["url"])
        self.assertIn("kalyani+song", result["url"])
        self.assertFalse(result.get("executed", False))
        self.assertTrue(result.get("dry_run", False))
        # Never claims playback started
        self.assertNotIn("playing", result["spoken_message"].lower())

    def test_real_execution_opens_browser(self):
        with unittest.mock.patch("friday.tools.browser.webbrowser.open") as mock_open:
            result = play_youtube("despacito", dry_run=False)
        mock_open.assert_called_once()
        self.assertTrue(result["success"])
        self.assertTrue(result.get("executed", True))
        self.assertIn("despacito", result["url"])

    def test_empty_query_returns_failure(self):
        result = play_youtube("", dry_run=True)
        self.assertFalse(result["success"])


class TestPlayItFollowUp(unittest.TestCase):
    """'play it' resolves to the previous YouTube/media query."""

    def test_context_resolver_play_it(self):
        ctx = ShortTermContext(
            last_search_query="kalyani song",
            last_search_results=[],
            last_action=Action.PLAY_VIDEO,
        )
        resolved, err = resolve_context("play it", ctx)
        self.assertEqual(err, "")
        self.assertEqual(resolved, "play kalyani song on youtube")

    def test_conversation_follow_up_uses_previous_query(self):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()
        resp1, _ = cm.handle_transcript("play kalyani song on youtube")
        self.assertIn("kalyani song", resp1.lower())
        resp2, _ = cm.handle_transcript("play it")
        self.assertIn("kalyani song", resp2.lower())
        # Must NOT open Chrome
        self.assertNotIn("chrome", resp2.lower())

    def test_play_it_without_context_returns_helpful_error(self):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()
        resp, _ = cm.handle_transcript("play it")
        # No prior context: should not crash, should be truthful
        self.assertIsInstance(resp, str)
        self.assertTrue(len(resp) > 0)


class TestTruthfulness(unittest.TestCase):
    """ISSUE 10 — tools never claim success without evidence."""

    def test_open_website_false_return_is_reported(self):
        # webbrowser.open() returning False must NOT be reported as success
        with unittest.mock.patch("friday.tools.browser.webbrowser.open", return_value=False):
            from friday.tools.browser import open_website
            result = open_website("youtube", dry_run=False)
        self.assertFalse(result["success"])
        self.assertIn("did not confirm", result["message"].lower())

    def test_open_website_exception_is_reported(self):
        with unittest.mock.patch(
            "friday.tools.browser.webbrowser.open",
            side_effect=RuntimeError("browser crashed"),
        ):
            from friday.tools.browser import open_website
            result = open_website("youtube", dry_run=False)
        self.assertFalse(result["success"])

    def test_open_app_reports_executable_evidence(self):
        from friday.tools.apps import open_app, _find_executable
        exe = _find_executable("chrome")
        if not exe:
            self.skipTest("Chrome not installed on this machine")
        with unittest.mock.patch("friday.tools.apps.os.startfile") as mock_start:
            result = open_app("chrome", dry_run=False)
        mock_start.assert_called_once()
        self.assertTrue(result["success"])
        # Real-execution message carries the executable evidence
        self.assertIn(exe, result["message"])

    def test_close_app_reports_closed_processes(self):
        from friday.tools.apps import close_app
        with unittest.mock.patch("psutil.process_iter", return_value=[]):
            result = close_app("notepad", dry_run=False)
        self.assertTrue(result["success"])
        # Missing process must be stated, not claimed as closed
        self.assertIn("not running", result["message"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)