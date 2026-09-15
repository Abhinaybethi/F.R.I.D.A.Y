"""
Resolves short-term context references, anaphoric pronouns ("close it"), and search result indexing in Phase 13/22.
"""
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from friday.intent.models import Action


@dataclass
class ShortTermContext:
    last_search_query: str = ""
    last_search_results: List[Dict[str, str]] = field(default_factory=list)
    last_tool_result: Optional[dict] = None
    last_action: Optional[Action] = None
    last_target: str = ""
    last_transcript: str = ""
    last_response: str = ""
    history: List[Dict] = field(default_factory=list)
    goal_entities: Dict[str, Any] = field(default_factory=dict)
    # Structured working-memory fields fed from ConversationContext.
    active_app: str = ""
    active_website: str = ""
    last_search: Optional[dict] = None          # {provider, query, results}
    current_media: Optional[dict] = None        # {provider, query, title, url, video_id}
    previous_media: List[dict] = field(default_factory=list)
    last_action_info: Optional[dict] = None     # {type, query, target}
    conversation_turn: int = 0


_ORDINAL_MAP = {
    "first": 0, "1st": 0, "1": 0, "one": 0,
    "second": 1, "2nd": 1, "2": 1, "two": 1, "another": 1, "next": 1,
    "third": 2, "3rd": 2, "3": 2, "three": 2,
    "fourth": 3, "4th": 3, "4": 3, "four": 3,
    "fifth": 4, "5th": 4, "5": 4, "five": 4,
    "last": -1,
}

_RESULT_REF_PAT = re.compile(
    r"^(?:play|open|go to|visit|read|use|select|summarize|no,?\s+the|no,?\s+|find|show)?\s*(?:the\s+)?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|1|2|3|4|5|another|next|result\s+\d+)(?:\s+(?:result|one|video))?$",
    re.IGNORECASE
)

# Positional media advance: "next video" / "previous one" / "play the next video".
_NEXT_PREV_MEDIA_PAT = re.compile(
    r"^(?:play\s+)?(?:the\s+)?(next|previous)\s+(?:video|one)$",
    re.IGNORECASE
)


def resolve_context(transcript: str, context: ShortTermContext) -> tuple[str, str]:
    """
    Given a transcript and context, return a resolved transcript.
    Returns:
        (resolved_transcript, error_message)
    """
    text = transcript.lower().strip().rstrip(".!?").strip()

    if not text:
        return text, ""

    # Helper to find the most recent valid target in history or goal entities
    def get_recent_target() -> str:
        if context.last_target and context.last_target.lower() not in ("it", "that", "the app", "the file", "the website"):
            return context.last_target
        if context.goal_entities.get("last_target"):
            return context.goal_entities["last_target"]
        # Search backwards in history
        for turn in reversed(context.history):
            intent = turn.get("intent")
            if intent and intent.target and intent.target.lower() not in ("it", "that", "the app", "the file", "the website"):
                return intent.target
        return ""

    # Helper to find the most recent search results
    def get_search_results() -> list:
        if context.last_search_results:
            return context.last_search_results
        if context.goal_entities.get("search_results"):
            return context.goal_entities["search_results"]
        if context.last_tool_result and isinstance(context.last_tool_result, dict) and context.last_tool_result.get("results"):
            return context.last_tool_result.get("results")
        for turn in reversed(context.history):
            res = turn.get("tool_result")
            if isinstance(res, dict) and res.get("results"):
                return res.get("results")
        return []

    # 1. "search for X instead" -> drop "instead" and let router parse
    if text.endswith(" instead"):
        text = text[:-8].strip()

    # 1b. Positional next / previous video ("next video", "play the next one").
    #     Advances within the current search results RELATIVE to the active
    #     media; otherwise replays the active query truthfully rather than
    #     pretending to move to a real next video it cannot locate.
    m = _NEXT_PREV_MEDIA_PAT.match(text)
    if m and (text.startswith("play") or "video" in text):
        direction = m.group(1)
        want_play = text.startswith("play")
        media = context.current_media or {}
        current_url = media.get("url") or ""
        results = get_search_results()

        if not results:
            if direction == "previous" and context.previous_media:
                prev = context.previous_media[-1] if isinstance(context.previous_media[-1], dict) else {}
                prev_query = prev.get("query") or context.last_search_query
                if prev.get("url"):
                    return f"go to {prev['url']}", ""
                if prev_query:
                    return f"play {prev_query} on youtube", ""
            query = media.get("query") or context.last_search_query
            if query:
                return f"play {query} on youtube", ""
            return "", "I don't have enough context for the next video."

        idx = None
        for i, r in enumerate(results):
            r_url = r.get("url") if isinstance(r, dict) else None
            if r_url and r_url == current_url:
                idx = i
                break

        if idx is None:
            # Current media not located in the result list.
            if direction == "previous" and context.previous_media:
                prev = context.previous_media[-1] if isinstance(context.previous_media[-1], dict) else {}
                prev_query = prev.get("query") or context.last_search_query
                if prev.get("url"):
                    return f"go to {prev['url']}", ""
                if prev_query:
                    return f"play {prev_query} on youtube", ""
            query = media.get("query") or context.last_search_query
            if query:
                return f"play {query} on youtube", ""
            return "", "I don't have enough context for the next video."

        target_idx = idx + 1 if direction == "next" else idx - 1
        if 0 <= target_idx < len(results):
            item = results[target_idx]
            url = item.get("url") if isinstance(item, dict) else str(item)
            if url:
                return (f"play {url}" if want_play else f"go to {url}"), ""
        if direction == "previous":
            return "", "I don't have a previous video in context."
        return "", "I don't have a next video in context."

    # 2. Search result indexing ("open the first result", "use the second one", "go to result 2")
    m = _RESULT_REF_PAT.match(text)
    if m:
        raw_idx = m.group(1).lower().replace("result ", "").strip()
        idx = _ORDINAL_MAP.get(raw_idx)
        results = get_search_results()
        if results and idx is not None:
            try:
                item = results[idx]
                url = item.get("url") if isinstance(item, dict) else str(item)
                if url:
                    if text.startswith("read") or text.startswith("summarize"):
                        return f"read website {url}", ""
                    # "play the X one" -> keep it a media request so the tool
                    # reports truthfully whether a watch link resolved.
                    if text.startswith("play"):
                        return f"play {url}", ""
                    return f"go to {url}", ""
            except IndexError:
                return "", f"Result index {raw_idx} is out of range."
        return "", "I don't have a result list to open."

    # Backward compatibility for literal phrases
    if text in ("open the first result", "open the first one", "open result 1", "open first result"):
        results = get_search_results()
        if results:
            first_item = results[0]
            first_url = first_item.get("url") if isinstance(first_item, dict) else str(first_item)
            if first_url:
                return f"go to {first_url}", ""
        return "", "I don't have a result list to open."

    # 3. Pronouns for actions ("close it", "open it", "read it", "save it")
    if text in ("close it", "close that", "close the app", "close the application"):
        target = get_recent_target()
        if target:
            return f"close {target}", ""
        return "", "I don't know which application to close."

    if text in ("open it", "open that"):
        target = get_recent_target()
        if target:
            if context.last_action == Action.FIND_FILE:
                return f"open file {target}", ""
            return f"open {target}", ""
        return "", "I don't have enough context for that."

    if text in ("read it", "read that"):
        target = get_recent_target()
        if target:
            if target.startswith("http://") or target.startswith("https://") or "." in target:
                return f"read website {target}", ""
            return f"find file {target}", ""
        return "", "I don't know what to read."

    if text in ("save it", "now save it", "remember it"):
        target = get_recent_target()
        if target:
            return f"remember {target}", ""
        return "", "I don't know what to save."

    # 4. "play it" — resolve to previous YouTube / media query
    if text in ("play it", "play that", "play this"):
        query = (context.current_media or {}).get("query", "") or context.last_search_query or (
            context.last_search or {}).get("query", "") or context.goal_entities.get("last_search_query", "")
        if query:
            return f"play {query} on youtube", ""
        # Fall back to the most recent media-like target
        target = get_recent_target()
        if target and target.lower() not in ("chrome", "youtube"):
            return f"play {target} on youtube", ""
        return "", "I don't have a recent search or media query to play."

    # 4b. "play <query>" inside an active YouTube context — refine with the
    #     prior topic so "play jenny's lectures" after "python tutorials"
    #     becomes "play python tutorials jenny's lectures on youtube".
    #     Reference plays ("it", "that", "next video", "the first one" …) are
    #     handled earlier / by the dedicated rules below and are never refined.
    if (
        text.startswith("play ")
        and not text.endswith(" on youtube")
        and not re.match(r"^play\s+(?:it|that|this|next|previous|another|the)\b", text)
    ):
        prev_topic = (
            (context.last_search or {}).get("query", "")
            or context.last_search_query
            or (context.current_media or {}).get("query", "")
        )
        in_youtube = (
            context.active_website == "youtube"
            or (context.last_search or {}).get("provider") == "youtube"
            or (context.current_media or {}).get("provider") == "youtube"
        )
        if in_youtube and prev_topic and prev_topic.lower() not in text.lower():
            return f"play {prev_topic} {text[5:].strip()} on youtube", ""

    # 6. "search again" / "same thing" — reuse the last search query
    if text in ("search again", "search the same thing", "same search", "search the same thing again", "search for the same thing"):
        query = (context.last_search or {}).get("query", "") or context.last_search_query or context.goal_entities.get("last_search_query", "")
        if query:
            return f"search for {query}", ""
        return "", "I don't have a recent search to repeat."

    return text, ""
