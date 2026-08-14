"""
File tools — search and open files within safe, configured directories.

Safety constraints:
  - Search is limited to a whitelist of directories (Desktop, Documents, Downloads).
  - Files are opened via os.startfile (Windows shell open verb) — no arbitrary
    command execution.
  - Folders are opened via explorer with an explicit whitelisted path.
  - No deletion, modification, or write operations.
"""
import os
from pathlib import Path

from friday.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Safe search directories
# ---------------------------------------------------------------------------

_SAFE_DIRS: dict[str, Path] = {
    "desktop":   Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "pictures":  Path.home() / "Pictures",
    "music":     Path.home() / "Music",
    "videos":    Path.home() / "Videos",
}

# Folder aliases for open_folder (normalised key → SAFE_DIRS key)
_FOLDER_ALIASES: dict[str, str] = {
    "download":  "downloads",
    "downloads": "downloads",
    "document":  "documents",
    "documents": "documents",
    "desktop":   "desktop",
    "picture":   "pictures",
    "pictures":  "pictures",
    "music":     "music",
    "video":     "videos",
    "videos":    "videos",
}

_MAX_RESULTS = 10   # cap returned candidates


def find_file(query: str) -> dict:
    """
    Search for files matching ``query`` within the safe directories.

    Returns up to _MAX_RESULTS candidates as a list of absolute path strings.
    Never opens or executes any file automatically.
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return {"success": False, "message": "Empty search query.", "candidates": []}

    candidates: list[str] = []
    for dir_name, dir_path in _SAFE_DIRS.items():
        if not dir_path.exists():
            continue
        try:
            for entry in dir_path.iterdir():
                if query_lower in entry.name.lower():
                    candidates.append(str(entry))
                    if len(candidates) >= _MAX_RESULTS:
                        break
        except PermissionError:
            pass

    logger.info("find_file(%r): %d candidate(s)", query, len(candidates))
    return {
        "success":    bool(candidates),
        "candidates": candidates,
        "message":    (
            f"Found {len(candidates)} file(s) matching \"{query}\"."
            if candidates
            else f"No files matching \"{query}\" in safe directories."
        ),
        "spoken_message": (
            f"I found {len(candidates)} files matching {query}."
            if candidates
            else f"I couldn't find any files matching {query}."
        ),
    }


def open_file(path: str, dry_run: bool = True) -> dict:
    """
    Open a file by absolute path using the OS default application.

    The path must be inside one of the safe directories.
    """
    p = Path(path).resolve()
    in_safe_dir = any(
        str(p).startswith(str(safe.resolve()))
        for safe in _SAFE_DIRS.values()
        if safe.exists()
    )
    if not in_safe_dir:
        return {"success": False, "message": f"Path is outside safe directories: {path}"}

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would open file: {p}", "spoken_message": f"Opening file {p.name}."}

    try:
        os.startfile(str(p))
        return {"success": True, "message": f"Opened file: {p}", "spoken_message": f"Opening file {p.name}."}
    except Exception as e:
        return {"success": False, "message": f"Error opening file: {e}", "spoken_message": "I couldn't open the file."}


def open_folder(name: str, dry_run: bool = True) -> dict:
    """
    Open a known system folder by alias name.

    ``name`` should be a normalised alias (e.g. "download", "downloads",
    "documents") — it comes from the router, not raw user speech.
    """
    key = _FOLDER_ALIASES.get(name.lower().strip())
    if not key:
        return {"success": False, "message": f"Unknown folder: {name!r}. Not in registry."}

    folder_path = _SAFE_DIRS[key]

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would open folder: {folder_path}", "spoken_message": f"Opening folder {folder_path.name}."}

    try:
        os.startfile(str(folder_path))
        return {"success": True, "message": f"Opened folder: {folder_path}", "spoken_message": f"Opening folder {folder_path.name}."}
    except Exception as e:
        return {"success": False, "message": f"Error opening folder: {e}", "spoken_message": "I couldn't open the folder."}
