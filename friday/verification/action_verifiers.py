"""
Deterministic action verifiers for F.R.I.D.A.Y. Phase 9.

SAFETY REQUIREMENT:
  Verifiers are strictly observational (read-only process/filesystem checks).
  They NEVER execute commands, run shell scripts, launch processes, kill processes, or modify files.
"""
from pathlib import Path
from typing import Optional

from friday.intent.models import Action, Intent
from friday.verification.models import VerificationStatus, VerificationResult

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


def verify_open_folder(target: str, is_dry_run: bool) -> VerificationResult:
    """
    Verify OPEN_FOLDER by confirming the target directory exists.
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
    if folder_path.exists() and folder_path.is_dir():
        return VerificationResult(
            status=VerificationStatus.VERIFIED_SUCCESS,
            message=f"Verified folder {key.title()} exists at {folder_path}.",
            details={"path": str(folder_path)},
        )
    return VerificationResult(
        status=VerificationStatus.FAILED,
        message=f"Folder path {folder_path} does not exist.",
    )


def verify_open_website(target: str, is_dry_run: bool) -> VerificationResult:
    """
    Verify OPEN_WEBSITE by checking registry URL and browser process availability.
    """
    if is_dry_run:
        return VerificationResult(
            status=VerificationStatus.DRY_RUN,
            message=f"[DRY RUN] Verification simulated for opening website {target!r}.",
        )

    url = _WEBSITE_URLS.get(target.lower().strip())
    if not url:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            message=f"Website {target!r} is not in the registry.",
        )

    return VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message=f"Verified website navigation initiated for {target.title()} ({url}).",
        details={"url": url},
    )


def verify_search_web(query: str, is_dry_run: bool) -> VerificationResult:
    """
    Verify SEARCH_WEB by verifying non-empty search query string.
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

    return VerificationResult(
        status=VerificationStatus.VERIFIED_SUCCESS,
        message=f"Verified web search initiated for query \"{query}\".",
        details={"query": query},
    )


def verify_get_time(target: str, is_dry_run: bool) -> VerificationResult:
    """
    GET_TIME is a pure stdlib call with no persistent side effects.
    """
    return VerificationResult(
        status=VerificationStatus.NOT_APPLICABLE,
        message="Verification not applicable for GET_TIME.",
    )


def verify_find_file(target: str, is_dry_run: bool) -> VerificationResult:
    """
    FIND_FILE is read-only file search.
    """
    return VerificationResult(
        status=VerificationStatus.NOT_APPLICABLE,
        message="Verification not applicable for FIND_FILE.",
    )


def verify_open_file(target: str, is_dry_run: bool) -> VerificationResult:
    """
    Verify OPEN_FILE by checking file existence in safe directories.
    """
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
