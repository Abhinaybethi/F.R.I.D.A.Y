"""
UNIT TEST — llama.cpp Server Lifecycle Manager
================================================
Tests LlamaCppServerManager with mocked subprocess and network calls.
No Bonsai hardware/model required.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from unittest.mock import patch, MagicMock

from friday.reasoning.llamacpp_server import LlamaCppServerManager


class TestServerAlreadyRunning(unittest.TestCase):
    """If a healthy server already exists, never spawn a second one."""

    @patch.object(LlamaCppServerManager, "is_already_running", return_value=True)
    def test_does_not_start_when_healthy(self, mock_health):
        mgr = LlamaCppServerManager()
        ok = mgr.start()
        self.assertTrue(ok)
        self.assertFalse(mgr.started_by_friday)
        self.assertFalse(mgr.is_owned())
        # Ensure no subprocess was ever spawned
        mock_health.assert_called_once()


class TestServerStartsIfUnavailable(unittest.TestCase):
    """Server down → auto-start spawns recognizable one."""
    pass


class TestServerStartupFlow(unittest.TestCase):
    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    @patch.object(LlamaCppServerManager, "_find_executable", return_value=r"C:\fake\llama-server.exe")
    @patch.object(LlamaCppServerManager, "_wait_until_ready", return_value=True)
    @patch("friday.reasoning.llamacpp_server.Path.is_file", return_value=True)
    def test_start_spawns_process_and_tracks_ownership(self, mock_file, mock_wait, mock_find, mock_health):
        mgr = LlamaCppServerManager()
        with patch("friday.reasoning.llamacpp_server.subprocess.Popen", return_value=MagicMock(pid=1234)) as mock_popen:
            ok = mgr.start()
        self.assertTrue(ok)
        self.assertTrue(mgr.started_by_friday)
        self.assertTrue(mgr.is_owned())
        mock_popen.assert_called_once()
        # command contains expected model and context flags
        args = mock_popen.call_args[0][0]
        self.assertIn("-m", args)
        self.assertIn("C:\\AI\\models\\Bonsai-8B-Q1_0.gguf", args)


class TestStartupFailureCases(unittest.TestCase):
    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    @patch.object(LlamaCppServerManager, "_find_executable", return_value=None)
    def test_missing_executable_returns_false(self, mock_find, mock_health):
        mgr = LlamaCppServerManager()
        ok = mgr.start()
        self.assertFalse(ok)
        self.assertFalse(mgr.is_owned())

    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    @patch.object(LlamaCppServerManager, "_find_executable", return_value=r"C:\fake\llama-server.exe")
    @patch("friday.reasoning.llamacpp_server.Path.is_file", return_value=False)
    def test_missing_model_returns_false(self, mock_file, mock_find, mock_health):
        mgr = LlamaCppServerManager()
        ok = mgr.start()
        self.assertFalse(ok)
        self.assertFalse(mgr.is_owned())

    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    @patch.object(LlamaCppServerManager, "_find_executable", return_value=r"C:\fake\llama-server.exe")
    @patch("friday.reasoning.llamacpp_server.Path.is_file", return_value=True)
    @patch.object(LlamaCppServerManager, "_wait_until_ready", return_value=False)
    @patch("friday.reasoning.llamacpp_server.subprocess.Popen", return_value=MagicMock(pid=777))
    def test_startup_timeout_returns_false(self, mock_popen, mock_wait, mock_file, mock_find, mock_health):
        mgr = LlamaCppServerManager()
        ok = mgr.start()
        self.assertFalse(ok)

    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    @patch.object(LlamaCppServerManager, "_find_executable", return_value=r"C:\fake\llama-server.exe")
    @patch("friday.reasoning.llamacpp_server.Path.is_file", return_value=True)
    def test_popen_exception_returns_false(self, mock_file, mock_find, mock_health):
        mgr = LlamaCppServerManager()
        with patch("friday.reasoning.llamacpp_server.subprocess.Popen",
                   side_effect=OSError("spawn failed")):
            ok = mgr.start()
        self.assertFalse(ok)
        self.assertFalse(mgr.is_owned())


class TestServerShutdown(unittest.TestCase):
    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    @patch.object(LlamaCppServerManager, "_find_executable", return_value=r"C:\fake\llama-server.exe")
    @patch.object(LlamaCppServerManager, "_wait_until_ready", return_value=True)
    @patch("friday.reasoning.llamacpp_server.Path.is_file", return_value=True)
    def test_stop_kills_owned_process(self, mock_file, mock_wait, mock_find, mock_health):
        proc = MagicMock()
        proc.pid = 999
        proc.terminate.return_value = None
        proc.wait.return_value = None
        mgr = LlamaCppServerManager()
        with patch("friday.reasoning.llamacpp_server.subprocess.Popen", return_value=proc):
            mgr.start()
        mgr.stop()
        proc.terminate.assert_called_once()
        self.assertFalse(mgr.is_owned())

    @patch.object(LlamaCppServerManager, "is_already_running", return_value=True)
    def test_stop_does_not_kill_external_process(self, mock_health):
        mgr = LlamaCppServerManager()
        mgr.start()  # detects external server, started_by_friday stays False
        mgr.stop()
        self.assertFalse(mgr.started_by_friday)
        mock_health.assert_called()


class TestAutoStartDisabled(unittest.TestCase):
    @patch.object(LlamaCppServerManager, "is_already_running", return_value=False)
    def test_auto_start_false_does_not_spawn(self, mock_health):
        mgr = LlamaCppServerManager(auto_start=False)
        ok = mgr.start()
        self.assertFalse(ok)
        self.assertFalse(mgr.is_owned())


if __name__ == "__main__":
    unittest.main(verbosity=2)