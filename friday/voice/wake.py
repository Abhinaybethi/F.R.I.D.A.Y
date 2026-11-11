"""Shared wake-word / stop-phrase matching.

Both voice bodies (the dashboard hands-free listener and the CLI assistant)
must agree on what counts as "the wake word". This module is the single
source of truth:

* the configured wake word is always accepted;
* common Whisper renderings of "friday" are accepted as aliases;
* the wake word must *open* the utterance (after optional filler words), so a
  sentence that merely mentions it never wakes FRIDAY;
* stop phrases are recognised by every session owner.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Common Whisper renderings of the default wake word. The configured wake
# word is always added, so custom names still work.
WAKE_ALIASES = {
    "friday": (
        r"friday|fridays|frida|frieda|freddy|freddie|fredi|ferdi|ferdy|"
        r"freedy|fridy|friday'?s|free\s*day|fry\s*day"
    ),
}
WAKE_GREETING = r"(?:hey|ok|okay|hi|hello|yo)?"
# Filler words Whisper commonly puts in front of the wake word. Stripped only
# from the very start so a wake word buried mid-sentence never wakes FRIDAY.
LEAD_FILLER = re.compile(
    r"^(?:(?:um|uh|er|ah|so|and|but|well|oh|alright|all right|okay|ok)[\s,]+)+",
    re.IGNORECASE,
)
_LEAD_IN_COMMAND = re.compile(
    r"^(?:um|uh|er|ah|please|can you|could you|would you)\b[ ,]*",
    re.IGNORECASE,
)

STOP_PHRASES = frozenset({
    "stop", "stop listening", "stop now", "go to sleep", "go idle",
    "end session", "sleep", "that's all", "thats all", "bye", "goodbye",
    "good bye", "see you", "exit",
})
_STOP_PREFIXES = ("stop listening", "go to sleep", "end session", "stop now")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


@lru_cache(maxsize=16)
def _compile(wake_word: str) -> re.Pattern[str]:
    tokens = [token for token in re.split(r"\s+", (wake_word or "friday").strip().lower()) if token]
    word = tokens[-1] if tokens else "friday"
    alias = WAKE_ALIASES.get(word, re.escape(word))
    return re.compile(
        rf"{WAKE_GREETING}[\s,]*\b(?:{alias})\b[\s,.;:!?]*",
        re.IGNORECASE,
    )


class WakeMatcher:
    """Wake/stop phrase matcher configured for one wake word."""

    def __init__(self, wake_word: str = "friday") -> None:
        self.wake_word = (wake_word or "friday").strip().lower()
        self._pattern = _compile(self.wake_word)

    def opens_with_wake_word(self, text: str) -> bool:
        """True only when the wake word opens the utterance (after filler)."""
        if not text:
            return False
        anchored = LEAD_FILLER.sub("", _normalize(text))
        return self._pattern.match(anchored) is not None

    def extract(self, text: str) -> tuple[bool, str]:
        """Split a transcript into ``(wake_detected, trailing_command)``.

        ``"hey friday, what's the weather?"`` -> ``(True, "what's the weather?")``
        ``"hey friday"``                     -> ``(True, "")``
        ``"how are you"``                    -> ``(False, "")``
        """
        if not text:
            return False, ""
        anchored = LEAD_FILLER.sub("", _normalize(text))
        match = self._pattern.match(anchored)
        if not match:
            return False, ""
        remainder = anchored[match.end():].strip(" \t,.;:!?-")
        remainder = _LEAD_IN_COMMAND.sub("", remainder)
        if len(remainder.strip()) < 2:
            return True, ""
        return True, remainder.strip()

    def strip_prefix(self, text: str) -> str:
        """Remove a leading wake phrase, preserving anything after it."""
        norm = _normalize(text)
        lowered = norm.lower()
        for prefix in (f"hey {self.wake_word}", self.wake_word):
            if lowered == prefix:
                return ""
            if lowered.startswith(prefix):
                return norm[len(prefix):].lstrip(" ,.").strip(" ,.")
        return norm

    def is_stop_phrase(self, text: str) -> bool:
        norm = _normalize(text).lower().strip(" .,!?:;")
        if not norm:
            return False
        if norm in STOP_PHRASES:
            return True
        return any(norm.startswith(phrase) for phrase in _STOP_PREFIXES)


def extract_wake_command(text: str, wake_word: str = "friday") -> tuple[bool, str]:
    """Module-level convenience wrapper (kept for existing call sites)."""
    return WakeMatcher(wake_word).extract(text)


def is_stop_phrase(text: str, wake_word: str = "friday") -> bool:
    return WakeMatcher(wake_word).is_stop_phrase(text)


def strip_wake_prefix(text: str, wake_word: str = "friday") -> str:
    return WakeMatcher(wake_word).strip_prefix(text)
