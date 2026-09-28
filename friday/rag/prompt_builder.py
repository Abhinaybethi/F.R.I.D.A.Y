"""
RAG prompt block — clean, compact, grounded context for the local LLM.

The block is appended to the CHAT-mode user message (system prompt is left
intact so existing reasoner behaviour is preserved).  It carries:
  - retrieved, source-tagged context (knowledge)
  - optional stable-memory recollection (memory)
  - a compact conversation snapshot (conversation)
  - explicit grounding instructions for Bonsai
"""
from friday.rag.models import RAGResult

_INSTRUCTIONS = """INSTRUCTIONS (only when the RETRIEVED CONTEXT is relevant to the question):
- Answer the user's actual question directly.
- Use retrieved context when relevant; prefer it over assumptions.
- Do NOT invent facts that are absent from the context.
- If the retrieved context is insufficient, say so explicitly.
- Never treat unrelated context as evidence.
- Preserve important technical details (names, APIs, model names, file paths).
- Keep the response natural and conversational.
"""


def build_rag_prompt_block(
    result: RAGResult,
    memory_answer: str = "",
    conversation_context: str = "",
) -> str:
    """
    Build the RAG block appended to the LLM user message.

    Returns an empty string when nothing should be injected (no context,
    no memory recollection, no conversation pin needed).
    """
    parts = []

    if result.final_context:
        context_help = (
            "The following context was retrieved from your knowledge base. "
            "Use it only if it is actually relevant to the question.\n\n"
        )
        parts.append(context_help + result.context_block)

    if memory_answer:
        parts.append(f"PERSONAL MEMORY:\n{memory_answer}")

    conv = (conversation_context or "").strip()
    if conv:
        parts.append(f"RECENT CONVERSATION:\n{conv}")

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts) + "\n\n" + _INSTRUCTIONS


def no_context_block(message: str, conversation_context: str = "") -> str:
    """Block used when the relevance gate rejected all context."""
    parts = [message]
    conv = (conversation_context or "").strip()
    if conv:
        parts.append(f"RECENT CONVERSATION:\n{conv}")
    return "\n\n".join(parts)