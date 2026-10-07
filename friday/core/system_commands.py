"""
Deterministic System Router - local answers for locally answerable questions.

The 2026-09-29 voice run sent "can you tell me the current time?" to Bonsai,
which replied that it could not provide the current time. Information that the
local machine can answer deterministically must never reach the LLM.

Scope and rules (2026-09-29 interaction-quality pass):

* this is a *thin* layer in front of the reasoner, not a second command router
  (``friday/intent/router.py`` remains the only command router)
* ``TIME_QUERY`` is the only intent implemented in this pass
* the current time is read from the local system clock through the existing
  ``friday.tools.system.get_time`` helper - nothing is hard-coded
* every other utterance is ignored (``route()`` returns ``None``) so the
  existing pipeline keeps ownership of it

Pipeline position::

    classify
        -> NaturalConversationRouter
        -> DeterministicSystemRouter      <-- this module
        -> transcript-quality guard
        -> context resolution
        -> RAG / research
        -> planner / tools
        -> BonsaiReasoner

Configuration::

    system_commands:
      enabled: true      # FRIDAY_SYSTEM_COMMANDS_ENABLED overrides
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from friday.tools.system import get_time
from friday.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Intent vocabulary
# ---------------------------------------------------------------------------
TIME_QUERY = "TIME_QUERY"

# Anchored, full-segment patterns only: a system query must match in its
# entirety, so "what time is it" is a system query and "set the time to 5" or
# "what time zone is it" is not.
_TIME_PATTERNS = [
    re.compile(
        r"^(?:what|whats)\s+(?:is\s+the\s+)?(?:current\s+|local\s+|right\s+now\s+)?"
        r"time(?:\s+(?:it\s+is|is\s+it))?(?:\s+right\s+now|\s+now)?$"
    ),
    re.compile(
        r"^(?:tell|show|give)\s+me\s+(?:the\s+)?(?:current\s+|local\s+)?"
        r"time(?:\s+please)?$"
    ),
    re.compile(r"^(?:can|could|would)\s+you\s+(?:please\s+)?tell\s+me\s+the\s+time$"),
    re.compile(r"^(?:can|could|would)\s+you\s+(?:please\s+)?tell\s+me\s+(?:the\s+)?current\s+time$"),
    re.compile(r"^(?:do|does)\s+you\s+(?:know|have)\s+(?:the\s+)?time$"),
    re.compile(r"^(?:current\s+|local\s+)?time(?:\s+please|\s+right\s+now|\s+now)?\??$"),
    re.compile(r"^time\s+now$"),
    re.compile(r"^how\s+late\s+is\s+it$"),
    re.compile(r"^what\s+time\s+is\s+it\s+now$"),
    re.compile(r"^give\s+me\s+the\s+time$"),
]


def _clean(text: str) -> str:
    """Lowercase, expand contractions, strip punctuation/fillers/wake word."""
    low = (text or "").strip().lower()
    low = re.sub(r"\bwhat'?s\b", "what is", low)
    low = re.sub(r"\bdo'?you\b", "do you", low)
    low = low.replace("'", "").replace("\u2019", "")
    low = re.sub(r"[^\w\s+#.]", " ", low)
    low = re.sub(r"\bfriday\b", " ", low)
    low = re.sub(r"\b(?:please|now|right|currently|hey|ok|okay)\b", " ", low)
    low = low.replace(".", " ")
    return re.sub(r"\s+", " ", low).strip()


def _handle_time() -> str:
    """Spoken local time, e.g. "It's 11:23 AM." (never hard-coded)."""
    return get_time()["spoken_message"]


# ---------------------------------------------------------------------------
# Result / metrics
# ---------------------------------------------------------------------------
@dataclass
class SystemCommandResult:
    """Outcome of one deterministic system-question attempt."""

    handled: bool
    intent: str = ""
    response: str = ""
    reason: str = ""
    data: Dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0

    def __bool__(self) -> bool:
        return self.handled


@dataclass
class SystemCommandMetrics:
    """Lightweight counters; no metrics dependency is introduced."""

    system_command_count: int = 0
    system_command_llm_bypass_count: int = 0
    system_command_latency_ms_total: float = 0.0
    system_command_latency_ms_max: float = 0.0
    by_intent: Dict[str, int] = field(default_factory=dict)

    def record(self, intent: str, latency_ms: float) -> None:
        self.system_command_count += 1
        # Answered locally => the reasoner, RAG, research and browser are all
        # skipped for this turn.
        self.system_command_llm_bypass_count += 1
        self.system_command_latency_ms_total += latency_ms
        self.system_command_latency_ms_max = max(
            self.system_command_latency_ms_max, latency_ms,
        )
        self.by_intent[intent] = self.by_intent.get(intent, 0) + 1

    def snapshot(self) -> Dict[str, float]:
        avg = (self.system_command_latency_ms_total / self.system_command_count
               if self.system_command_count else 0.0)
        return {
            "system_command_count": self.system_command_count,
            "system_command_llm_bypass_count": self.system_command_llm_bypass_count,
            "system_command_latency_ms_total": round(self.system_command_latency_ms_total, 3),
            "system_command_latency_ms_avg": round(avg, 3),
            "system_command_latency_ms_max": round(self.system_command_latency_ms_max, 3),
        }


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


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
class DeterministicSystemRouter:
    """Answers locally-answerable system questions without any model call."""

    def __init__(
        self,
        enabled: bool = True,
        handlers: Optional[Dict[str, Callable[[], str]]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.metrics = SystemCommandMetrics()
        self._handlers: Dict[str, Callable[[], str]] = dict(handlers or {})
        self._patterns: List[tuple] = [(TIME_QUERY, pattern) for pattern in _TIME_PATTERNS]
        if TIME_QUERY not in self._handlers:
            self._handlers[TIME_QUERY] = _handle_time

    # -- construction ------------------------------------------------------
    @classmethod
    def from_config(cls, config: Optional[dict] = None) -> "DeterministicSystemRouter":
        """Build from ``config.yaml`` with the env override applied last."""
        section = (config or {}).get("system_commands", {}) or {}
        enabled = _config_bool(section.get("enabled", True), default=True)
        env = os.environ.get("FRIDAY_SYSTEM_COMMANDS_ENABLED")
        if env is not None and env.strip() != "":
            enabled = _config_bool(env, default=enabled)
        return cls(enabled=enabled)

    def register(
        self,
        intent: str,
        pattern: "re.Pattern",
        handler: Callable[[], str],
        prepend: bool = True,
    ) -> None:
        """Add a deterministic capability without touching the command router."""
        if prepend:
            self._patterns.insert(0, (intent, pattern))
        else:
            self._patterns.append((intent, pattern))
        self._handlers[intent] = handler

    # -- public API --------------------------------------------------------
    def route(self, text: str) -> Optional[SystemCommandResult]:
        """Answer a system question locally, or return ``None`` to defer."""
        started = time.perf_counter()
        if not self.enabled:
            return None
        cleaned = _clean(text)
        if not cleaned:
            return None
        for intent, pattern in self._patterns:
            if not pattern.match(cleaned):
                continue
            handler = self._handlers.get(intent)
            if handler is None:
                return None
            try:
                response = handler()
            except Exception as exc:  # never break the pipeline
                logger.warning("[SYSTEM_CMD] intent=%s failed: %s", intent, exc)
                return None
            latency_ms = (time.perf_counter() - started) * 1000.0
            self.metrics.record(intent, latency_ms)
            logger.info(
                "[SYSTEM_CMD] intent=%s handled=true -> local system answer "
                "(no LLM) raw=%r normalized=%r latency_ms=%.3f",
                intent, text, cleaned, latency_ms,
            )
            return SystemCommandResult(
                handled=True,
                intent=intent,
                response=response,
                data={"normalized": cleaned},
                latency_ms=latency_ms,
            )
        return None
