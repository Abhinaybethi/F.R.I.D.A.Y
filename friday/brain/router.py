"""
Brain Router — deterministic routing layer for Friday's conversational agent.

Labels an incoming request with the brain subsystem that should handle it:

  tool           — concrete commands (open / search / find / system) via intent router
  knowledge      — RAG-backed questions about the project / docs / codebase
  reasoning      — math / analysis / code generation for the local reasoner
  conversational — small talk / greetings / chatter (no RAG)
  clarification  — follow-ups carrying unresolved references
  unsupported    — nothing matched; answer with a polite unknown

Deterministic and fully local (no cloud calls). ``friday.intent.router.route``
remains the single source of truth for tool actions, so this layer only labels
requests; tool execution still flows through the existing intent router.
"""

import re

from friday.intent.models import Action
from friday.intent.router import route as intent_route

_KNOWLEDGE_HINTS = (
    "what is ", "what's ", "what does ", "what are ", "what was ",
    "why did ", "why do ", "how does ", "how do ", "which ",
    "tell me about ", "explain ", "describe ",
)
_ANALYSIS_HINTS = (
    "calculate", "compute", "what is 25", "multiply", "subtract",
    "sum of", "plus", "minus", "times ", "divided by", "square root",
)
_CHATTER_HINTS = (
    "hello", "hey ", " hi", "how are you", "what can you do", "help me",
    "thanks", "thank you", "good morning", "good night", "tell me a joke",
)
_PRONOUN_RE = re.compile(r"\b(it|its|this|that|them|they)\b", re.I)


def route_request(transcript: str) -> dict:
    """Label *transcript* with the brain subsystem that should handle it.

    Returns ``{"kind", "action", "confidence", "reason"}`` where ``kind`` is
    one of tool / knowledge / reasoning / conversational / clarification /
    unsupported.
    """
    text = (transcript or "").strip()
    low = text.lower()
    if not low:
        return _label("unsupported", Action.UNKNOWN, 0.0, "empty")

    intent = intent_route(text)
    if intent.action != Action.UNKNOWN and intent.confidence >= 0.75:
        return _label("tool", intent.action, intent.confidence, "intent_router")

    if _PRONOUN_RE.search(text):
        return _label("clarification", Action.UNKNOWN, 0.6, "pronoun_reference")

    if any(h in low for h in _ANALYSIS_HINTS):
        return _label("reasoning", Action.UNKNOWN, 0.8, "analysis_hint")

    if any(low.startswith(h) for h in _KNOWLEDGE_HINTS):
        return _label("knowledge", Action.UNKNOWN, 0.75, "knowledge_hint")

    if any(h in low for h in _CHATTER_HINTS):
        return _label("conversational", Action.UNKNOWN, 0.7, "chatter_hint")

    return _label("unsupported", Action.UNKNOWN, 0.2, "no_match")


def _label(kind: str, action, confidence: float, reason: str) -> dict:
    return {"kind": kind, "action": action, "confidence": confidence, "reason": reason}


__all__ = ["route_request"]