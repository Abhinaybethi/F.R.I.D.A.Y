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


_ORDINAL_MAP = {
    "first": 0, "1st": 0, "1": 0, "one": 0,
    "second": 1, "2nd": 1, "2": 1, "two": 1,
    "third": 2, "3rd": 2, "3": 2, "three": 2,
    "fourth": 3, "4th": 3, "4": 3, "four": 3,
    "fifth": 4, "5th": 4, "5": 4, "five": 4,
    "last": -1,
}

_RESULT_REF_PAT = re.compile(
    r"^(?:open|go to|visit|read|use|select|summarize)\s+(?:the\s+)?(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|1|2|3|4|5|result\s+\d+)(?:\s+(?:result|one))?$",
    re.IGNORECASE
)


def resolve_context(transcript: str, context: ShortTermContext) -> tuple[str, str]:
    """
    Given a transcript and context, return a resolved transcript.
    Returns:
        (resolved_transcript, error_message)
    """
    text = transcript.lower().strip()

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

    return text, ""
