"""
Browser tools — open websites and perform web searches.

Uses stdlib webbrowser — no browser-specific deps.
URLs are explicit mappings, never built from raw transcript text.
"""
import webbrowser
from urllib.parse import quote_plus

from friday.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Whitelists
# ---------------------------------------------------------------------------

_WEBSITE_URLS: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google":  "https://www.google.com",
    "github":  "https://github.com",
}

_SEARCH_URL = "https://www.google.com/search?q={}"


def open_website(name: str, dry_run: bool = True) -> dict:
    """Open a known website by canonical name."""
    url = _WEBSITE_URLS.get(name)
    if not url:
        return {"success": False, "message": f"Unknown website: {name!r}. Not in registry."}

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would open {url}", "spoken_message": f"Opening {name.title()}."}

    webbrowser.open(url)
    logger.info("Opened website: %s", url)
    return {"success": True, "message": f"Opened {url}", "spoken_message": f"Opening {name.title()}."}


def search_web(query: str, dry_run: bool = True) -> dict:
    """
    Perform a web search for ``query``.

    The query is URL-encoded via urllib.parse — raw text is never interpolated
    unsafely into a shell command.
    """
    if not query.strip():
        return {"success": False, "message": "Empty search query."}

    safe_query = quote_plus(query)
    url = _SEARCH_URL.format(safe_query)

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would search: {url}", "spoken_message": f"Searching for {query}."}

    webbrowser.open(url)
    logger.info("Searched: %s", query)
    return {"success": True, "message": f"Searched: {query}", "spoken_message": f"Searching for {query}."}
