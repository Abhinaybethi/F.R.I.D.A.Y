"""
Resolves short-term context references, anaphoric pronouns ("close it"), and search result indexing in Phase 13 (P0).
"""
from typing import Optional, List, Dict
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


def resolve_context(transcript: str, context: ShortTermContext) -> tuple[str, str]:
    """
    Given a transcript and context, return a resolved transcript.
    Returns:
        (resolved_transcript, error_message)
    """
    text = transcript.lower().strip()

    if not text:
        return text, ""

    # 1. "search for X instead" -> drop "instead" and let router parse
    if text.endswith(" instead"):
        text = text[:-8].strip()

    # 2. Pronoun / anaphora for close ("close it", "close that", "close the app")
    if text in ("close it", "close that", "close the app", "close the application"):
        if context.last_target:
            return f"close {context.last_target}", ""
        return "", "I don't know which application to close."

    # 3. Search result indexing ("open the first result", "open the first one")
    if text in ("open the first result", "open the first one", "open result 1", "open first result"):
        results = context.last_search_results or (context.last_tool_result.get("results") if context.last_tool_result else None)
        if results and len(results) > 0:
            first_item = results[0]
            first_url = first_item.get("url") if isinstance(first_item, dict) else str(first_item)
            if first_url:
                return f"go to {first_url}", ""
        return "", "I don't have a result list to open."

    # 4. Open it / open that pronoun fallback
    if text in ("open it", "open that"):
        if context.last_target:
            return f"open {context.last_target}", ""
        return "", "I don't have enough context for that."

    return text, ""
