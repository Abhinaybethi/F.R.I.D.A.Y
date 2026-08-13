"""
Target resolver — maps raw target strings to canonical app/website names.

Uses difflib for fuzzy matching (stdlib, no extra deps).
Returns (canonical_name, confidence) where confidence ∈ [0, 1].
"""
from difflib import SequenceMatcher, get_close_matches

# ---------------------------------------------------------------------------
# Known targets
# ---------------------------------------------------------------------------

# Maps aliases (including common STT phonetic errors) → canonical name.
# Only canonical names are used as difflib candidates — keeps the fuzzy
# search space small and predictable.
_APP_ALIASES: dict[str, str] = {
    "chrome":               "chrome",
    "google chrome":        "chrome",
    "edge":                 "edge",
    "microsoft edge":       "edge",
    "firefox":              "firefox",
    "vscode":               "vscode",
    "vs code":              "vscode",
    "visual studio code":   "vscode",
    "code":                 "vscode",
    "notepad":              "notepad",
    "explorer":             "explorer",
    "file explorer":        "explorer",
    "files":                "explorer",
}

_WEBSITE_ALIASES: dict[str, str] = {
    "youtube":  "youtube",
    "google":   "google",
    "github":   "github",
}

# Canonical names used as fuzzy candidates
_APP_CANONICAL      = list(dict.fromkeys(_APP_ALIASES.values()))
_WEBSITE_CANONICAL  = list(dict.fromkeys(_WEBSITE_ALIASES.values()))

# Fuzzy match cutoff (lower than default 0.6 to catch phonetic STT errors
# like "grove" → "chrome" at SequenceMatcher ratio ≈ 0.545)
_CUTOFF = 0.45


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


_PHONETIC_APP_ALIASES: dict[str, tuple[str, float]] = {
    "groom": ("chrome", 0.55),
    "grove": ("chrome", 0.55),
    "groan": ("chrome", 0.55),
}


def resolve_app(target: str) -> tuple[str, float]:
    """
    Returns (canonical_app_name, confidence).
    confidence = 1.0 on exact alias match, 0.55 on phonetic match,
    difflib ratio on fuzzy match, or 0.0 if no match found.
    """
    t = target.lower().strip()
    if t in _APP_ALIASES:
        return _APP_ALIASES[t], 1.0

    if t in _PHONETIC_APP_ALIASES:
        return _PHONETIC_APP_ALIASES[t]

    matches = get_close_matches(t, _APP_CANONICAL, n=1, cutoff=_CUTOFF)
    if matches:
        return matches[0], _ratio(t, matches[0])

    return t, 0.0


def resolve_website(target: str) -> tuple[str, float]:
    """Returns (canonical_website_name, confidence)."""
    t = target.lower().strip()
    if t in _WEBSITE_ALIASES:
        return _WEBSITE_ALIASES[t], 1.0

    matches = get_close_matches(t, _WEBSITE_CANONICAL, n=1, cutoff=_CUTOFF)
    if matches:
        return matches[0], _ratio(t, matches[0])

    return t, 0.0
