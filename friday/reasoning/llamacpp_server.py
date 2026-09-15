"""
llama.cpp server lifecycle manager.

Tracks whether F.R.I.D.A.Y. owns the llama-server subprocess, detects an
already-running instance, auto-starts the server when unavailable, and
terminates ONLY the process it started on shutdown.
"""
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class LlamaCppServerManager:
    """Starts / monitors / stops the llama.cpp server for Bonsai reasoning."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model_path: str = "C:\\AI\\models\\Bonsai-8B-Q1_0.gguf",
        executable: str = "llama-server",
        context_size: int = 2048,
        auto_start: bool = True,
        startup_timeout: float = 60.0,
        health_timeout: float = 3.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_path = model_path
        self.executable = executable
        self.context_size = context_size
        self.auto_start = auto_start
        self.startup_timeout = startup_timeout
        self.health_timeout = health_timeout

        self._process: subprocess.Popen | None = None
        self.started_by_friday = False

    # ------------------------------------------------------------------
    # Health detection
    # ------------------------------------------------------------------

    def _health_url(self) -> str:
        return f"{self.base_url}/health"

    def is_already_running(self) -> bool:
        """True if a healthy llama.cpp server is already reachable."""
        try:
            req = urllib.request.Request(self._health_url(), method="GET")
            with urllib.request.urlopen(req, timeout=self.health_timeout) as response:
                if response.status == 200:
                    body = json.loads(response.read().decode("utf-8"))
                    return body.get("status") == "ok"
                return False
        except Exception:
            return False

    def _wait_until_ready(self) -> bool:
        """Poll /health until healthy or startup_timeout elapses."""
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self.is_already_running():
                return True
            time.sleep(0.5)
        return False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Ensure a llama.cpp server is reachable.

        - If already healthy: do nothing (server NOT owned by F.R.I.D.A.Y).
        - If auto_start enabled: spawn the server and wait for readiness.
        - Returns True if reasoning is available afterwards.
        """
        if self.is_already_running():
            logger.info("[LLAMACPP-SERVER] Server already running at %s", self.base_url)
            self.started_by_friday = False
            return True

        if not self.auto_start:
            logger.warning("[LLAMACPP-SERVER] Server unavailable and auto_start disabled.")
            return False

        if self.started_by_friday and self._process is not None:
            # Already attempted — just wait for readiness.
            ready = self._wait_until_ready()
            if ready:
                logger.info("[LLAMACPP-SERVER] Server became ready at %s", self.base_url)
            return ready

        # Locate executable
        exe_path = self._find_executable()
        if exe_path is None:
            logger.error(
                "[LLAMACPP-SERVER] Executable '%s' not found on PATH. "
                "Reasoning is unavailable; deterministic commands remain operational.",
                self.executable,
            )
            return False

        # Validate model file exists
        model = Path(self.model_path)
        if not model.is_file():
            logger.error(
                "[LLAMACPP-SERVER] Model file not found: %s. "
                "Reasoning is unavailable; deterministic commands remain operational.",
                self.model_path,
            )
            return False

        # Spawn server
        cmd = [
            exe_path,
            "-m", self.model_path,
            "-c", str(self.context_size),
            "--host", "127.0.0.1",
            "--port", "8080",
        ]
        logger.info("[LLAMACPP-SERVER] Starting server: %s", " ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.started_by_friday = True
        except Exception as e:
            logger.error("[LLAMACPP-SERVER] Failed to start server: %s", e)
            self._process = None
            self.started_by_friday = False
            return False

        ready = self._wait_until_ready()
        if ready:
            logger.info("[LLAMACPP-SERVER] Server ready at %s", self.base_url)
        else:
            logger.error(
                "[LLAMACPP-SERVER] Server started but /health never became ready within %.0fs. "
                "Check model load / port. Reasoning unavailable; deterministic commands remain operational.",
                self.startup_timeout,
            )
            # Server may still be loading; leave it running but report not-ready.
        return ready

    def is_owned(self) -> bool:
        """True if F.R.I.D.A.Y. spawned this server process."""
        return self.started_by_friday and self._process is not None

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop(self):
        """Terminate ONLY the server subprocess this manager started."""
        if not self.is_owned():
            logger.info("[LLAMACPP-SERVER] Not owner — leaving external server untouched.")
            return

        proc = self._process
        logger.info("[LLAMACPP-SERVER] Stopping owned server (pid=%s)", getattr(proc, "pid", "?"))
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
        except Exception as e:
            logger.error("[LLAMACPP-SERVER] Error stopping server: %s", e)
        finally:
            self._process = None
            self.started_by_friday = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_executable(self) -> str | None:
        """Locate the llama-server executable via shutil.which."""
        found = shutil.which(self.executable)
        if found:
            return found
        # Common standard locations fallback
        candidates = [
            str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server.exe"),
            str(Path("C:\\AI\\llama.cpp\\build\\bin\\llama-server.exe")),
            str(Path("C:\\llama.cpp\\build\\bin\\llama-server.exe")),
        ]
        for c in candidates:
            if Path(c).is_file():
                return c
        return None

    def close(self):
        """Alias of stop() for interface parity with reasoner."""
        self.stop()