"""
Memory router — keeps Knowledge / Memory / Conversation separated.

  Knowledge    -> indexed project documentation (vector store)
  Memory       -> stable user-specific facts (persistent SQLite memories)
  Conversation -> current-session context (ShortTermContext history)

Policy: never mix blindly. A query classified as `memory` seeds the keyword
recall check first; only those that miss fall back to a knowledge search.
Conversation context is only ever used to disambiguate the query text.
"""
from typing import Optional, List, Dict

from friday.rag.models import RAGQuery


def try_recall_memory(query: RAGQuery, recall_fn=None) -> Optional[str]:
    """
    Attempt to answer from persistent memories. Returns a spoken answer string
    or None when no stable memory matches.

    `recall_fn` is injected (defaults to friday.tools.memory.recall) so the
    router stays pure and testable.
    """
    if not query.needs_rag or query.query_type != "memory":
        return None
    if recall_fn is None:
        from friday.tools.memory import recall as _recall
        recall_fn = _recall

    probe = str(query.semantic_query or query.original)
    result = recall_fn(probe)
    if isinstance(result, dict) and result.get("success"):
        return result.get("spoken_message") or result.get("message")
    # Strip conversational scaffolding and retry.
    simplified = probe.lower().replace("what did i say about ", "").replace("do you remember ", "").strip()
    if simplified != probe.lower():
        result = recall_fn(simplified)
        if isinstance(result, dict) and result.get("success"):
            return result.get("spoken_message") or result.get("message")
    return None


def conversation_pin(query: RAGQuery, history: List[Dict]) -> str:
    """Compact conversation snapshot used only to disambiguate follow-ups."""
    return query.conversation_context