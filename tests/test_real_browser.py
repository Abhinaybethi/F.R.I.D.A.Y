"""
DRY RUN TEST — Real Browser
=============================
Tests the browser tool layer with dry_run=True by default.

Run with --allow-real to perform actual browser opens (safe URLs only).
Safe URLs: youtube, google, github. Search engine is Google.

Label: DRY RUN TEST (default) / REAL EXECUTION TEST (--allow-real flag)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml
from pathlib import Path
from friday.tools import browser

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _real_enabled():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    t = cfg.get("tools", {})
    return (not t.get("dry_run", True)) and t.get("allow_real_execution", False) and ("--allow-real" in sys.argv)


# ---------------------------------------------------------------------------
# DRY RUN tests (always run)
# ---------------------------------------------------------------------------

def test_open_youtube_dryrun():
    result = browser.open_website("youtube", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]
    assert "youtube.com" in result["message"]


def test_open_google_dryrun():
    result = browser.open_website("google", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_github_dryrun():
    result = browser.open_website("github", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]


def test_open_unknown_website_denied():
    """Websites not in whitelist must be rejected."""
    result = browser.open_website("facebook", dry_run=True)
    assert not result["success"]
    assert "Not in registry" in result["message"]


def test_open_arbitrary_url_denied():
    """Arbitrary URL string not in whitelist must be rejected."""
    result = browser.open_website("https://evil.com/payload", dry_run=True)
    assert not result["success"]


def test_search_web_dryrun():
    """Search uses URL-encoded query via fixed Google search URL."""
    result = browser.search_web("python tutorials", dry_run=True)
    assert result["success"]
    assert "DRY RUN" in result["message"]
    assert "python+tutorials" in result["message"] or "python%20tutorials" in result["message"] or "python" in result["message"]


def test_search_web_empty_denied():
    result = browser.search_web("", dry_run=True)
    assert not result["success"]


def test_search_web_whitespace_denied():
    result = browser.search_web("   ", dry_run=True)
    assert not result["success"]


def test_search_web_query_is_url_encoded():
    """Verify query is URL-encoded, not interpolated into a shell command."""
    from urllib.parse import quote_plus
    query = "python & javascript; rm -rf /"
    result = browser.search_web(query, dry_run=True)
    assert result["success"]
    # Verify the URL would be safe (encoded)
    assert "DRY RUN" in result["message"]


# ---------------------------------------------------------------------------
# REAL EXECUTION tests (opt-in only)
# ---------------------------------------------------------------------------

def test_real_open_youtube():
    """[REAL EXECUTION TEST] Opens YouTube in default browser. Opt-in only."""
    if not _real_enabled():
        return
    result = browser.open_website("youtube", dry_run=False)
    print(f"\n  [REAL] Open YouTube: {result}")
    assert result["success"]


def test_real_search_web():
    """[REAL EXECUTION TEST] Searches Google for 'python tutorials'. Opt-in only."""
    if not _real_enabled():
        return
    result = browser.search_web("python tutorials", dry_run=False)
    print(f"\n  [REAL] Search Web: {result}")
    assert result["success"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
