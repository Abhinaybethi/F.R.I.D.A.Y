"""
Natural Conversation Layer - deterministic local handling of pure chatter.

F.R.I.D.A.Y. used to send every conversational utterance ("hi, how are you?")
to the local reasoner, which is wasteful in latency, CPU and memory. This
module answers simple social interaction locally, before any LLM / RAG /
web-research path is reached.

Design constraints (deliberate, see task 22):

* no model call, no embeddings, no ChromaDB, no web search, no new dependency
* pattern matching on a *normalized* copy of the utterance only; the raw text is
  never rewritten, so downstream context resolution still sees the original
* conservative: anything carrying a substantive request (question, command,
  information request, entity + question, context-dependent follow-up) is
  rejected so the existing pipeline owns it
* ``route()`` returns ``None`` for every non-conversational utterance

Insertion point in the pipeline (task 6)::

    STT
     -> alias normalization / session control / confirmation
     -> deterministic classification          (free, no LLM)
     -> NATURAL CONVERSATION  <-- this layer, short-circuits the LLM
     -> context + follow-up resolution
     -> RAG / web research / reasoner
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from friday.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Intent vocabulary
# ---------------------------------------------------------------------------
GREETING = "GREETING"
WELLBEING = "WELLBEING"
THANKS = "THANKS"
ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
POSITIVE_FEEDBACK = "POSITIVE_FEEDBACK"
GOODBYE = "GOODBYE"
NEGATIVE_FEEDBACK = "NEGATIVE_FEEDBACK"

# Small, hand-written pools. No LLM, no generation, deterministic rotation.
RESPONSES: Dict[str, List[str]] = {
    GREETING: [
        # Canonical greeting first: byte-identical to the pre-existing
        # deterministic greeting (friday.tools.registry Action.GREETING), so
        # text mode, voice mode and their tests stay in agreement.
        "Hello! How can I assist you today?",
        "Hello! How can I help?",
        "Hey! What can I do for you?",
        "Hi there! How can I help?",
    ],
    WELLBEING: [
        "I'm doing great. How about you?",
        "I'm doing well. What can I help you with?",
        "All systems are running smoothly.",
        "I'm good and ready to help.",
    ],
    THANKS: [
        # "You're welcome!" first: existing deterministic-ack contract.
        "You're welcome!",
        "Anytime.",
        "Happy to help.",
        "You're welcome. What else can I do?",
    ],
    ACKNOWLEDGEMENT: [
        "Alright.",
        "Got it.",
        "Sure.",
        "Okay.",
        "Sounds good.",
    ],
    POSITIVE_FEEDBACK: [
        "Glad you liked it.",
        "Awesome.",
        "Great.",
        "Happy to hear that.",
    ],
    GOODBYE: [
        "Goodbye!",
        "See you later.",
        "Take care!",
    ],
    NEGATIVE_FEEDBACK: [
        "Yeah, that's unfortunate.",
        "I understand.",
        "Let's see if we can fix it.",
    ],
}

# Full-segment, fully anchored patterns. A segment is conversational only when
# the WHOLE segment matches one of these - no partial / substring matching.
_INTENT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (GREETING, re.compile(
        r"^(?:hi|hiya|hey|hello|yo|howdy|heya|good\s+(?:morning|afternoon|evening)|"
        r"morning|afternoon|evening)(?:\s+(?:there|everyone|all|friend|computer|bot|friday))?$"
    )),
    (WELLBEING, re.compile(
        r"^(?:how\s+(?:are|is)\s+(?:you|things|it\s+going)|"
        r"how\s+(?:are|is)\s+(?:you|it|things)(?:\s+(?:going|doing|today|now))?|"
        r"how\s+(?:you|it|things)(?:\s+(?:going|doing))*|"
        r"hows\s+(?:it|everything)(?:\s+going)?|"
        r"you\s+(?:doing|are\s+you\s+doing)\s*(?:okay|ok|alright|good|well|"
        r"fine|great|alright)|"
        r"are\s+you\s+(?:okay|ok|alright|good|well|fine|there|alive|still\s+there)|"
        r"you\s+(?:doing\s+)?(?:okay|ok|alright|good|well|fine)|"
        r"everything\s+(?:okay|ok|alright|fine|good))$"
    )),
    (THANKS, re.compile(
        r"^(?:thanks?(?:\s+(?:a\s+lot|lots|very\s+much|much|tons))?|"
        r"thank\s+you(?:\s+(?:a\s+lot|lots|very\s+much|so\s+much|much|tons))?|"
        r"much\s+appreciated|appreciate\s+(?:it|that|your\s+help)|"
        r"that\s+is\s+(?:helpful|super\s+helpful|really\s+helpful)|"
        r"that\s+helped|you\s+(?:are|were)\s+(?:helpful|great|awesome|amazing|"
        r"the\s+best|brilliant))"
        r"(?:\s+friday)?$"
    )),
    (ACKNOWLEDGEMENT, re.compile(
        r"^(?:ok|okay|okey|alright|all\s+right|right|sure|got\s+it|gotcha|"
        r"understood|roger|noted|sounds\s+good|will\s+do|perfectly\s+fine|"
        r"mm|hm|yeah|yes\s+okay)(?:\s+friday)?$"
    )),
    (POSITIVE_FEEDBACK, re.compile(
        r"^(?:nice|great|awesome|amazing|perfect|excellent|cool|fantastic|"
        r"wonderful|brilliant|superb|lovely|beautiful|that\s+is\s+"
        r"(?:great|awesome|cool|perfect|amazing|fine|good|right|nice)|"
        r"that\s+is\s+(?:really\s+)?(?:great|awesome|cool|perfect|amazing)|"
        r"sounds\s+(?:great|awesome|perfect)|love\s+it|looks\s+good)$"
    )),
    (GOODBYE, re.compile(
        r"^(?:bye|bye\s+bye|goodbye|good\s+bye|see\s+you|see\s+ya|"
        r"talk\s+to\s+you\s+later|chat\s+later|catch\s+you\s+later|"
        r"talk\s+later|see\s+you\s+later|see\s+ya\s+(?:later|soon)|"
        r"have\s+a\s+(?:good\s+day|good\s+night|good\s+one))(?:\s+friday)?$"
    )),
    (NEGATIVE_FEEDBACK, re.compile(
        r"^(?:ugh|oh\s+no|no\s+way|that\s+is\s+bad|that\s+is\s+not\s+good|"
        r"not\s+good|that\s+is\s+unfortunate|unfortunate|too\s+bad|"
        r"that\s+sucks|ah\s+man|oh\s+man|hm)(?:\s+friday)?$"
    )),
]

# Any of these means the utterance is doing real work: never swallow it.
_SUBSTANTIVE_VERB = re.compile(
    r"\b(?:open|close|launch|start|stop|pause|resume|skip|next|previous|"
    r"play|search|google|find|look\s+up|fetch|read|send|write|create|make|"
    r"build|run|execute|install|uninstall|delete|remove|set|turn|volume|"
    r"mute|unmute|download|upload|translate|calculate|compute|convert|"
    r"remind|remember|recall|forget|schedule|book|order|buy|call|message|"
    r"email|click|scroll|screenshot|navigate|browse|tell|show|explain|"
    r"describe|list|summarize|summarise|define|compare|recommend|suggest|"
    r"help\s+me|do)\b"
)
_SUBSTANTIVE_WORD = re.compile(
    r"\b(?:what|whats|what's|who|who's|where|when|why|which|whose|how\s+do|"
    r"how\s+can|how\s+to|how\s+much|how\s+many|"
    r"facts?|information|info|news|latest|current|today|tonight|tomorrow|"
    r"yesterday|recent|recently|price|cost|version|release|weather|score|"
    r"weather\s+forecast|definition|meaning|docs|documentation)\b"
)
_CONTEXT_DEPENDENT = re.compile(
    r"\b(?:it|its|they|them|their|those|this|that|he|him|his|she|her|"
    r"more|else|another|again|the\s+same|one|ones)\b"
)
_FILLER = re.compile(r"^(?:um|uh|erm|hmm|mm|hm|eh|like|well|so|please|just|now)$")

# Wake word + vocative forms: "hey friday", "friday", "ok friday".
_WAKE_WORD = re.compile(r"\bfriday\b")

_CONTRACTIONS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bhow'?s\b"), "how is"),
    (re.compile(r"\bwhat'?s\b"), "what is"),
    (re.compile(r"\bthat'?s\b"), "that is"),
    (re.compile(r"\bthere'?s\b"), "there is"),
    (re.compile(r"\bhere'?s\b"), "here is"),
    (re.compile(r"\byou'?re\b"), "you are"),
    (re.compile(r"\byou'?ve\b"), "you have"),
    (re.compile(r"\bi'?m\b"), "i am"),
    (re.compile(r"\bit'?s\b"), "it is"),
    (re.compile(r"\bdon'?t\b"), "do not"),
    (re.compile(r"\bdoesn'?t\b"), "does not"),
    (re.compile(r"\bdidn'?t\b"), "did not"),
    (re.compile(r"\bcan'?t\b"), "can not"),
    (re.compile(r"\bwon'?t\b"), "will not"),
    (re.compile(r"\bisn'?t\b"), "is not"),
    (re.compile(r"\baren'?t\b"), "are not"),
    (re.compile(r"\bwasn'?t\b"), "was not"),
    (re.compile(r"\bgonna\b"), "going to"),
    (re.compile(r"\bwanna\b"), "want to"),
    (re.compile(r"\blemme\b"), "let me"),
    (re.compile(r"\bgimme\b"), "give me"),
]

# Segments are split on the separator kept by normalize() and on connectives.
_SEGMENT_SPLIT = re.compile(r"\s*\|\s*|\s+(?:and|then|also|but|plus)\s+")
_MAX_TOTAL_TOKENS = 10
_MAX_SEGMENT_TOKENS = 6


def _config_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on", "enabled"):
            return True
        if low in ("0", "false", "no", "off", "disabled"):
            return False
    return default


@dataclass
class NaturalConversationResult:
    """Outcome of a natural-conversation route attempt."""

    handled: bool
    intent: str = ""
    response: str = ""
    reason: str = ""
    raw_text: str = ""
    normalized_text: str = ""
    latency_ms: float = 0.0

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.handled


@dataclass
class NaturalConversationMetrics:
    """Lightweight counters - no metrics dependency is introduced."""

    natural_chat_count: int = 0
    natural_chat_llm_bypass_count: int = 0
    natural_chat_latency_ms_total: float = 0.0
    natural_chat_latency_ms_max: float = 0.0
    natural_chat_rejected_count: int = 0
    by_intent: Dict[str, int] = field(default_factory=dict)

    def record_handled(self, intent: str, latency_ms: float) -> None:
        self.natural_chat_count += 1
        # A locally answered turn never reaches the reasoner, RAG, research or
        # the browser: that is the whole point of this layer.
        self.natural_chat_llm_bypass_count += 1
        self.natural_chat_latency_ms_total += latency_ms
        self.natural_chat_latency_ms_max = max(self.natural_chat_latency_ms_max, latency_ms)
        self.by_intent[intent] = self.by_intent.get(intent, 0) + 1

    def record_rejected(self) -> None:
        self.natural_chat_rejected_count += 1

    def snapshot(self) -> Dict[str, float]:
        avg = (self.natural_chat_latency_ms_total / self.natural_chat_count
               if self.natural_chat_count else 0.0)
        return {
            "natural_chat_count": self.natural_chat_count,
            "natural_chat_llm_bypass_count": self.natural_chat_llm_bypass_count,
            "natural_chat_latency_ms_total": round(self.natural_chat_latency_ms_total, 3),
            "natural_chat_latency_ms_avg": round(avg, 3),
            "natural_chat_latency_ms_max": round(self.natural_chat_latency_ms_max, 3),
            "natural_chat_rejected_count": self.natural_chat_rejected_count,
        }


class NaturalConversationRouter:
    """Deterministic local router for pure conversational utterances.

    ``route(text)`` returns a :class:`NaturalConversationResult` when the whole
    utterance is confidently natural conversation, and ``None`` otherwise so the
    caller continues with the normal pipeline.
    """

    def __init__(
        self,
        enabled: bool = True,
        selector: Optional[Callable[[str, List[str]], str]] = None,
        responses: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.responses = responses or RESPONSES
        self._selector = selector
        self._rotation: Dict[str, int] = {}
        self.metrics = NaturalConversationMetrics()

    # -- construction ------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: Optional[dict] = None,
        selector: Optional[Callable[[str, List[str]], str]] = None,
    ) -> "NaturalConversationRouter":
        """Build from ``config.yaml`` with the env override applied last."""
        section = (config or {}).get("natural_conversation", {}) or {}
        enabled = _config_bool(section.get("enabled", True), default=True)
        env = os.environ.get("FRIDAY_NATURAL_CONVERSATION_ENABLED")
        if env is not None and env.strip() != "":
            enabled = _config_bool(env, default=enabled)
        return cls(enabled=enabled, selector=selector)

    # -- normalization -----------------------------------------------------
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize a *copy* of the utterance for matching only.

        Lowercase, expand contractions, drop fillers and the wake word, and turn
        clause punctuation into a ``|`` segment separator (so "hi, how are you?"
        is evaluated as two segments). Dots inside a token ("node.js", "3.14")
        are left alone. The caller's original text is never modified, so
        context resolution keeps the raw semantics.
        """
        low = (text or "").strip().lower()
        for pattern, replacement in _CONTRACTIONS:
            low = pattern.sub(replacement, low)
        low = low.replace("'", "").replace("\u2019", "")
        # Sentence punctuation becomes an explicit segment separator so a
        # compound utterance ("hi, how are you?") is evaluated part by part.
        # A dot inside a token ("node.js", "3.14") is NOT a separator.
        low = re.sub(r"[!?;:,()\[\]{}]+", " | ", low)
        low = re.sub(r"(?<![a-z0-9])\.|\.(?![a-z0-9])", " | ", low)
        low = re.sub(r"[^a-z0-9\s+#|]", " ", low)
        low = _WAKE_WORD.sub(" ", low)
        tokens = [t for t in re.split(r"\s+", low) if t and (t == "|" or not _FILLER.match(t))]
        # Drop dangling connectives left by fillers ("hi, and" -> "hi").
        while tokens and tokens[0] in ("and", "then", "also", "but", "plus"):
            tokens.pop(0)
        while tokens and tokens[-1] in ("and", "then", "also", "but", "plus"):
            tokens.pop()
        segments: List[str] = []
        for token in tokens:
            if token == "|":
                if segments and segments[-1] != "|":
                    segments.append("|")
                continue
            segments.append(token)
        while segments and segments[0] == "|":
            segments.pop(0)
        while segments and segments[-1] == "|":
            segments.pop()
        return re.sub(r"\s+", " ", " ".join(segments)).strip()

    # -- matching ----------------------------------------------------------
    @staticmethod
    def _segments(normalized: str) -> List[str]:
        if not normalized:
            return []
        return [seg.strip() for seg in _SEGMENT_SPLIT.split(normalized) if seg and seg.strip()]

    @staticmethod
    def _match_intent(segment: str) -> str:
        for intent, pattern in _INTENT_PATTERNS:
            if pattern.match(segment):
                return intent
        return ""

    @staticmethod
    def _substantive_reason(segment: str) -> str:
        """Why *segment* is not pure chatter (empty string when it is safe)."""
        if _SUBSTANTIVE_VERB.search(segment):
            return "substantive_request"
        if _SUBSTANTIVE_WORD.search(segment):
            return "substantive_request"
        if _CONTEXT_DEPENDENT.search(segment):
            return "context_reference"
        if re.search(r"\d", segment):
            return "substantive_request"
        return "not_conversational"

    # -- response selection ------------------------------------------------
    def _select(self, intent: str) -> str:
        pool = self.responses.get(intent) or ["Okay."]
        if self._selector is not None:
            return self._selector(intent, pool)
        index = self._rotation.get(intent, 0)
        self._rotation[intent] = index + 1
        return pool[index % len(pool)]

    # -- public API --------------------------------------------------------
    def route(self, text: str) -> Optional[NaturalConversationResult]:
        """Handle *text* locally, or return ``None`` to defer to the pipeline."""
        started = time.perf_counter()
        raw = text or ""
        normalized = self.normalize(raw)

        if not self.enabled:
            logger.debug("[NATURAL_CHAT] handled=false reason=disabled")
            return None
        if not normalized:
            self.metrics.record_rejected()
            logger.debug("[NATURAL_CHAT] handled=false reason=empty")
            return None

        segments = self._segments(normalized)
        if not segments or len(normalized.split()) > _MAX_TOTAL_TOKENS:
            self.metrics.record_rejected()
            logger.debug(
                "[NATURAL_CHAT] handled=false reason=too_long text=%r", raw,
            )
            return None

        intents: List[str] = []
        for segment in segments:
            if len(segment.split()) > _MAX_SEGMENT_TOKENS:
                self.metrics.record_rejected()
                logger.debug(
                    "[NATURAL_CHAT] handled=false reason=too_long text=%r", raw,
                )
                return None
            intent = self._match_intent(segment)
            if not intent:
                reason = self._substantive_reason(segment)
                self.metrics.record_rejected()
                logger.debug(
                    "[NATURAL_CHAT] handled=false reason=%s text=%r", reason, raw,
                )
                return None
            intents.append(intent)

        # Every segment is conversational: the utterance is pure chatter.
        # The freshest segment wins ("thanks, bye" -> GOODBYE).
        intent = intents[-1]
        response = self._select(intent)
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.metrics.record_handled(intent, latency_ms)
        logger.info(
            "[NATURAL_CHAT] intent=%s handled=true -> local response (no LLM) "
            "raw=%r normalized=%r latency_ms=%.3f",
            intent, raw, normalized, latency_ms,
        )
        return NaturalConversationResult(
            handled=True,
            intent=intent,
            response=response,
            raw_text=raw,
            normalized_text=normalized,
            latency_ms=latency_ms,
        )
