"""
DRY RUN TEST — Real Files
===========================
Tests the file tool layer. All tests are read-only.
find_file never executes files. open_folder uses os.startfile on known paths.

Label: DRY RUN TEST (open_folder) / REAL READ-ONLY (find_file — always safe)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
from friday.tools import files


# ---------------------------------------------------------------------------
# find_file — always real (read-only, no execution)
# ---------------------------------------------------------------------------

def test_find_file_returns_candidates_or_empty():
    """[REAL READ-ONLY] find_file searches safe dirs and returns candidates list."""
    result = files.find_file("test")
    assert "candidates" in result
    assert isinstance(result["candidates"], list)
    assert "message" in result


def test_find_file_empty_query_denied():
    result = files.find_file("")
    assert not result["success"]


def test_find_file_whitespace_denied():
    result = files.find_file("   ")
    assert not result["success"]


def test_find_file_capped_at_max_results():
    """find_file must not return more than 10 results."""
    result = files.find_file("e")  # very common letter — likely many matches
    assert len(result.get("candidates", [])) <= 10


def test_find_file_stays_in_safe_dirs():
    """All returned candidates must be within the safe directory tree."""
    safe_roots = [
        Path.home() / "Desktop",
        Path.home() / "Documents",
        Path.home() / "Downloads",
        Path.home() / "Pictures",
        Path.home() / "Music",
        Path.home() / "Videos",
    ]
    result = files.find_file("a")
    for candidate in result.get("candidates", []):
        p = Path(candidate).resolve()
        in_safe = any(
            str(p).startswith(str(root.resolve()))
            for root in safe_roots
            if root.exists()
        )
        assert in_safe, f"Candidate outside safe dirs: {candidate}"


# ---------------------------------------------------------------------------
# open_folder — dry-run tests (always safe)
# ---------------------------------------------------------------------------

def test_open_downloads_dryrun():
    result = files.open_folder("downloads", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_documents_dryrun():
    result = files.open_folder("documents", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_desktop_dryrun():
    result = files.open_folder("desktop", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_unknown_folder_denied():
    """Unknown folder aliases must be rejected."""
    result = files.open_folder("system32", dry_run=True)
    assert not result["success"]
    assert "Not in registry" in result["message"]


def test_open_arbitrary_path_folder_denied():
    result = files.open_folder(r"C:\Windows\System32", dry_run=True)
    assert not result["success"]


# ---------------------------------------------------------------------------
# open_file — path safety check
# ---------------------------------------------------------------------------

def test_open_file_outside_safe_dirs_denied():
    """Files outside safe directories must be rejected."""
    result = files.open_file(r"C:\Windows\System32\calc.exe", dry_run=True)
    assert not result["success"]
    assert "outside safe directories" in result["message"]


def test_open_file_within_safe_dir_dryrun():
    """A path inside Downloads is accepted in dry-run."""
    safe_path = str(Path.home() / "Downloads" / "test.txt")
    result = files.open_file(safe_path, dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
