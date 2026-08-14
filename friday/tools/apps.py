"""
App tools — open and close applications via explicit whitelisted mappings.

SAFETY REQUIREMENT:
  User speech → structured Intent → canonical app name → executable lookup.
  Raw transcript text NEVER reaches subprocess.
"""
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
        str(Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"),
        "code",
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
    "notepad":  ["notepad.exe"],
    "explorer": ["explorer.exe"],
}

# Human-readable display names
_DISPLAY_NAMES: dict[str, str] = {
    "chrome":   "Chrome",
    "edge":     "Microsoft Edge",
    "firefox":  "Firefox",
    "vscode":   "VS Code",
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
    Open an application by canonical name.

    Args:
        name:    Canonical app name (from resolver).
        dry_run: If True, log intent but do not launch.
    """
    if name not in _APP_EXECUTABLES:
        return {"success": False, "message": f"Unknown app: {name!r}. Not in registry."}

    display = _DISPLAY_NAMES.get(name, name.title())

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would open {display}.", "spoken_message": f"Opening {display}."}

    exe = _find_executable(name)
    if not exe:
        return {"success": False, "message": f"Could not locate {display} on this system."}

    try:
        subprocess.Popen([exe], close_fds=True)
        logger.info("Opened %s (%s)", display, exe)
        return {"success": True, "message": f"Opening {display}.", "spoken_message": f"Opening {display}."}
    except Exception as e:
        logger.error("Failed to open %s: %s", display, e)
        return {"success": False, "message": f"Failed to open {display}: {e}", "spoken_message": f"I couldn't open {display}."}


def close_app(name: str, dry_run: bool = True) -> dict:
    """
    Close an application by canonical name.

    Args:
        name:    Canonical app name (from resolver).
        dry_run: If True, log intent but do not terminate.
    """
    if name not in _PROCESS_NAMES:
        return {"success": False, "message": f"Unknown app: {name!r}. Not in registry."}

    display = _DISPLAY_NAMES.get(name, name.title())

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would close {display}.", "spoken_message": f"Closing {display}."}

    try:
        import psutil
    except ImportError:
        return {"success": False, "message": "psutil not installed. Run: pip install psutil"}

    target_procs = [p.lower() for p in _PROCESS_NAMES[name]]
    closed = []
    for proc in psutil.process_iter(["name"]):
        if proc.info["name"] and proc.info["name"].lower() in target_procs:
            try:
                proc.terminate()
                closed.append(proc.info["name"])
            except Exception:
                pass

    if closed:
        logger.info("Closed %s (%s)", display, closed)
        return {"success": True, "message": f"Closed {display}.", "spoken_message": f"Closed {display}."}
    return {"success": False, "message": f"{display} does not appear to be running.", "spoken_message": f"{display} doesn't seem to be running."}
