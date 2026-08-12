"""
File and folder control: open, find, and create.

`SEARCH_ROOTS` controls where "find file ..." looks. Add more folders to
the list if you keep files elsewhere.
"""
import os
import platform
import subprocess

from friday.utils.logger import get_logger

logger = get_logger(__name__)

SEARCH_ROOTS = [
    os.path.expanduser("~/Desktop"),
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Downloads"),
]


def open_path(spoken_path: str) -> bool:
    """Tries to open a path directly, or searches common folders for a
    matching file/folder name."""
    candidate = os.path.expanduser(spoken_path)
    if os.path.exists(candidate):
        _open_with_os(candidate)
        return True

    matches = find_file(spoken_path)
    if matches:
        _open_with_os(matches[0])
        return True

    return False


def _open_with_os(path: str):
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def find_file(name: str, max_results: int = 5):
    name = name.lower().strip()
    matches = []

    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for fname in filenames + dirnames:
                if name in fname.lower():
                    matches.append(os.path.join(dirpath, fname))
                    if len(matches) >= max_results:
                        return matches
    return matches


def create_folder(name: str, base_dir: str = None) -> str:
    base_dir = base_dir or os.path.expanduser("~/Desktop")
    path = os.path.join(base_dir, name)
    os.makedirs(path, exist_ok=True)
    return path
