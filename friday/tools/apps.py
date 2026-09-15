"""
App tools — open and close applications via explicit whitelisted mappings.

SAFETY REQUIREMENT:
  User speech → structured Intent → canonical app name → executable lookup.
  Raw transcript text NEVER reaches subprocess.
"""
import os
import shutil
import subprocess
from pathlib import Path

from friday.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Whitelist: canonical name → candidate executables (tried in order)
# ---------------------------------------------------------------------------

_APP_EXECUTABLES: dict[str, list[str]] = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "chrome",       # in PATH fallback
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "msedge",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "firefox",
    ],
    "vscode": [
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"),
        "code",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        str(Path.home() / "AppData" / "Local" / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        "brave",
    ],
    "notepad": ["notepad"],
    "explorer": ["explorer"],
}

# canonical name → process names to match (for close)
_PROCESS_NAMES: dict[str, list[str]] = {
    "chrome":   ["chrome.exe"],
    "edge":     ["msedge.exe"],
    "firefox":  ["firefox.exe"],
    "vscode":   ["Code.exe"],
    "brave":    ["brave.exe"],
    "notepad":  ["notepad.exe"],
    "explorer": ["explorer.exe"],
}

# Human-readable display names
_DISPLAY_NAMES: dict[str, str] = {
    "chrome":   "Chrome",
    "edge":     "Microsoft Edge",
    "firefox":  "Firefox",
    "vscode":   "VS Code",
    "brave":    "Brave",
    "notepad":  "Notepad",
    "explorer": "File Explorer",
}


def _find_executable(app_name: str) -> str | None:
    """Return the first working executable path for the given canonical name."""
    for candidate in _APP_EXECUTABLES.get(app_name, []):
        # Check absolute path
        if Path(candidate).exists():
            return candidate
        # Check PATH
        found = shutil.which(candidate)
        if found:
            return found
    return None


def open_app(name: str, dry_run: bool = True) -> dict:
    """
    Open an application by canonical name with duplicate launch protection.

    Args:
        name:    Canonical app name (from resolver).
        dry_run: If True, log intent but do not launch.
    """
    if name not in _APP_EXECUTABLES:
        return {"success": False, "message": f"Unknown app: {name!r}. Not in registry."}

    display = _DISPLAY_NAMES.get(name, name.title())

    if dry_run:
        msg = f"[DRY RUN] Would open {display}."
        return {"success": True, "message": msg, "spoken_message": msg}

    exe = _find_executable(name)
    if not exe:
        return {"success": False, "message": f"Could not locate {display} on this system."}

    # Duplicate process protection for desktop tools
    try:
        import psutil
        target_procs = [p.lower() for p in _PROCESS_NAMES.get(name, [])]
        is_running = False
        for proc in psutil.process_iter(["name"]):
            pname = (proc.info.get("name") or "").lower()
            if pname in target_procs:
                is_running = True
                break
        if is_running and name in ("notepad", "explorer"):
            logger.info("%s is already running. Reusing existing instance.", display)
            return {"success": True, "message": f"Opening {display}.", "spoken_message": f"Opening {display}."}
    except Exception:
        pass

    try:
        os.startfile(exe)
        logger.info("Opened %s (%s)", display, exe)
        return {"success": True, "message": f"Opening {display} from {exe}.", "spoken_message": f"Opening {display}."}
    except Exception as e:
        logger.error("Failed to open %s: %s", display, e)
        return {"success": False, "message": f"Failed to open {display}: {e}", "spoken_message": f"I couldn't open {display}."}


def close_app(name: str, dry_run: bool = True) -> dict:
    """
    Close an application by canonical name (idempotent).

    Args:
        name:    Canonical app name (from resolver).
        dry_run: If True, log intent but do not terminate.
    """
    if name not in _PROCESS_NAMES:
        return {"success": False, "message": f"Unknown app: {name!r}. Not in registry."}

    display = _DISPLAY_NAMES.get(name, name.title())

    if dry_run:
        msg = f"[DRY RUN] Would close {display}."
        return {"success": True, "message": msg, "spoken_message": msg}

    try:
        import psutil
    except ImportError:
        return {"success": False, "message": "psutil not installed. Run: pip install psutil"}

    target_procs = [p.lower() for p in _PROCESS_NAMES[name]]
    closed = []

    # Attempt graceful window close first on Windows
    for proc_name in target_procs:
        stem = proc_name.rsplit(".", 1)[0]
        try:
            cmd = f"Get-Process -Name '{stem}' -ErrorAction SilentlyContinue | ForEach-Object {{ $_.CloseMainWindow() }}"
            subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=2.0)
        except Exception:
            pass

    time_module = None
    try:
        import time as time_module
        time_module.sleep(0.2)
    except Exception:
        pass

    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] and proc.info["name"].lower() in target_procs:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=0.5)
                closed.append(proc.info["name"])
            except Exception:
                pass

    if closed:
        logger.info("Closed %s (%s)", display, closed)
        return {"success": True, "message": f"Closed {display}.", "spoken_message": f"Closed {display}."}
    return {"success": True, "message": f"{display} is not running.", "spoken_message": f"{display} is already closed."}
