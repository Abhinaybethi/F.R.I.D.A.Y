"""Conservative text normalizer — lowercase, punctuation, whitespace only."""
import re


_PREFIX_REGEX = re.compile(
    r"^(?:(?:hey\s+)?friday\s+|please\s+|can\s+you(?:\s+please)?\s+|"
    r"could\s+you(?:\s+please)?\s+|would\s+you(?:\s+please)?\s+|kindly\s+)+"
)

_SUFFIX_REGEX = re.compile(r"(?:\s+for\s+me|\s+please)+$")

def normalize(text: str) -> str:
    """
    Lowercase, strip punctuation, collapse whitespace, and strip known
    harmless conversational prefixes (e.g. 'can you', 'please') so the
    deterministic router can match the core command.
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)   # drop punctuation
    text = re.sub(r"\s+", " ", text).strip()

    # Strip conversational fillers for deterministic matching
    text = _PREFIX_REGEX.sub("", text)
    text = _SUFFIX_REGEX.sub("", text)

    return text.strip()

