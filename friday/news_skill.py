"""News skill: fetches live headlines and summarizes them via the local LLM.

- Uses friday.news.get_headlines() to fetch real headlines (no fabrication).
- Passes headlines + today's date to the LLM with strict "ONLY use provided data" instructions.
- Returns 5 short spoken points for voice assistant.
- Remembers last headlines for "number N" follow-ups.
"""

from __future__ import annotations

import datetime
import urllib.request

from friday.news import get_headlines, resolve_article_url
from friday.utils.logger import get_logger

logger = get_logger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Module-level memory for the last fetched headlines (for follow-up "number N")
_last_headlines: list[dict[str, str]] = []
_last_headlines_region: str = ""  # region string like "India", "Hindi", etc.


def _fetch_html(url: str, timeout: float = 15.0) -> str | None:
    """Download an article page with a browser user agent."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("[NEWS] download failed for %s: %s", url[:80], exc)
        return None


def _format_headlines_for_llm(headlines: list[dict[str, str]]) -> str:
    """Format headlines as a numbered list for the LLM prompt."""
    lines = []
    for i, h in enumerate(headlines, 1):
        src = h.get("source", "News")
        title = h.get("title", "").strip()
        lines.append(f"{i}. {title} ({src})")
    return "\n".join(lines)


def _build_news_prompt(headlines: list[dict[str, str]], region: str) -> str:
    """Build the LLM prompt for news summarization."""
    today = datetime.datetime.now().strftime("%B %d, %Y")
    formatted = _format_headlines_for_llm(headlines)

    return (
        f"You are F.R.I.D.A.Y., a voice assistant. Today is {today}.\n\n"
        f"Here are the latest news headlines from {region}:\n\n"
        f"{formatted}\n\n"
        f"INSTRUCTIONS:\n"
        f"- Use ONLY the headlines provided above. Do NOT add any outside knowledge.\n"
        f"- If the headlines are empty, say so.\n"
        f"- Give exactly 5 short points, one per line, each under 20 words.\n"
        f"- Write for SPOKEN delivery: natural, concise, no markdown, no bullet chars.\n"
        f"- Do NOT mention sources or numbers in the output.\n\n"
        f"Summary:"
    )


def summarize_headlines(
    llm_client,
    limit: int = 8,
    hindi: bool = False,
    region: str | None = None,
) -> tuple[str, list[dict[str, str]] | None]:
    """
    Fetch headlines and ask the LLM to summarize them in 5 short points.

    Returns:
        (spoken_response, headlines_list_or_None)
        - spoken_response: what the assistant should say
        - headlines_list_or_None: the raw headlines (for follow-up "number N" support),
          or None if fetch failed
    """
    global _last_headlines, _last_headlines_region

    region_label = region or ("Hindi" if hindi else "India")

    headlines, err = get_headlines(limit=limit, hindi=hindi)

    if err:
        logger.warning("[NEWS] fetch failed: %s", err)
        return (
            f"I couldn't retrieve live news right now. {err}",
            None,
        )

    if not headlines:
        return (
            "I couldn't find any news headlines right now. Please try again later.",
            [],
        )

    # Store for follow-ups
    _last_headlines = headlines
    _last_headlines_region = region_label

    # If LLM is available, use it to summarize
    if llm_client and llm_client.is_available():
        prompt = _build_news_prompt(headlines, region_label)
        try:
            # Use the reasoner's chat mode
            from friday.planning.context_resolver import ShortTermContext
            ctx = ShortTermContext()
            result = llm_client.request(prompt, ctx, mode="chat")
            if result.get("type") == "response":
                text = result.get("text", "").strip()
                if text:
                    return text, headlines
        except Exception as e:
            logger.warning("[NEWS] LLM summarization failed: %s", e)

    # Fallback: simple deterministic summary without LLM
    fallback_lines = []
    for i, h in enumerate(headlines[:5], 1):
        title = h.get("title", "").strip()
        if title:
            fallback_lines.append(f"{i}. {title}")
    fallback = "Top headlines: " + "; ".join(fallback_lines)
    return fallback, headlines


def get_article_text(url: str) -> tuple[str | None, str | None]:
    """Fetch and extract article text using trafilatura.

    Google News redirect links are resolved to the publisher first; if the
    download or extraction fails (paywall / redirect / bot block), returns a
    descriptive error so the caller can fall back to the headline.

    Returns (extracted_text, error_message).
    """
    try:
        import trafilatura
    except Exception as e:
        return None, f"trafilatura not available: {e}"

    resolved = resolve_article_url(url)

    try:
        downloaded = trafilatura.fetch_url(resolved)
        if not downloaded:
            downloaded = _fetch_html(resolved)
        if not downloaded:
            return None, "Could not download the article (redirect, paywall, or blocked)"

        extracted = None
        for options in ({"favor_recall": True}, {"no_fallback": False}):
            try:
                candidate = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                    **options,
                )
            except TypeError:
                # Option unsupported by this trafilatura version.
                continue
            if candidate and len(candidate.strip()) >= 120:
                extracted = candidate
                break

        if not extracted or len(extracted.strip()) < 120:
            return None, "Article text could not be extracted (paywall, redirect, or blocked)"

        # Truncate to ~6000 chars for local model context.
        if len(extracted) > 6000:
            extracted = extracted[:6000].rsplit(" ", 1)[0] + "…"

        return extracted, None
    except Exception as e:
        return None, f"Extraction error: {e}"


def deep_dive(
    llm_client,
    number_or_topic: str,
) -> str:
    """
    Handle "tell me more about number N" or "more details on <topic>".

    - If number_or_topic is a digit, look up that headline from the last fetch.
    - Otherwise, treat as a topic and try to find a matching headline.
    - Fetch full article with trafilatura, then ask LLM to explain using ONLY that text.
    """
    global _last_headlines

    if not _last_headlines:
        return "I don't have any recent headlines to reference. Please ask for news first."

    # Try to parse as a number (1-based index)
    target_article = None
    try:
        idx = int(number_or_topic.strip()) - 1
        if 0 <= idx < len(_last_headlines):
            target_article = _last_headlines[idx]
    except ValueError:
        # Not a number — try fuzzy match on title
        query = number_or_topic.lower()
        for h in _last_headlines:
            if query in h.get("title", "").lower():
                target_article = h
                break

    if not target_article:
        return f"Couldn't find a matching article for '{number_or_topic}'."

    url = target_article.get("link", "")
    title = target_article.get("title", "Unknown")

    if not url:
        return f"No link available for that article."

    # Fetch full article text
    article_text, err = get_article_text(url)
    if err or not article_text:
        # Fallback to headline only
        logger.warning("[NEWS] deep_dive extraction failed for %s: %s", url, err)
        return (
            f"I couldn't fetch the full article for '{title}' ({err or 'extraction failed'}). "
            f"Here's the headline: {title}"
        )

    # Ask LLM to explain using ONLY the article text
    if llm_client and llm_client.is_available():
        prompt = (
            f"You are F.R.I.D.A.Y., a voice assistant.\n\n"
            f"Here is a news article:\n\n"
            f"{article_text}\n\n"
            f"INSTRUCTIONS:\n"
            f"- Explain the key points using ONLY the article text above.\n"
            f"- Do NOT add outside knowledge or speculation.\n"
            f"- Give a concise spoken summary (2-3 sentences).\n"
            f"- No markdown, no bullet points.\n\n"
            f"Explanation:"
        )
        try:
            from friday.planning.context_resolver import ShortTermContext
            ctx = ShortTermContext()
            result = llm_client.request(prompt, ctx, mode="chat")
            if result.get("type") == "response":
                text = result.get("text", "").strip()
                if text:
                    return text
        except Exception as e:
            logger.warning("[NEWS] deep_dive LLM failed: %s", e)

    # Fallback: just return the first part of the article
    return article_text[:300] + "…"


def get_last_headlines() -> list[dict[str, str]]:
    """Return the last fetched headlines (for follow-up support)."""
    return list(_last_headlines)


def clear_last_headlines() -> None:
    """Clear the stored headlines."""
    global _last_headlines, _last_headlines_region
    _last_headlines = []
    _last_headlines_region = ""