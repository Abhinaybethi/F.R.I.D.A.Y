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
import re
import urllib.parse
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


def _contains_traversal(target: str) -> bool:
    """
    Check string for path traversal attempts (relative traversal '..' and UNC paths).
    """
    if not target or not isinstance(target, str):
        return False

    raw_lower = target.lower().strip()
    unquoted = urllib.parse.unquote(raw_lower)

    for s in (raw_lower, unquoted):
        if ".." in s:
            return True
        if s.startswith(("\\\\", "//")):
            return True

    return False


def _is_path_inside_safe_roots(path: Path) -> bool:
    """Validate that path strictly resides inside an approved safe root directory."""
    try:
        res = path.resolve()
        for safe in _SAFE_DIRS.values():
            if safe.exists():
                safe_res = safe.resolve()
                try:
                    res.relative_to(safe_res)
                    return True
                except ValueError:
                    continue
        return False
    except Exception:
        return False


def find_file(query: str) -> dict:
    """
    Search for files matching ``query`` within the safe directories.
    Returns up to _MAX_RESULTS candidates as a list of absolute path strings.
    Never opens or executes any file automatically.
    """
    if not query or not query.strip():
        return {"success": False, "message": "Empty search query.", "candidates": []}

    q_strip = query.strip()
    is_abs_path = bool(re.match(r"^[a-zA-Z]:[/\\]", q_strip) or q_strip.startswith("/") or q_strip.startswith("\\"))

    if _contains_traversal(query) or is_abs_path:
        logger.warning("Path traversal attempt in find_file query: %r", query)
        return {
            "success": False,
            "message": f"Path traversal attempt blocked: {query!r}",
            "candidates": [],
            "spoken_message": "Invalid file search query."
        }

    query_lower = query.lower().strip()

    # Extract implied file type if present
    implied_type = None
    for ext in ["pdf", "txt", "docx", "csv", "png", "jpg", "jpeg", "mp4", "xlsx", "zip"]:
        if ext in query_lower.split():
            implied_type = ext
            break

    # Clean query (remove "latest", "recent", "my", "find")
    clean_query = query_lower.replace("latest", "").replace("recent", "").replace("my ", "").replace("find ", "")
    if implied_type:
        clean_query = clean_query.replace(implied_type, "")
    clean_query = clean_query.strip()
    query_tokens = [tok for tok in re.split(r"\W+", clean_query) if tok]

    candidates = []

    def _search_dir(dir_name: str, dir_path: Path, depth: int = 0):
        if depth > 3:  # limit depth for speed
            return
        try:
            for entry in os.scandir(str(dir_path)):
                if entry.name.startswith(".") or entry.name in ("node_modules", "venv", ".venv", "__pycache__", "build", "dist"):
                    continue
                if entry.is_file():
                    fname_lower = entry.name.lower()
                    stem_lower = Path(entry.name).stem.lower()

                    match = True
                    if implied_type and not fname_lower.endswith(f".{implied_type}"):
                        match = False
                    if clean_query and clean_query not in fname_lower:
                        # Allow partial token match if not all tokens match
                        if query_tokens and not any(tok in fname_lower for tok in query_tokens):
                            match = False

                    if match:
                        try:
                            p = Path(entry.path)
                            if not _is_path_inside_safe_roots(p):
                                continue
                            stat = entry.stat()
                            
                            # Multi-criteria scoring
                            score = 0.0
                            if clean_query and clean_query == stem_lower:
                                score += 100.0
                            elif clean_query and clean_query in fname_lower:
                                score += 50.0

                            for tok in query_tokens:
                                if tok == stem_lower:
                                    score += 40.0
                                elif tok in fname_lower:
                                    score += 20.0

                            if implied_type and fname_lower.endswith(f".{implied_type}"):
                                score += 30.0

                            # Directory preference
                            if dir_name in ("desktop", "documents"):
                                score += 10.0
                            elif dir_name == "downloads":
                                score += 5.0

                            candidates.append({
                                "path": str(p.resolve()),
                                "name": entry.name,
                                "mtime": stat.st_mtime,
                                "score": score,
                            })
                        except Exception:
                            pass
                elif entry.is_dir():
                    _search_dir(dir_name, Path(entry.path), depth + 1)
        except PermissionError:
            pass

    for dir_name, dir_path in _SAFE_DIRS.items():
        if dir_path.exists():
            _search_dir(dir_name, dir_path)

    # Sort by score descending, then mtime descending
    candidates.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)
    results = [c["path"] for c in candidates[:_MAX_RESULTS]]

    logger.info("find_file(%r): %d candidate(s)", query, len(results))
    return {
        "success":    bool(results),
        "candidates": results,
        "message":    (
            f"Found {len(results)} file(s) matching \"{query}\". Latest: {results[0] if results else ''}"
            if results
            else f"No files matching \"{query}\" in safe directories."
        ),
        "spoken_message": (
            f"I found {len(results)} files matching {query}. The latest one is {Path(results[0]).name}."
            if results
            else f"I couldn't find any files matching {query}."
        ),
    }


def open_file(path: str, dry_run: bool = True) -> dict:
    """
    Open a file by absolute path using the OS default application.
    The path must be inside one of the safe directories.
    """
    if _contains_traversal(path):
        logger.warning("Path traversal attempt in open_file path: %r", path)
        return {"success": False, "message": f"Path traversal attempt blocked: {path}"}

    try:
        p = Path(path).resolve()
    except Exception as e:
        return {"success": False, "message": f"Invalid path: {e}"}

    if not _is_path_inside_safe_roots(p):
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
