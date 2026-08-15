import socket
import ipaddress
import urllib.parse
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


def _validate_url_security(url: str, is_dry_run: bool = False) -> tuple[bool, str]:
    """
    URL Security Boundary for SSRF Prevention.
    Validates scheme, hostname, IP address classification (loopback, private,
    link-local, unspecified, multicast, reserved), localhost resolution, and DNS.
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

    # Direct forbidden hostname keywords
    if hostname_lower in ("localhost", "127.0.0.1", "::1") or hostname_lower.endswith(".localhost") or hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        return False, f"Access to localhost/loopback target {hostname!r} is forbidden."

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
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        if is_dry_run:
            return True, ""
        return False, f"DNS resolution failed for {hostname!r}: {e}"
    except Exception as e:
        if is_dry_run:
            return True, ""
        return False, f"DNS resolution error for {hostname!r}: {e}"

    if not addr_info:
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


_ALLOWED_DOMAINS = {
    "youtube.com", "www.youtube.com",
    "google.com", "www.google.com",
    "github.com", "www.github.com",
    "example.com", "www.example.com",
    "python.org", "www.python.org",
}


def open_website(name: str, dry_run: bool = True) -> dict:
    """Open a known website by canonical name or direct URL."""
    name_clean = (name or "").strip()
    if not name_clean:
        return {"success": False, "message": "Empty website target."}

    name_lower = name_clean.lower()
    url = _WEBSITE_URLS.get(name_lower)

    if not url:
        if name_lower.startswith("http://") or name_lower.startswith("https://"):
            parsed = urlparse(name_clean)
            hostname = (parsed.hostname or "").lower()
            if hostname in _ALLOWED_DOMAINS or any(hostname.endswith("." + d) for d in _ALLOWED_DOMAINS):
                url = name_clean
            else:
                return {"success": False, "message": f"Not in registry: {name_clean}"}
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

    webbrowser.open(url)
    logger.info("Opened website: %s", url)
    return {"success": True, "message": f"Opened {url}", "spoken_message": f"Opening {url}."}


def search_web(query: str, dry_run: bool = True) -> dict:
    """
    Perform a web search for ``query``.
    Returns structured results list.
    """
    if not query or not query.strip():
        return {"success": False, "message": "Empty search query."}

    query_str = query.strip()
    safe_query = quote_plus(query_str)
    url = _SEARCH_URL.format(safe_query)

    if dry_run:
        dummy_results = [
            {"title": f"Result 1 for {query_str}", "summary": f"Summary for {query_str}", "url": f"https://example.com/1?q={safe_query}"},
            {"title": f"Result 2 for {query_str}", "summary": f"Second summary for {query_str}", "url": f"https://example.com/2?q={safe_query}"},
            {"title": f"Result 3 for {query_str}", "summary": f"Third summary for {query_str}", "url": f"https://example.com/3?q={safe_query}"},
        ]
        return {
            "success": True,
            "message": f"[DRY RUN] Would search: {url}",
            "spoken_message": f"Searching for {query_str}.",
            "results": dummy_results,
        }

    results = []
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            for r in ddgs.text(query_str, max_results=3):
                results.append({
                    "title": r.get("title", ""),
                    "summary": r.get("body", ""),
                    "url": r.get("href", ""),
                })
    except Exception as e:
        logger.warning("Web search failed: %s", e)

    if not results:
        spoken = f"I couldn't find any results for {query_str}."
    else:
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
