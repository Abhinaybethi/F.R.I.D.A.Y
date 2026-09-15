import socket
import ipaddress
import re
import urllib.parse
import urllib.request
import webbrowser
from urllib.parse import quote_plus, urlparse, urljoin

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


_BLOCKED_DOMAINS = {
    "evil.com", "www.evil.com",
    "malicious.com", "www.malicious.com",
    "attacker.com", "www.attacker.com",
}

_ALLOWED_DOMAINS = {
    "youtube.com", "www.youtube.com",
    "google.com", "www.google.com",
    "github.com", "www.github.com",
    "example.com", "www.example.com",
    "python.org", "www.python.org", "docs.python.org",
    "duckduckgo.com", "www.duckduckgo.com",
}


def _validate_url_security(url: str, is_dry_run: bool = False) -> tuple[bool, str]:
    """
    URL Security Boundary for SSRF & Threat Prevention.
    Validates scheme, hostname, blocked domains, IP address classification (loopback,
    private, link-local, unspecified, multicast, reserved), and DNS resolution.
    Returns (is_safe: bool, reason_if_blocked: str).
    """
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL string."

    url_clean = url.strip()

    try:
        parsed = urlparse(url_clean)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Blocked scheme {scheme!r}. Only http and https are allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL contains no hostname."

    hostname_lower = hostname.lower().strip("[] ")

    # Direct forbidden hostname keywords & blacklisted domains
    if hostname_lower in ("localhost", "127.0.0.1", "::1") or hostname_lower.endswith(".localhost") or hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        return False, f"Access to localhost/loopback target {hostname!r} is forbidden."

    if any(hostname_lower == b or hostname_lower.endswith("." + b) for b in _BLOCKED_DOMAINS):
        return False, f"Domain {hostname!r} is blocked by security policy."

    # Parse direct IP if provided
    try:
        ip_obj = ipaddress.ip_address(hostname_lower)
        if ip_obj.is_loopback:
            return False, f"Direct access to loopback IP {hostname_lower} is forbidden."
        if ip_obj.is_private:
            return False, f"Direct access to private network IP {hostname_lower} is forbidden."
        if ip_obj.is_link_local:
            return False, f"Direct access to link-local IP {hostname_lower} is forbidden."
        if ip_obj.is_unspecified:
            return False, f"Direct access to unspecified IP {hostname_lower} is forbidden."
        if ip_obj.is_multicast:
            return False, f"Direct access to multicast IP {hostname_lower} is forbidden."
        if ip_obj.is_reserved:
            return False, f"Direct access to reserved IP {hostname_lower} is forbidden."
    except ValueError:
        pass  # Hostname is a domain name, proceed to DNS resolution check

    # Perform DNS Resolution
    addr_info = None
    for attempt in range(2):
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            if addr_info:
                break
        except socket.gaierror as e:
            if attempt == 0:
                import time
                time.sleep(0.1)
                continue
            if is_dry_run:
                return True, ""
            return False, f"DNS resolution failed for {hostname!r}: {e}"
        except Exception as e:
            if is_dry_run:
                return True, ""
            return False, f"DNS resolution error for {hostname!r}: {e}"

    if not addr_info:
        if is_dry_run:
            return True, ""
        return False, f"No IP addresses resolved for {hostname!r}."

    resolved_ips = set()
    for info in addr_info:
        sockaddr = info[4]
        if sockaddr:
            resolved_ips.add(sockaddr[0])

    for ip_str in resolved_ips:
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Resolved invalid IP format: {ip_str!r}."

        if ip_obj.is_loopback:
            return False, f"Hostname {hostname!r} resolves to loopback IP {ip_str}."
        if ip_obj.is_private:
            return False, f"Hostname {hostname!r} resolves to private IP {ip_str}."
        if ip_obj.is_link_local:
            return False, f"Hostname {hostname!r} resolves to link-local IP {ip_str}."
        if ip_obj.is_unspecified:
            return False, f"Hostname {hostname!r} resolves to unspecified IP {ip_str}."
        if ip_obj.is_multicast:
            return False, f"Hostname {hostname!r} resolves to multicast IP {ip_str}."
        if ip_obj.is_reserved and not (isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj in ipaddress.IPv6Network("64:ff9b::/96")):
            return False, f"Hostname {hostname!r} resolves to reserved IP {ip_str}."

    return True, ""


def open_website(name: str, dry_run: bool = True) -> dict:
    """Open a known website by canonical name or direct URL."""
    name_clean = (name or "").strip()
    if not name_clean:
        return {"success": False, "message": "Empty website target."}

    name_lower = name_clean.lower()
    url = _WEBSITE_URLS.get(name_lower)

    if not url:
        if ":" in name_clean:
            parsed_scheme = urlparse(name_clean).scheme.lower()
            if parsed_scheme and parsed_scheme not in ("http", "https"):
                return {
                    "success": False,
                    "message": f"Blocked scheme {parsed_scheme!r}. Only http and https are allowed.",
                    "spoken_message": "I cannot access that website due to security restrictions."
                }
        if name_lower.startswith("http://") or name_lower.startswith("https://"):
            parsed = urlparse(name_clean)
            if parsed.hostname:
                url = name_clean
            else:
                return {"success": False, "message": f"Invalid URL target: {name_clean}"}
        else:
            return {"success": False, "message": f"Not in registry: {name_clean}"}

    is_safe, err_reason = _validate_url_security(url, is_dry_run=dry_run)
    if not is_safe:
        return {
            "success": False,
            "message": f"Blocked URL for security reasons: {err_reason}",
            "spoken_message": "I cannot access that website due to security restrictions."
        }

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would open {url}", "spoken_message": f"Opening {url}."}

    try:
        opened = webbrowser.open(url)
    except Exception as e:
        logger.error("Failed to open website: %s", e)
        return {"success": False, "message": f"Failed to open {url}: {e}",
                "spoken_message": f"I couldn't open {name_clean}."}
    if not opened:
        logger.warning("webbrowser.open returned False for %s", url)
        return {"success": False, "message": f"Failed to open {url}: browser did not confirm",
                "spoken_message": f"I couldn't open {name_clean}."}
    logger.info("Opened website: %s", url)
    return {"success": True, "message": f"Opened {url}", "spoken_message": f"Opening {url}."}


# In-memory search result cache with TTL (60s) to prevent DuckDuckGo rate limiting
_SEARCH_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 60.0


_VIDEO_TITLE_RE = re.compile(r'"title":{"runs":\[\{"text":"([^"]+)"', re.IGNORECASE)
_VIDEO_ID_RE = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')

_YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _resolve_youtube_watch(query: str, timeout: float = 3.0) -> tuple[str, str]:
    """
    Best-effort resolution of the first real YouTube watch link for ``query``.

    Returns ``(watch_url, title)`` when a video is found, otherwise ``("", "")``.
    Uses a plain HTTP fetch of the YouTube results page — no external deps.
    """
    if not query or not query.strip():
        return "", ""
    safe_query = quote_plus(query.strip())
    url = f"https://www.youtube.com/results?search_query={safe_query}"
    try:
        req = urllib.request.Request(url, headers=_YT_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.info("YouTube watch resolution failed (%s): %s", query.strip()[:40], e)
        return "", ""

    match = _VIDEO_ID_RE.search(html)
    if not match:
        return "", ""
    video_id = match.group(1)
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    title = ""
    t_match = _VIDEO_TITLE_RE.search(html)
    if t_match:
        title = t_match.group(1).replace("\\u0026", "&")
    return watch_url, title


def play_youtube(query: str, dry_run: bool = True) -> dict:
    """
    Deterministically open YouTube search results for ``query``.

    Behavior:
      - dry_run: return the search URL without launching the browser.
      - real:    open https://www.youtube.com/results?search_query=<query>
                 via the default browser (does NOT pretend playback started).

    Returns a truthful dict — never claims a video is playing unless it is.
    """
    if not query or not query.strip():
        return {"success": False, "message": "Empty YouTube query."}

    query_str = query.strip()
    safe_query = quote_plus(query_str)
    url = f"https://www.youtube.com/results?search_query={safe_query}"

    is_safe, err_reason = _validate_url_security(url, is_dry_run=dry_run)
    if not is_safe:
        return {
            "success": False,
            "message": f"Blocked URL for security reasons: {err_reason}",
            "spoken_message": "I cannot open that YouTube search due to security restrictions.",
        }

    if dry_run:
        return {
            "success": True,
            "executed": False,
            "dry_run": True,
            "action": "play_youtube",
            "provider": "youtube",
            "target": query_str,
            "url": url,
            "message": f"[DRY RUN] Would open YouTube search: {url}",
            "spoken_message": f"[DRY RUN] Would search YouTube for {query_str}.",
        }

    # Best-effort: resolve a real watch link before opening the browser.
    watch_url, video_title = _resolve_youtube_watch(query_str)
    if watch_url:
        try:
            webbrowser.open(watch_url)
        except Exception as e:
            logger.error("Failed to open YouTube watch link: %s", e)
            return {
                "success": False,
                "executed": False,
                "action": "play_youtube",
                "provider": "youtube",
                "target": query_str,
                "url": url,
                "message": f"Failed to open YouTube watch link: {e}",
                "spoken_message": f"I couldn't open the video for {query_str}.",
            }
        video_id = watch_url.rstrip("/").split("watch?v=")[-1].split("&", 1)[0]
        logger.info("Opened YouTube watch link for %r: %s", query_str, watch_url)
        return {
            "success": True,
            "executed": True,
            "action": "play_youtube",
            "provider": "youtube",
            "target": query_str,
            "url": url,
            "watch_resolved": True,
            "watch_url": watch_url,
            "video_id": video_id,
            "title": video_title or query_str,
            "message": f"Opened YouTube watch link for {query_str}: {watch_url}",
            "spoken_message": f"Found the video. Opening it on YouTube now for {query_str}.",
        }

    try:
        webbrowser.open(url)
    except Exception as e:
        logger.error("Failed to open YouTube search: %s", e)
        return {
            "success": False,
            "executed": False,
            "action": "play_youtube",
            "provider": "youtube",
            "target": query_str,
            "message": f"Failed to open YouTube search: {e}",
            "spoken_message": f"I couldn't open YouTube search for {query_str}.",
        }

    logger.info("Opened YouTube search: %s", url)
    return {
        "success": True,
        "executed": True,
        "action": "play_youtube",
        "provider": "youtube",
        "target": query_str,
        "url": url,
        "watch_resolved": False,
        "message": f"Opened YouTube search for {query_str}: {url}",
        "spoken_message": f"Opening YouTube search for {query_str}. I couldn't verify a video link, so I opened the search results.",
    }


def search_web(query: str, dry_run: bool = True) -> dict:
    """
    Perform a web search for ``query``.
    Returns structured results list with stable result IDs and in-memory TTL caching.
    """
    if not query or not query.strip():
        return {"success": False, "message": "Empty search query."}

    query_str = query.strip()
    query_key = query_str.lower()
    safe_query = quote_plus(query_str)
    url = _SEARCH_URL.format(safe_query)

    if dry_run:
        dummy_results = [
            {"id": "result_1", "title": f"Result 1 for {query_str}", "summary": f"Summary for {query_str}", "url": f"https://example.com/1?q={safe_query}"},
            {"id": "result_2", "title": f"Result 2 for {query_str}", "summary": f"Second summary for {query_str}", "url": f"https://example.com/2?q={safe_query}"},
            {"id": "result_3", "title": f"Result 3 for {query_str}", "summary": f"Third summary for {query_str}", "url": f"https://example.com/3?q={safe_query}"},
        ]
        return {
            "success": True,
            "message": f"[DRY RUN] Would search: {url}",
            "spoken_message": f"Searching for {query_str}.",
            "results": dummy_results,
        }

    import time
    now = time.time()

    # Check search cache to prevent DDG 429 rate-limiting during rapid queries / workflows
    if query_key in _SEARCH_CACHE:
        cached_time, cached_results = _SEARCH_CACHE[query_key]
        if (now - cached_time) < _CACHE_TTL_SECONDS and cached_results:
            logger.info("Search cache hit for %r (%d results)", query_str, len(cached_results))
            titles = [r.get("title", "") for r in cached_results if r.get("title")]
            spoken = f"I found {len(cached_results)} search results for {query_str}: " + "; ".join(titles) + "."
            return {
                "success": True,
                "message": f"Searched (cached): {query_str}",
                "spoken_message": spoken,
                "results": cached_results,
                "cached": True,
            }

    results = []
    # Attempt 1: DuckDuckGo API with retry (ddgs is the current package name;
    # duckduckgo_search is the legacy name — try ddgs first)
    for attempt in range(2):
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                for idx, r in enumerate(ddgs.text(query_str, max_results=3)):
                    results.append({
                        "id": f"result_{idx + 1}",
                        "title": r.get("title", ""),
                        "summary": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
                if results:
                    break
        except Exception as e:
            logger.warning("Web search API attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(0.3)

    # Attempt 2: HTML Scraper Fallback
    if not results:
        try:
            import requests
            from bs4 import BeautifulSoup
            html_url = f"https://html.duckduckgo.com/html/?q={safe_query}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            r = requests.get(html_url, headers=headers, timeout=6)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for idx, item in enumerate(soup.select(".result__body")[:3]):
                    title_elem = item.select_one(".result__title")
                    snippet_elem = item.select_one(".result__snippet")
                    url_elem = item.select_one(".result__url")
                    title = title_elem.get_text().strip() if title_elem else ""
                    summary = snippet_elem.get_text().strip() if snippet_elem else f"Result for {query_str}"
                    raw_href = url_elem.get_text().strip() if url_elem else ""
                    res_url = f"https://{raw_href}" if raw_href and not raw_href.startswith("http") else raw_href
                    if title:
                        results.append({
                            "id": f"result_{idx + 1}",
                            "title": title,
                            "summary": summary,
                            "url": res_url,
                        })
        except Exception as e_fallback:
            logger.warning("Web search HTML fallback failed: %s", e_fallback)

    if not results:
        spoken = f"I couldn't find any results for {query_str}."
        logger.info("Searched: %s (0 results)", query_str)
        return {
            "success": False,
            "message": f"Search returned 0 results for: {query_str}",
            "spoken_message": spoken,
            "results": [],
        }

    # Store in cache
    _SEARCH_CACHE[query_key] = (now, results)

    titles = [r.get("title", "") for r in results if r.get("title")]
    spoken = f"I found {len(results)} search results for {query_str}: " + "; ".join(titles) + "."
    logger.info("Searched: %s (%d results)", query_str, len(results))
    return {
        "success": True,
        "message": f"Searched: {query_str}",
        "spoken_message": spoken,
        "results": results,
    }


def read_website(name_or_url: str, dry_run: bool = True) -> dict:
    """
    Extract readable text from a website synchronously with SSRF validation.
    Constraints: 10s timeout, 2MB limit, no JS execution, max 2000 chars.
    """
    url = _WEBSITE_URLS.get(name_or_url, name_or_url)
    parsed_target = urlparse(url)
    if not parsed_target.scheme:
        url = "https://" + url

    is_safe, err_reason = _validate_url_security(url, is_dry_run=dry_run)
    if not is_safe:
        return {
            "success": False,
            "message": f"Blocked URL for security reasons: {err_reason}",
            "spoken_message": "I cannot access that website due to security restrictions."
        }

    if dry_run:
        return {"success": True, "message": f"[DRY RUN] Would read {url}", "spoken_message": f"Reading website {name_or_url}."}

    import requests
    from bs4 import BeautifulSoup

    current_url = url
    max_redirects = 5
    response = None

    try:
        for _ in range(max_redirects):
            is_safe, err_reason = _validate_url_security(current_url, is_dry_run=dry_run)
            if not is_safe:
                return {
                    "success": False,
                    "message": f"Blocked redirect URL for security reasons: {err_reason}",
                    "spoken_message": "I cannot access that website due to security restrictions."
                }

            response = requests.get(current_url, timeout=10, stream=True, allow_redirects=False)
            is_redir = (getattr(response, "is_redirect", False) is True) or (getattr(response, "status_code", 200) in (301, 302, 303, 307, 308))
            if is_redir:
                location = response.headers.get("Location") if hasattr(response, "headers") else None
                if not location or not isinstance(location, str):
                    break
                current_url = urljoin(current_url, location)
            else:
                break

        if response is None:
            return {"success": False, "message": "Failed to retrieve URL response.", "spoken_message": "I could not read the website."}

        response.raise_for_status()

        content = b""
        for chunk in response.iter_content(chunk_size=1024 * 100):
            content += chunk
            if len(content) > 2 * 1024 * 1024:  # 2MB limit
                logger.warning("Website %s exceeded 2MB limit, truncating.", current_url)
                break

        soup = BeautifulSoup(content, "html.parser")

        for element in soup(["script", "style", "meta", "noscript", "header", "footer", "nav"]):
            element.decompose()

        text = soup.get_text(separator=" ")
        import re
        clean_text = re.sub(r'\s+', ' ', text).strip()

        if len(clean_text) > 2000:
            clean_text = clean_text[:1997] + "..."

        return {
            "success": True,
            "message": f"Read website {current_url}",
            "spoken_message": f"Here is the page content: {clean_text}"
        }
    except requests.Timeout:
        return {"success": False, "message": f"Timeout connecting to {url}.", "spoken_message": "The website took too long to load."}
    except Exception as e:
        logger.error("Error reading website %s: %s", url, e)
        return {"success": False, "message": f"Error reading {url}: {e}", "spoken_message": "I could not read the website."}
