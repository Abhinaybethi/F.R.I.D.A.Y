"""
Resolves short-term context references in raw text.
"""
from typing import Optional
from dataclasses import dataclass
from friday.intent.models import Action

@dataclass
class ShortTermContext:
    last_search_query: str = ""
    last_tool_result: dict = None
    last_action: Optional[Action] = None
    last_transcript: str = ""
    last_response: str = ""


def resolve_context(transcript: str, context: ShortTermContext) -> tuple[str, str]:
    """
    Given a transcript and context, return a resolved transcript.
    Returns:
        (resolved_transcript, error_message)
    """
    text = transcript.lower().strip()
    
    # 1. "search for X instead" -> drop "instead" and let the router parse it.
    if text.endswith(" instead"):
        text = text[:-8].strip()
        
    # 2. Pronoun / reference safety
    if text in ("open the first result", "open the first one", "open it", "open that"):
        if context.last_tool_result and context.last_tool_result.get("results"):
            # We have a valid result list
            results = context.last_tool_result["results"]
            if len(results) > 0:
                first_url = results[0].get("url")
                if first_url:
                    return f"go to {first_url}", ""
            return "", "I don't have a result list to open."
        else:
            if "result" in text or "one" in text:
                return "", "I don't have a result list to open."
            return "", "I don't have enough context for that."

    return text, ""
