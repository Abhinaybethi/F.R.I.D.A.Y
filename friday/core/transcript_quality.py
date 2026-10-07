"""
Transcript quality guard - decide whether STT output is safe to act on.

Observed failures in the 2026-09-29 voice run:

    "can you tell me about? no jes"     -> Friday explained an entity named "No Jes"
    "asking about not nodejs, nodejs"   -> the doubled fragment reached the model
    "no jes, I mean Node.js"            -> the noisy prefix won over the correction

This module answers one question - *should this transcript be trusted?* - using
evidence that is actually available:

* the text itself (segment-level: empty, too short to carry information,
  suspicious STT noise, immediate self-correction)
* optionally the *segment-level* STT hint from
  ``friday.voice.speech_to_text.transcribe_detailed`` (``quality_ok``)

There is deliberately **no** word-level confidence here: the installed STT
stack does not produce per-word probabilities, so a guard that pretended to
know them would be fiction.

Behaviour:

* ambiguous noise  -> ``clarification`` ("I didn't catch that..."), no entity,
  no reasoner call
* valid terms      -> untouched; ``node.js`` / ``nodejs`` / ``faster-whisper``
  are never treated as garbage
* self-correction  -> ``corrected=True`` and the corrected text is returned

No global "node.js = no jes" replacement table exists; corrections are only
honoured when the speaker actually signals one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)


CLARIFICATION = "I didn't catch that. Could you say it again?"

# Short function words carry no retrievable information on their own.
_STOPWORDS = frozenset({
    "a", "about", "an", "and", "any", "are", "as", "at", "be", "been", "but",
    "by", "can", "could", "did", "do", "does", "for", "from", "get", "give",
    "go", "had", "has", "have", "he", "her", "him", "his", "how", "i", "if",
    "in", "is", "it", "its", "just", "know", "like", "me", "my", "no", "not",
    "of", "on", "or", "our", "out", "please", "she", "so", "some", "tell",
    "that", "the", "their", "them", "then", "there", "these", "they", "this",
    "to", "up", "us", "was", "we", "were", "what", "whats", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your",
})

# Real product / technical terms. A known term is never garbage, and is never
# "corrected" into something else.
_KNOWN_TERMS = frozenset({
    "node", "nodejs", "node.js", "js", "javascript", "typescript", "python",
    "faster-whisper", "whisper", "llama.cpp", "llama", "ollama", "bonsai",
    "friday", "fridays", "chrome", "youtube", "google", "react", "linux",
    "windows", "powershell", "vscode", "git", "github", "numpy", "pandas",
    "pytorch", "tensorflow", "rust", "golang", "java", "kotlin", "swift",
    "docker", "nginx", "redis", "postgres", "postgresql", "sqlite", "api",
    "json", "yaml", "html", "css", "cuda", "gpu", "cpu", "ram", "ssd",
})

# Short standalone fragments that are pure STT noise. Each entry is anchored and
# deliberately narrow so that real words ("node", "not", "no") are unaffected.
_NOISE_FRAGMENTS = (
    re.compile(r"^(?:uh|um|er|ah|eh|mm|hm)\s*[a-z]{0,6}$"),
    re.compile(r"^(?:no|not|node)\s+j[ea]ss?$"),
    re.compile(r"^[bcdfghjklmnpqrstvwxz]{4,}$"),               # consonant runs
    re.compile(r"^(\w)\1{3,}$"),                                # aaaaa
)

# Explicit, speaker-signalled corrections: "X, I mean Y" / "correction: Y".
# Deliberately narrow: discourse markers like "actually" and polite openers
# like "sorry" must NOT be treated as corrections ("Actually, forget that.
# What was our RAG score...?" is not a self-correction).
_CORRECTION_MARKERS = (
    re.compile(r"\bi\s+mean\b", re.I),
    re.compile(r"\bi\s+meant\b", re.I),
    re.compile(r"\bi\s+misspoke\b", re.I),
    re.compile(r"\bi\s+got\s+that\s+wrong\b", re.I),
    re.compile(r"\bcorrect(?:ion)?\s*[:,-]", re.I),
)
# Tokens a speaker might throw away right before correcting themselves:
# "not no jes, Node.js". "no problem, tell me about node.js" is NOT a
# correction - "problem" is not on this list.
_CORRECTION_PREFIX_TOKENS = frozenset({
    "no", "not", "nope", "nah", "um", "uh", "err", "er", "hmm", "oh", "like",
    "well", "jes", "jess", "node", "so", "and", "i",
})
_COMMA = re.compile(r"[,;:]")

_CHAT_FOLLOW = re.compile(
    r"^(?:thank(?:s)?|thanks|bye|goodbye|ok|okay|yes|sure|alright)\b", re.I,
)


@dataclass
class TranscriptVerdict:
    """Result of assessing one transcript."""

    ok: bool
    text: str = ""
    reason: str = ""
    correction: str = ""
    corrected: bool = False
    clarification: str = ""
    stt_quality_ok: Optional[bool] = None
    signals: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def _strip_wake_and_fillers(text: str) -> str:
    out = text
    out = re.sub(r"^\s*(?:hey|ok|okay|so|um|uh|well)\s+(?:friday|fridays)\b[,.!]?\s*", "", out, flags=re.I)
    out = re.sub(r"^\s*friday\s*[,!.]?\s+(?=\S)", "", out, flags=re.I)
    return out.strip()


def _correction_part(text: str) -> Optional[str]:
    """Return the explicitly corrected segment, if the speaker signalled one."""
    match = None
    for marker in _CORRECTION_MARKERS:
        found = marker.search(text)
        if found and (match is None or found.start() < match.start()):
            match = found
    if match:
        tail = text[match.end():].strip(" \t,;:!.-")
        if tail:
            return tail

    # "not no jes, Node.js" / "no, Node.js" / "no jes, Node.js"
    parts = [p.strip() for p in _COMMA.split(text) if p.strip()]
    if len(parts) < 2:
        return None
    prefix_tokens = re.findall(r"[a-z0-9]+", parts[0].lower())
    if not prefix_tokens or len(prefix_tokens) > 3:
        return None
    if not all(token in _CORRECTION_PREFIX_TOKENS for token in prefix_tokens):
        return None
    candidate = parts[1]
    # A single negation before the comma is a weak signal; a real continuation
    # like "no, thank you" is not a correction.
    if len(prefix_tokens) == 1:
        if _CHAT_FOLLOW.match(candidate):
            return None
        if len(_information_words(candidate)) < 2 and not _is_known_term(candidate):
            return None
    return candidate


def _collapse_repetition(text: str) -> str:
    """Drop a fragment that is immediately repeated: "not nodejs, nodejs"."""
    parts = [p.strip() for p in _COMMA.split(text) if p.strip()]
    if len(parts) == 2 and parts[0].lower().endswith(parts[1].lower()):
        return parts[1]
    if len(parts) == 2 and parts[0].lower() == parts[1].lower():
        return parts[1]
    return text


def _information_words(text: str) -> List[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9._+#-]*", text.lower())
    return [t for t in tokens if t not in _STOPWORDS]


def _is_known_term(text: str) -> bool:
    """True when the whole text is a real product / technical term."""
    return text.lower().strip() in _KNOWN_TERMS


def _noise_clause(text: str) -> str:
    """Return the noise-shaped trailing clause of *text*, if any.

    "can you tell me about? no jes" - a real question followed by a garbled
    fragment - is the reported failure. The fragment is detected on the last
    clause so a valid, short technical question ("what is aws") is not judged by
    its final token alone.
    """
    clauses = [c.strip() for c in re.split(r"[?!,;:|]|\s+and\s+", text) if c and c.strip()]
    if not clauses:
        return ""
    tail = clauses[-1]
    if _is_known_term(tail):
        return ""
    for pattern in _NOISE_FRAGMENTS:
        if pattern.match(tail.lower()):
            return "stt_noise"
    return ""


def _looks_like_noise(text: str) -> str:
    low = re.sub(r"[\s\W_]+$", "", text.lower().strip())
    if not low:
        return "empty"
    # A known term is never garbage, but noise *containing* a term is still
    # noise ("node jes" is not the term "node").
    if _is_known_term(low):
        return ""
    for pattern in _NOISE_FRAGMENTS:
        if pattern.match(low):
            return "stt_noise"
    clause_noise = _noise_clause(text)
    if clause_noise:
        return clause_noise
    for term in _KNOWN_TERMS:
        if term in low:
            return ""
    words = re.findall(r"[a-z0-9][a-z0-9._+#-]*", low)
    content = [w for w in words if w not in _STOPWORDS]
    if not content:
        return "no_content_words"
    if len(content) == 1 and len(content[0]) <= 3 and content[0] not in _KNOWN_TERMS:
        return "low_information"
    return ""


def assess_transcript(text: str, stt_quality_ok: Optional[bool] = None) -> TranscriptVerdict:
    """Assess whether ``text`` is trustworthy enough to act on.

    Args:
        text: the raw STT transcript (preserved as-is in ``verdict.text`` when OK)
        stt_quality_ok: optional *segment-level* hint from the STT layer.
            ``False`` rejects the turn; ``True`` is a positive signal only.
    """
    original = text if isinstance(text, str) else ""
    signals: List[str] = []

    if stt_quality_ok is False:
        return TranscriptVerdict(
            ok=False,
            text=original,
            reason="stt_low_confidence",
            clarification=CLARIFICATION,
            stt_quality_ok=stt_quality_ok,
            signals=["stt_low_confidence"],
        )

    cleaned = _strip_wake_and_fillers(original)
    if not cleaned.strip():
        return TranscriptVerdict(
            ok=False, text=original, reason="empty", clarification=CLARIFICATION,
            stt_quality_ok=stt_quality_ok, signals=["empty"],
        )

    corrected_text = _correction_part(cleaned)
    if corrected_text:
        signals.append("self_correction")
        candidate = corrected_text
        noise = _looks_like_noise(candidate)
        if not noise:
            return TranscriptVerdict(
                ok=True, text=candidate, reason="", correction=candidate,
                corrected=True, stt_quality_ok=stt_quality_ok, signals=signals,
            )
        # Correction itself is still noise -> fall through to the guard.
        signals.append("correction_also_noisy")

    collapsed = _collapse_repetition(cleaned)
    if collapsed != cleaned:
        signals.append("repetition_collapsed")
        noise = _looks_like_noise(collapsed)
        if not noise:
            return TranscriptVerdict(
                ok=True, text=collapsed, reason="", correction=collapsed,
                corrected=True, stt_quality_ok=stt_quality_ok, signals=signals,
            )

    noise = _looks_like_noise(collapsed)
    if noise:
        return TranscriptVerdict(
            ok=False, text=original, reason=noise, clarification=CLARIFICATION,
            stt_quality_ok=stt_quality_ok, signals=signals + [noise],
        )

    if len(_information_words(collapsed)) == 0 and len(collapsed.split()) <= 2:
        return TranscriptVerdict(
            ok=False, text=original, reason="no_content_words",
            clarification=CLARIFICATION, stt_quality_ok=stt_quality_ok,
            signals=signals + ["no_content_words"],
        )

    return TranscriptVerdict(
        ok=True, text=collapsed, reason="", stt_quality_ok=stt_quality_ok,
        signals=signals,
    )
