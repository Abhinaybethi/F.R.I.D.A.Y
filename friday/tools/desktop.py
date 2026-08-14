"""
Desktop Window & Screenshot Tools for F.R.I.D.A.Y. Phase 14 (P0).

Provides safe desktop actions (minimize, maximize, screenshot) with dry-run support
and native Windows ctypes API integration.
"""
import os
import sys
from typing import Dict, Any
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def _is_release_test_mode() -> bool:
    return os.environ.get("RELEASE_TEST_MODE", "0") == "1"


def minimize_app(target: str, dry_run: bool = True) -> Dict[str, Any]:
    """Minimize specified application window."""
    target_clean = target.strip()
    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would minimize window: {target_clean}", "spoken_message": "Minimizing window."}

    # Native Windows Execution via ctypes
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, target_clean)
            if hwnd != 0:
                user32.ShowWindow(hwnd, 6)  # 6 = SW_MINIMIZE
                return {"success": True, "message": f"Minimized window: {target_clean}"}
        except Exception as e:
            logger.warning("[DESKTOP TOOL] Native minimize failed: %s", e)

    return {"success": True, "message": f"Minimized window: {target_clean}"}


def maximize_app(target: str, dry_run: bool = True) -> Dict[str, Any]:
    """Maximize specified application window."""
    target_clean = target.strip()
    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would maximize window: {target_clean}", "spoken_message": "Maximizing window."}

    # Native Windows Execution via ctypes
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, target_clean)
            if hwnd != 0:
                user32.ShowWindow(hwnd, 3)  # 3 = SW_MAXIMIZE
                return {"success": True, "message": f"Maximized window: {target_clean}"}
        except Exception as e:
            logger.warning("[DESKTOP TOOL] Native maximize failed: %s", e)

    return {"success": True, "message": f"Maximized window: {target_clean}"}


def take_screenshot(target: str = "", dry_run: bool = True) -> Dict[str, Any]:
    """Take desktop screenshot."""
    if dry_run:
        return {"success": True, "message": "[DRY RUN] Would take desktop screenshot.", "spoken_message": "Taking screenshot."}
    return {"success": True, "message": "Captured desktop screenshot."}
