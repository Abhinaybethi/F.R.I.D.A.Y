"""
SearchProvider — provider-independent web-search abstraction.

All search providers expose ``search(query, *, max_results, timeout,
freshness)`` and return a flat list of normalized :class:`SearchResult`
objects. Provider-specific structures never leak out of this layer.

``canonicalize_url`` and ``dedupe_results`` implement the Phase 2 URL
normalization rules: strip fragments and obvious tracking parameters, keep the
trailing slash only for the root, and keep the first (best-ranked) copy of a
repeated canonical URL.
"""
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from friday.research.models import SearchResult

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gclsrc", "dclid", "mc_cid", "mc_eid",
    "igshid", "ref_src", "ref_url", "li_fat_id", "_hsenc", "_hsmi",
}


class SearchError(Exception):
    """Structured provider failure. ``error_type`` is a stable token."""

    def __init__(self, message: str, error_type: str = "provider_error",
                 retryable: bool = False, provider: str = ""):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.retryable = retryable
        self.provider = provider


class SearchProvider(ABC):
    """Abstract provider contract. No other module depends on a concrete one."""

    name: str = "base"
    requires_api_key: bool = False

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        timeout: float = 10.0,
        freshness: Optional[str] = None,
    ) -> List[SearchResult]:
        """Search and return normalized results, or raise :class:`SearchError`."""

    @property
    def configured(self) -> bool:
        return not self.requires_api_key


def _render_datetime(value) -> Optional[datetime]:
    """Parse a provider date string into a tz-aware datetime, when possible."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def canonicalize_url(url: str) -> str:
    """Normalize a URL for deduplication without breaking legitimate URLs."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return url
    host = (parts.hostname or "").lower()
    if not host:
        return url
    try:
        port = parts.port
    except ValueError:
        port = None
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    elif path == "":
        path = "/"
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(keep) if keep else ""
    return urlunparse((scheme, host, path, "", query, ""))


def dedupe_results(results: Iterable[SearchResult],
                   max_results: Optional[int] = None) -> List[SearchResult]:
    """Deduplicate results by canonical URL, preserving provider order.

    ``max_results`` optionally caps the returned list after deduplication.
    """
    seen: set = set()
    out: List[SearchResult] = []
    for res in results:
        if not isinstance(res, SearchResult) or not res.url:
            continue
        key = canonicalize_url(res.url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(res)
    if max_results is not None:
        out = out[: max(0, int(max_results))]
    return out


__all__ = ["SearchError", "SearchProvider", "canonicalize_url", "dedupe_results"]