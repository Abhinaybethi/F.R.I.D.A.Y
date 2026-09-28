"""
Query understanding for RAG.

Turns a raw user transcript into a retrieval-friendly RAGQuery:
  - decides wether RAG is needed at all (commands / chatter skip retrieval)
  - classifies the question type
  - extracts entities + keywords (e.g. "authentication", "JWT", "database")
  - resolves weak follow-ups ("why did I choose it?") using recent turns
  - optionally returns a compact conversation-context snapshot
Deterministic and lightweight — no LLM calls.
"""
import re
from typing import List, Optional

from friday.rag.models import RAGQuery

_COMMAND_HINTS = [
    "open ", "close ", "play ", "search for ", "search the web", "look up ",
    "set volume", "mute", "unmute", "sleep", "stop", "quit", "exit", "goodbye",
    "remind me to", "what time is it", "what's the time", "tell me a joke",
    "take a screenshot", "find file", "find my file",
]
_CHATTER_HINTS = [
    "tell me a joke", "how are you", "what can you do", "help me", "thanks",
    "thank you", "good morning", "good night", "hey", "hello", "hi",
]
_KNOWLEDGE_IMPERATIVES = [
    "summarize", "summarise", "explain", "describe", "tell me about",
    "what is ", "what's ", "what does ", "what are ",
]
_QUESTION_MARKERS = ["what", "why", "how", "which", "who", "when", "where", "does", "did", "is there", "are there"]
_MEMORY_MARKERS = [
    "remember", "recall", "what did i say", "what did i tell", "my preference",
    "my favorite", "my favourite", "i told you", "you told me", "you remember",
    "what is my", "what's my",
]
_PROJECT_MARKERS = [
    "friday", "my project", "our project", "the project", "my assistant",
    "campus management", "in my code", "in my repo", "repository", "codebase",
    "architecture", "implementation", "i implemented", "i built", "i made",
    "did i use",
]
_ENTITY_PATTERNS = {
    "authentication": r"\bauth\w*|\bjwt\b|\b(login|log\s*in|sign\s*in)\b|\bauthorization\b|\btoken\b",
    "database": r"\b(db|database|sqlite|mysql|postgres\w*|mongodb|schema|table)\b",
    "api": r"\bapi\b|\bendpoint\b|\brest\b|\bhttp\b|\bcrud\b",
    "voice": r"\b(voice|speech|stt|tts|audio|microphone|whisper|vad|piper|kokoro)\b",
    "reasoning": r"\b(reasoning|llm|llama|ollama|bonsai|model|transformer|gguf)\b",
    "embedding": r"\b(embedding|vector|semantic|retriev)\w*",
    "deployment": r"\b(deploy|server|docker|container|cloud|hosting|local)\b",
    "frontend": r"\b(frontend|ui|web app|dashboard|react|interface)\b",
    "backend": r"\b(backend|server[- ]side|node|flask|django|fastapi)\b",
}
_PRONOUN_REF = re.compile(r"\b(it|its|that|this|them|they)\b", re.I)
_FOLLOWUP_SHORT = re.compile(r"^(why|how|what|what about|and|but|so|then|which|who|when|where)\b", re.I)


def _hits(text: str, hints) -> bool:
    """Word-boundary match for hint lists ('hey' must NOT fire inside 'they')."""
    for h in hints:
        if re.search(r"(?<![a-z0-9_])" + re.escape(h) + r"(?![a-z0-9_])", text):
            return True
    return False


def _extract_entities(text: str) -> List[str]:
    found = []
    for name, pat in _ENTITY_PATTERNS.items():
        if re.search(pat, text, re.I):
            found.append(name)
    return found


def _extract_keywords(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text.lower())
    stop = {
        "the", "and", "that", "this", "with", "from", "have", "has", "what",
        "why", "how", "which", "did", "does", "your", "you", "may", "my",
        "about", "were", "was", "are", "for", "into", "could", "would",
    }
    return [w for w in words if w not in stop][:12]


def is_question(text: str) -> bool:
    return any(text.lstrip("?!").lower().startswith(m) for m in _QUESTION_MARKERS) or text.rstrip().endswith("?")


def analyze_query(transcript: str, history: Optional[List[dict]] = None) -> RAGQuery:
    """Analyse the raw transcript into a retrieval-ready RAGQuery."""
    raw = transcript.strip()
    low = raw.lower()
    history = history or []

    query_type = _classify(low)
    needs_rag = _needs_rag(low, query_type)

    entities = _extract_entities(low)
    keywords = _extract_keywords(low)

    conv_context = _compact_conversation(history)
    semantic = _resolve_followup(raw, history)

    filters = {}
    return RAGQuery(
        original=raw,
        semantic_query=semantic,
        keywords=keywords,
        entities=entities,
        query_type=query_type,
        needs_rag=needs_rag,
        filters=filters,
        conversation_context=conv_context,
    )


def _classify(low: str) -> str:
    if re.search(r"\b(what did i say|what did i tell|what is my|what's my|my preference|my favorite|my favourite)\b", low) or any(m in low for m in _MEMORY_MARKERS):
        return "memory"
    if _hits(low, _COMMAND_HINTS):
        return "command"
    if _hits(low, _KNOWLEDGE_IMPERATIVES):
        # "explain X" / "summarize the doc" are knowledge tasks, not commands
        return "technical" if any(m in low for m in ("architecture", "code", "implementation", "database", "api", "model", "config")) else "factual"
    if is_question(low) and any(m in low for m in _PROJECT_MARKERS):
        return "project"
    if is_question(low) and any(
        m in low for m in ("database", "authentication", "api", "code", "architecture",
                           "algorithm", "function", "class", "library", "framework", "how does")
    ):
        return "technical"
    if is_question(low):
        return "factual"
    if any(h in low for h in _CHATTER_HINTS):
        return "conversational"
    return "command"


def _needs_rag(low: str, query_type: str) -> bool:
    if query_type in ("command", "conversational"):
        return False
    if query_type == "memory":
        return True  # personal-stable facts use the memory router
    if _hits(low, _CHATTER_HINTS) or (not is_question(low) and not _hits(low, _KNOWLEDGE_IMPERATIVES)):
        return False
    return True


def _compact_conversation(history: List[dict], max_turns: int = 3) -> str:
    lines = []
    for turn in history[-max_turns:]:
        if not isinstance(turn, dict):
            continue
        t = turn.get("transcript", "")
        r = turn.get("response", "")
        if t:
            lines.append(f"User: {t}")
        if r:
            snippet = r if len(r) < 220 else r[:220] + "..."
            lines.append(f"Assistant: {snippet}")
    return "\n".join(lines)


def _resolve_followup(raw: str, history: List[dict]) -> str:
    """Resolve weak follow-ups into a retrievable query using recent context."""
    text = raw.strip()
    short = _FOLLOWUP_SHORT.match(text) and len(text.split()) <= 8
    has_pronoun = bool(_PRONOUN_REF.search(text))
    if not (short or has_pronoun):
        return text

    # Recover the most recent substantive topic from history.
    previous = None
    for turn in reversed(history[-5:]):
        if isinstance(turn, dict) and turn.get("transcript"):
            t = str(turn["transcript"]).strip()
            if t and not _PRONOUN_REF.match(t) and not short:
                previous = t
                break
            if t and len(t.split()) >= 3 and low(t) != low(text):
                previous = t
                break
    if not previous:
        return text
    return f"{text} ({previous})"


def low(s: str) -> str:
    return s.lower()