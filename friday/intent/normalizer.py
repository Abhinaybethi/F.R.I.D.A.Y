"""Conservative text normalizer — lowercase, punctuation, whitespace only.

Also provides deterministic application/entity alias expansion for common STT
mishearing of application names (e.g. "grom" -> chrome).  Aliases are only
expanded when the full token matches a known mishearing, so ordinary words are
never rewritten.
"""
import re


_PREFIX_REGEX = re.compile(
    r"^(?:(?:hey\s+)?friday\s+|please\s+|can\s+you(?:\s+please)?\s+|"
    r"could\s+you(?:\s+please)?\s+|would\s+you(?:\s+please)?\s+|kindly\s+|"
    r"now\s+|okay\s+|ok\s+|then\s+)+"
)

_SUFFIX_REGEX = re.compile(r"(?:\s+for\s+me|\s+please)+$")

# Canonical application name -> set of STT mishearing / informal aliases.
# Token-level, case-insensitive, whole-word replacement only.
_APP_ALIASES: dict[str, tuple[str, ...]] = {
    "chrome": ("grom", "crome", "chrom", "chromy", "chrom browser"),
    "firefox": ("fire fox", "forefox", "far fox"),
    "edge": ("microsoft edge", "ms edge", "bing"),
    "visual studio code": ("vscode", "vs code", "v s code", "studio code"),
    "spotify": ("spodify", "spotifi"),
    "notepad": ("note pad", "notes pad"),
    "word": ("ms word", "microsoft word"),
    "excel": ("ms excel", "microsoft excel"),
    "powershell": ("power shell", "pwsh"),
    "explorer": ("file explorer", "windows explorer"),
}

_ALIAS_ENTRIES = [
    (canonical, tuple(sorted(alias_tokens, key=len, reverse=True)))
    for canonical, alias_tokens in _APP_ALIASES.items()
]

# Precompiled: (canonical, (pattern, ...)) for each alias, matched word-boundary.
_ALIAS_PATTERNS = [
    (canonical, [(re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), alias) for alias in aliases])
    for canonical, aliases in _ALIAS_ENTRIES
]


def normalize_app_aliases(text: str) -> tuple[str, list[str]]:
    """
    Expand known application aliases / STT mishearings in ``text``.

    Returns ``(normalized_text, list_of_changes)`` where each change is a
    ``"alias -> canonical"`` string.  Only full-token matches from the alias
    table are rewritten; arbitrary user text is never modified.
    """
    if not text:
        return text, []
    normalized = text
    changes: list[str] = []
    for canonical, patterns in _ALIAS_PATTERNS:
        for pattern, alias in patterns:
            if pattern.search(normalized):
                was = normalized
                normalized = pattern.sub(canonical, normalized)
                if normalized != was:
                    change = f"{alias} -> {canonical}"
                    if change not in changes:
                        changes.append(change)
    return normalized, changes

def normalize(text: str) -> str:
    """
    Lowercase, strip punctuation, collapse whitespace, and strip known
    harmless conversational prefixes (e.g. 'can you', 'please') so the
    deterministic router can match the core command.
    """
    text = text.lower()

    # Preserve URLs from punctuation stripping
    url_match = re.search(r"https?://\S+", text)
    if url_match:
        url_str = url_match.group(0)
        placeholder = "__URL_PLACEHOLDER__"
        text_no_url = text.replace(url_str, placeholder)
        text_clean = re.sub(r"[^\w\s]", "", text_no_url)
        text = text_clean.replace(placeholder, url_str)
    else:
        text = re.sub(r"[^\w\s]", "", text)

    text = re.sub(r"\s+", " ", text).strip()

    # Strip conversational fillers for deterministic matching
    text = _PREFIX_REGEX.sub("", text)
    text = _SUFFIX_REGEX.sub("", text)

    return text.strip()

