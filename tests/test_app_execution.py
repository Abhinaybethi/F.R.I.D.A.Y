"""
UNIT TEST — App Execution Pipeline
===================================
Tests the full path: transcript → route → resolve → registry → apps tool.
Covers:
  - Dry-run responses carry [DRY RUN] tag (no false-success)
  - Unknown app returns clear error, not false "Opening X."
  - Brave is recognized as a valid app
  - close_app dry-run carries [DRY RUN] tag
  - Executable-not-found returns truthful failure (real mode)
  - Subprocess exception returns truthful failure (real mode)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from unittest.mock import patch

from friday.core.conversation import ConversationManager, ConversationState
from friday.intent.models import Action, Intent
from friday.intent.resolver import resolve_app
from friday.tools import registry
from friday.tools.apps import open_app, close_app

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}


class TestDryRunResponsesContainTag(unittest.TestCase):
    """Dry-run responses must never impersonate real success."""

    def test_open_app_dry_run_response(self):
        result = open_app("chrome", dry_run=True)
        self.assertTrue(result["success"])
        self.assertIn("[DRY RUN]", result["message"])
        self.assertIn("[DRY RUN]", result["spoken_message"])
        self.assertEqual(result["message"], result["spoken_message"])

    def test_close_app_dry_run_response(self):
        result = close_app("chrome", dry_run=True)
        self.assertTrue(result["success"])
        self.assertIn("[DRY RUN]", result["message"])
        self.assertIn("[DRY RUN]", result["spoken_message"])
        self.assertEqual(result["message"], result["spoken_message"])

    def test_conversation_dry_run_does_not_say_opening(self):
        """Conversation manager dry-run must not return bare 'Opening X.'."""
        cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
        cm.start_session()
        resp, keep = cm.handle_transcript("open chrome")
        self.assertNotEqual(resp, "Opening Chrome.")
        self.assertIn("[DRY RUN]", resp)
        self.assertIn("Chrome", resp)

    def test_close_conversation_dry_run_tagged(self):
        """Close app in dry-run must return tagged message."""
        cm = ConversationManager(dry_run=True, allow_real_execution=False, permissions=_ALL_ENABLED)
        cm.start_session()
        cm.handle_transcript("close chrome")
        resp_yes, _ = cm.handle_transcript("yes")
        self.assertIn("[DRY RUN]", resp_yes)
        self.assertIn("Chrome", resp_yes)


class TestUnknownAppReturnsClearError(unittest.TestCase):
    """Unknown app must fail clearly — never return false success."""

    def test_unknown_app_tool_returns_error(self):
        result = open_app("nonexistent_foo", dry_run=True)
        self.assertFalse(result["success"])
        self.assertIn("Unknown app", result["message"])

    def test_unknown_app_conversation_response(self):
        cm = ConversationManager(dry_run=True, permissions=_ALL_ENABLED)
        cm.start_session()
        resp, keep = cm.handle_transcript("open nonexistent foo")
        self.assertIn("didn't understand", resp.lower())


class TestBraveRecognition(unittest.TestCase):
    """Brave browser is recognized by resolver and app tool."""

    def test_resolve_app_brave(self):
        name, conf = resolve_app("brave")
        self.assertEqual(name, "brave")
        self.assertGreater(conf, 0.0)

    def test_open_app_brave_known(self):
        result = open_app("brave", dry_run=True)
        self.assertTrue(result["success"])
        self.assertIn("Brave", result["message"])
        self.assertIn("[DRY RUN]", result["spoken_message"])

    def test_close_app_brave_known(self):
        result = close_app("brave", dry_run=True)
        self.assertTrue(result["success"])
        self.assertIn("Brave", result["message"])


class TestRealModeFailurePaths(unittest.TestCase):
    """Real execution mode: executable-not-found returns truthful failure."""

    @patch("friday.tools.apps._find_executable", return_value=None)
    def test_executable_not_found(self, mock_find):
        result = open_app("chrome", dry_run=False)
        self.assertFalse(result["success"])
        self.assertIn("Could not locate", result["message"])

    @patch("friday.tools.apps.os.startfile", side_effect=PermissionError("access denied"))
    @patch("friday.tools.apps._find_executable", return_value=r"C:\fake\chrome.exe")
    def test_os_startfile_exception(self, mock_find, mock_startfile):
        result = open_app("chrome", dry_run=False)
        self.assertFalse(result["success"])
        self.assertIn("Failed to open", result["message"])
        self.assertIn("access denied", result["message"])


class TestRegistryExecDryRun(unittest.TestCase):
    """Registry.execute in dry_run must return dry-run outcome."""

    def test_registry_dry_run_outcome(self):
        intent = Intent(action=Action.OPEN_APP, target="chrome",
                        intent_confidence=1.0, target_confidence=1.0)
        outcome = registry.execute(intent, dry_run=True, allow_real_execution=False,
                                   permissions=_ALL_ENABLED)
        self.assertTrue(outcome.is_success)
        self.assertIn("[DRY RUN]", outcome.user_message)
        self.assertIn("[DRY RUN]", outcome.spoken_message)
        self.assertIn("[DRY RUN]", outcome.get("message", ""))
        self.assertIn("[DRY RUN]", outcome.get("spoken_message", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
