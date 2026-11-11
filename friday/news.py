"""News fetcher for F.R.I.D.A.Y. voice assistant.

Uses feedparser to fetch from Google News RSS.
Two sources:
  1. Google News India — Nation topic (English):
     https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en
  2. Google News India — Nation topic (Hindi):
     https://news.google.com/rss/headlines/section/topic/NATION?hl=hi&gl=IN&ceid=IN:hi
The Nation topic keeps the feed focused on Indian news instead of mixing in
global/world stories.
Fallback: The Hindu RSS if Google News fails.

Google News RSS links are redirect wrappers; ``resolve_article_url`` decodes
them to the real publisher URL so article extraction works.

Cache: 10-minute TTL to avoid refetching.
"""

from __future__ import annotations

import datetime
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any

import feedparser

from friday.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOOGLE_NEWS_EN_URL = (
    "https://news.google.com/rss/headlines/section/topic/NATION"
    "?hl=en-IN&gl=IN&ceid=IN:en"
)
GOOGLE_NEWS_HI_URL = (
    "https://news.google.com/rss/headlines/section/topic/NATION"
    "?hl=hi&gl=IN&ceid=IN:hi"
)
THE_HINDU_URL = "https://www.thehindu.com/rss"

DEFAULT_LIMIT = 8
CACHE_TTL_SECONDS = 600  # 10 minutes

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Module-level (memoised) state
# ---------------------------------------------------------------------------

_last_fetch: dict[str, dict[str, Any]] = {}  # source -> {items, ts}
_resolved_urls: dict[str, str] = {}  # google news url -> publisher url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _is_fresh(entry: dict[str, Any]) -> bool:
    """Check whether a cached entry is still within the TTL."""
    ts = entry.get("ts", 0)
    return _now() - ts < CACHE_TTL_SECONDS


def _make_item(entry: feedparser.FeedParserDict) -> dict[str, str]:
    """Build a minimal {title, link, source, published} dict from a feed entry."""
    published = entry.get("published_parsed")
    pub_str = (
        datetime.datetime(*published[:6]).isoformat() + "Z"
        if published
        else ""
    )
    source = entry.get("source", {}).get("title", "News")
    title = " ".join(entry.get("title", "").split())
    # Google News titles repeat the publisher ("... - The Hindu"); drop it so
    # the spoken summary and the numbered list stay readable.
    suffix = f" - {source}"
    if source and title.endswith(suffix):
        title = title[: -len(suffix)].rstrip()
    return {
        "title": title,
        "link": entry.get("link", ""),
        "source": source,
        "published": pub_str,
    }


# ---------------------------------------------------------------------------
# Source fetching
# ---------------------------------------------------------------------------

def _fetch_source(url: str, timeout: float = 15.0) -> tuple[list[dict[str, str]], str | None]:
    """Fetch a single RSS feed.

    Returns (items, error_message).
    error_message is None on success, otherwise a human-readable string.
    """
    # Use urllib to fetch with timeout, then feedparser to parse
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = feedparser.parse(raw)
        # feedparser sets .bozo on parse error
        if getattr(parsed, "bozo", False):
            msg = parsed.get("bozo_exception", "Unknown feed parse error")
            return [], msg

        entries = parsed.entries or []
        items = [_make_item(e) for e in entries[:DEFAULT_LIMIT]]
        return items, None
    except urllib.error.URLError as exc:
        return [], f"Network error fetching feed: {exc}"
    except Exception as exc:  # pylint: disable=broad-except
        return [], f"Exception fetching feed: {exc}"


def _fetch_text(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _decode_google_news_url(url: str, timeout: float = 10.0) -> str | None:
    """Resolve a news.google.com/rss/articles/... redirect to its publisher URL.

    Google News serves a JavaScript app shell, so the publisher link is only
    reachable through the same batchexecute endpoint the page itself uses.
    """
    article_id = url.split("/articles/")[1].split("?")[0]
    html = _fetch_text(url, timeout)

    sig = re.search(r'data-n-a-sg="([^"]+)"', html)
    ts = re.search(r'data-n-a-ts="([^"]+)"', html)
    if not (sig and ts):
        return None

    inner = [
        "garturlreq",
        [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
          None, None, None, None, None, 0, 1],
         "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
        article_id, int(ts.group(1)), sig.group(1),
    ]
    payload = [[["Fbv4je", json.dumps(inner, separators=(",", ":"))]]]
    body = urllib.parse.urlencode(
        {"f.req": json.dumps(payload, separators=(",", ":"))}
    ).encode()

    req = urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    chunk = text.split("\n\n", 1)[1] if "\n\n" in text else text
    parsed = json.loads(chunk)
    decoded = json.loads(parsed[0][2])
    resolved = decoded[1] if len(decoded) > 1 else None
    return resolved if isinstance(resolved, str) and resolved.startswith("http") else None


def resolve_article_url(url: str, timeout: float = 10.0) -> str:
    """Return the publisher URL for *url*, decoding Google News redirects.

    Non-Google URLs are returned unchanged. Resolution failures fall back to
    the original URL so callers still have something to try.
    """
    if not url or "news.google.com" not in url:
        return url
    cached = _resolved_urls.get(url)
    if cached:
        return cached
    try:
        resolved = _decode_google_news_url(url, timeout)
        if resolved:
            _resolved_urls[url] = resolved
            return resolved
    except Exception as exc:  # resolution is best-effort
        logger.warning("[NEWS] could not resolve %s: %s", url[:80], exc)
    return url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_headlines(limit: int = DEFAULT_LIMIT, hindi: bool = False) -> tuple[list[dict[str, str]], str | None]:
    """Return latest headlines from the selected source.

    Args:
        limit: maximum number of headlines to return (default 8).
        hindi: if True, use the Hindi-language feed instead of English.

    Returns:
        (headlines, error_message)
        - headlines: list of {title, link, source, published} dicts (may be empty on error).
        - error_message: None on success, otherwise a descriptive string.
    """
    # Choose source URL
    if hindi:
        url = GOOGLE_NEWS_HI_URL
        source_name = "Google News Hindi"
    else:
        url = GOOGLE_NEWS_EN_URL
        source_name = "Google News India"

    # Check cache first
    cache = _last_fetch.get(url)
    if cache and _is_fresh(cache):
        cached_items = cache["items"]
        cached_err = cache.get("err")
        # Respect the requested limit
        if limit <= len(cached_items):
            return cached_items[:limit], cached_err
        return cached_items, cached_err

    # Fetch from network
    items: list[dict[str, str]] = []
    err: str | None = None
    fallback_items: list[dict[str, str]] = []
    fallback_err: str | None = None

    # Primary source
    items, err = _fetch_source(url)

    # If primary failed, try The Hindu fallback
    if err:
        fallback_items, fallback_err = _fetch_source(THE_HINDU_URL)
        if fallback_items:
            items = fallback_items
            err = None  # we have data from the fallback
            # Mark that we used the fallback by prepending a note in source
            for it in items:
                it["source"] = "The Hindu"
        # If both fail, cache the failure so repeated calls keep reporting it
        if not items:
            message = fallback_err or err or "Could not fetch news feeds"
            _last_fetch[url] = {"items": [], "ts": _now(), "err": message}
            return [], message

    # Cache success
    if items:
        _last_fetch[url] = {"items": items, "ts": _now()}

    # If we got headlines from The Hindu fallback and not hindi request,
    # also cache under the Hindi key so subsequent calls with hindi=True also get it.
    if fallback_items and not hindi:
        _last_fetch[GOOGLE_NEWS_HI_URL] = {"items": fallback_items, "ts": _now()}

    # Apply limit
    if items and limit <= len(items):
        items = items[:limit]

    return items, None


# ---------------------------------------------------------------------------
# Debug / direct entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Simple manual test
    hrs, err = get_headlines()
    if err:
        print("Error:", err)
    else:
        for i, h in enumerate(hrs, 1):
            print(f"{i}. {h['title']} ({h['source']}) – {h['published']}")