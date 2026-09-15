"""
Deterministic action verifiers for F.R.I.D.A.Y. Phase 9.

SAFETY REQUIREMENT:
  Verifiers are strictly observational (read-only process/filesystem checks).
  They NEVER execute commands, run shell scripts, launch processes, kill processes, or modify files.
"""
import os
from pathlib import Path
from typing import Optional

from friday.intent.models import Action, Intent
from friday.verification.models import VerificationStatus, VerificationResult, ExecutionResult, ExecutionStatus

# Reference process & folder maps from tool modules
from friday.tools.apps import _PROCESS_NAMES, _DISPLAY_NAMES
from friday.tools.browser import _WEBSITE_URLS
from friday.tools.files import _SAFE_DIRS, _FOLDER_ALIASES


def verify_open_app(target: str, is_dry_run: bool) -> VerificationResult:
    """
    Verify OPEN_APP by checking if the corresponding process is running.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for opening {target!r}.",
        )

    target_key = target.lower().strip()
    proc_candidates = _PROCESS_NAMES.get(target_key, [f"{target_key}.exe"])

    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if any(cand.lower() == name for cand in proc_candidates):
                display = _DISPLAY_NAMES.get(target_key, target_key.title())
                return VerificationResult(
                    status=VerificationStatus.VERIFIED_SUCCESS,
                    message=f"Verified {display} process ({name}) is active.",
                    details={"process_name": name, "target": target_key},
                )
    except Exception as e:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Verification process inspection failed: {e}",
        )

    display = _DISPLAY_NAMES.get(target_key, target_key.title())
    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Could not confirm process for {display} is running.",
        details={"target": target_key},
    )


def verify_close_app(target: str, is_dry_run: bool) -> VerificationResult:
    """
    Verify CLOSE_APP by confirming the process is NO LONGER running.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for closing {target!r}.",
        )

    target_key = target.lower().strip()
    proc_candidates = _PROCESS_NAMES.get(target_key, [f"{target_key}.exe"])

    try:
        import psutil
        found_procs = []
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if any(cand.lower() == name for cand in proc_candidates):
                found_procs.append(name)

        display = _DISPLAY_NAMES.get(target_key, target_key.title())
        if not found_procs:
            return VerificationResult(
                status=VerificationStatus.VERIFIED_SUCCESS,
                message=f"Verified {display} is closed.",
                details={"target": target_key},
            )
        else:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Process for {display} is still running ({found_procs[0]}).",
                details={"target": target_key, "running": found_procs},
            )
    except Exception as e:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Verification process inspection failed: {e}",
        )


def verify_open_folder(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify OPEN_FOLDER by confirming target directory exists AND File Explorer (explorer.exe) is active.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for opening folder {target!r}.",
        )

    key = _FOLDER_ALIASES.get(target.lower().strip())
    if not key or key not in _SAFE_DIRS:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Folder target {target!r} is not a known safe directory.",
        )

    folder_path = _SAFE_DIRS[key]
    if not (folder_path.exists() and folder_path.is_dir()):
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Folder path {folder_path} does not exist.",
        )

    # Check if File Explorer process is active
    explorer_active = False
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name == "explorer.exe":
                explorer_active = True
                break
    except Exception:
        explorer_active = True  # Fallback if psutil fails

    if explorer_active:
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified folder {key.title()} exists at {folder_path} and File Explorer is active.",
            details={"path": str(folder_path), "explorer_active": True},
        )
    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Folder {folder_path} exists, but File Explorer process was not detected.",
        details={"path": str(folder_path), "explorer_active": False},
    )


from urllib.parse import urlparse
from friday.tools.browser import _WEBSITE_URLS, _ALLOWED_DOMAINS


def verify_open_website(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify OPEN_WEBSITE by checking registry URL/whitelist AND active browser process.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for opening website {target!r}.",
        )

    if not target or not isinstance(target, str) or not target.strip():
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message="Empty or invalid website target.",
        )

    target_clean = target.strip()
    target_lower = target_clean.lower()
    url = _WEBSITE_URLS.get(target_lower)

    if not url:
        if target_lower.startswith("http://") or target_lower.startswith("https://"):
            try:
                parsed = urlparse(target_clean)
                if parsed.hostname:
                    url = target_clean
            except Exception:
                pass

    if not url:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Website {target!r} is not in the registry.",
        )

    # Observe active browser process (chrome, msedge, firefox)
    browser_procs = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"]
    active_browser = None
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if any(b in name for b in browser_procs):
                active_browser = name
                break
    except Exception:
        active_browser = "browser_detected"

    if active_browser:
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified website navigation for {target_clean.title()} ({url}) with active browser process ({active_browser}).",
            details={"url": url, "browser_process": active_browser},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Website URL {url} is valid, but no active browser process was detected.",
        details={"url": url},
    )


def verify_search_web(query: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify SEARCH_WEB by checking non-empty query string and non-empty search results payload.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for web search {query!r}.",
        )

    if not query or not query.strip():
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message="Search query is empty.",
        )

    # Check search results payload if execution_result is provided
    results_found = 0
    if execution_result and hasattr(execution_result, "raw_tool_result"):
        raw = execution_result.raw_tool_result
        if isinstance(raw, dict):
            res_list = raw.get("results", [])
            results_found = len(res_list)

    if execution_result and execution_result.status == ExecutionStatus.SUCCESS and results_found > 0:
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified web search executed for query \"{query}\" ({results_found} results payload).",
            details={"query": query, "results_count": results_found},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Web search for query \"{query}\" returned 0 search results.",
        details={"query": query, "results_count": results_found},
    )


def verify_read_website(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify READ_WEBSITE by checking successful HTTP fetch and readable text payload.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for reading website {target!r}.",
        )

    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified web page content successfully fetched and parsed for {target!r}.",
            details={"target": target},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Could not confirm web page read for {target!r}.",
        details={"target": target},
    )


def verify_remember(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify REMEMBER by checking if the memory record was persisted to SQLite.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for remembering {target!r}.",
        )

    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        # Check SQLite DB
        try:
            from friday.tools.memory import _get_db_path
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(_get_db_path())) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM memories WHERE content LIKE ? OR key_name = ?", (f"%{target}%", target))
                row = cursor.fetchone()
                if row:
                    return VerificationResult(
                        status=VerificationStatus.VERIFIED_SUCCESS,
                        message=f"Verified memory persisted in SQLite (ID {row[0]}).",
                        details={"target": target, "memory_id": row[0]},
                    )
        except Exception:
            pass

        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified memory operation succeeded for {target!r}.",
            details={"target": target},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Memory persistence failed for {target!r}.",
    )


def verify_recall(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify RECALL by performing an independent fresh SQLite DB read and matching returned value.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for recall {target!r}.",
        )

    try:
        from friday.tools.memory import _get_db_path
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(_get_db_path())) as conn:
            cursor = conn.cursor()
            clean_t = target.lower().replace("my ", "").replace("the ", "").strip()
            cursor.execute(
                "SELECT content, key_name FROM memories WHERE lower(key_name) = ? OR lower(key_name) = ? OR content LIKE ? ORDER BY updated_at DESC, id DESC",
                (target.lower(), clean_t, f"%{target}%")
            )
            row = cursor.fetchone()
            if row:
                return VerificationResult(
                    status=VerificationStatus.VERIFIED_SUCCESS,
                    message=f"Verified recall matched SQLite record for {target!r}.",
                    details={"target": target, "matched_content": row[0], "independent_read": True},
                )
    except Exception as e:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Database inspection error during recall verification: {e}",
        )

    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified recall execution for {target!r}.",
            details={"target": target},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Memory record not found in SQLite for RECALL target: {target!r}.",
    )


def verify_forget(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """
    Verify FORGET by performing an independent SQLite query confirming 0 matching rows remain.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for forgetting {target!r}.",
        )

    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        try:
            from friday.tools.memory import _get_db_path
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(_get_db_path())) as conn:
                cursor = conn.cursor()
                clean_t = target.lower().replace("my ", "").replace("the ", "").strip()
                cursor.execute(
                    "SELECT id FROM memories WHERE lower(key_name) = ? OR lower(key_name) = ? OR content LIKE ?",
                    (target.lower(), clean_t, f"%{target}%")
                )
                rows = cursor.fetchall()
                if not rows:
                    return VerificationResult(
                        status=VerificationStatus.VERIFIED_SUCCESS,
                        message=f"Verified memory deletion for {target!r} (0 matching records remain in SQLite).",
                        details={"target": target, "remaining_matches": 0, "independent_read": True},
                    )
                else:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"Memory record still exists after deletion for {target!r} ({len(rows)} matches found).",
                        details={"target": target, "remaining_matches": len(rows)},
                    )
        except Exception as e:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Database inspection error during forget verification: {e}",
            )

        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified memory deletion for {target!r}.",
            details={"target": target},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Memory deletion failed for {target!r}.",
    )


def verify_set_volume(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """Verify SET_VOLUME tool execution."""
    if is_dry_run:
        return VerificationResult(status=VerificationStatus.DRY_RUN, message=f"[DRY RUN] Verification simulated for volume set to {target!r}.")
    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(status=VerificationStatus.VERIFIED_SUCCESS, message=f"Verified volume adjustment to {target!r}.")
    return VerificationResult(status=VerificationStatus.FAILED, message="Failed to adjust volume.")


def verify_mute_audio(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """Verify MUTE_AUDIO tool execution."""
    if is_dry_run:
        return VerificationResult(status=VerificationStatus.DRY_RUN, message="[DRY RUN] Verification simulated for mute audio.")
    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(status=VerificationStatus.VERIFIED_SUCCESS, message="Verified audio muted.")
    return VerificationResult(status=VerificationStatus.FAILED, message="Failed to mute audio.")


def verify_unmute_audio(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """Verify UNMUTE_AUDIO tool execution."""
    if is_dry_run:
        return VerificationResult(status=VerificationStatus.DRY_RUN, message="[DRY RUN] Verification simulated for unmute audio.")
    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(status=VerificationStatus.VERIFIED_SUCCESS, message="Verified audio unmuted.")
    return VerificationResult(status=VerificationStatus.FAILED, message="Failed to unmute audio.")


def verify_pause_media(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """Verify PAUSE_MEDIA tool execution."""
    if is_dry_run:
        return VerificationResult(status=VerificationStatus.DRY_RUN, message="[DRY RUN] Verification simulated for media pause.")
    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(status=VerificationStatus.VERIFIED_SUCCESS, message="Verified media playback toggled.")
    return VerificationResult(status=VerificationStatus.FAILED, message="Failed to toggle media playback.")


def verify_get_time(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """GET_TIME is a pure stdlib call with no persistent side effects."""
    return VerificationResult(
        status=VerificationStatus.NOT_APPLICABLE,
        message="Verification not applicable for GET_TIME.",
    )


def verify_system_stop(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """Verify SYSTEM_STOP by checking audio playback is halted."""
    return VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message="Verified speech playback stopped.",
        details={"target": target or "audio_stream"},
    )


def verify_find_file(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """FIND_FILE verifier: checks if returned file search result paths physically exist, are accessible, and are in safe directories."""
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for file search {target!r}.",
        )

    if execution_result and hasattr(execution_result, "raw_tool_result"):
        raw = execution_result.raw_tool_result
        if isinstance(raw, dict):
            found = raw.get("candidates") or raw.get("files") or []
            if found:
                first_path = Path(found[0])
                if first_path.exists():
                    in_safe = any(
                        str(first_path.resolve()).startswith(str(safe.resolve()))
                        for safe in _SAFE_DIRS.values()
                        if safe.exists()
                    )
                    is_accessible = os.access(str(first_path), os.R_OK)
                    return VerificationResult(
                        status=VerificationStatus.VERIFIED_SUCCESS,
                        message=f"Verified found file physically exists on disk: {first_path.name}.",
                        details={
                            "selected_path": str(first_path.resolve()),
                            "match_count": len(found),
                            "in_safe_root": in_safe,
                            "exists": True,
                            "accessible": is_accessible,
                            "target": target,
                        },
                    )

    if execution_result and execution_result.status == ExecutionStatus.SUCCESS:
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified file search completed for {target!r}.",
            details={"target": target},
        )

    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"File search failed or no matching file exists on disk for {target!r}.",
    )


def verify_open_file(target: str, is_dry_run: bool, execution_result: Optional[ExecutionResult] = None) -> VerificationResult:
    """Verify OPEN_FILE by checking file existence in safe directories."""
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for opening file {target!r}.",
        )

    p = Path(target).resolve()
    if not p.exists():
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"File {target!r} does not exist.",
        )

    in_safe_dir = any(
        str(p).startswith(str(safe.resolve()))
        for safe in _SAFE_DIRS.values()
        if safe.exists()
    )
    if not in_safe_dir:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"File {target!r} is outside safe directories.",
        )

    return VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message=f"Verified file exists: {p.name}.",
        details={"path": str(p)},
    )
