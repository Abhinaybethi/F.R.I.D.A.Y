"""
Deterministic pattern-based command router.

No LLM.  No cloud.  Regex patterns → structured Intent.

Routing priority (first match wins):
  1. GET_TIME        — unambiguous time queries
  2. CLOSE_APP       — "close / quit / exit / kill ..."
  3. SEARCH_WEB      — "search for / look up / google ..."
  4. OPEN_FOLDER     — "open [my] downloads/documents/..."
  5. FIND_FILE       — "find [my] ..."
  6. OPEN_WEBSITE    — "go to / visit / navigate to ..."
  7. OPEN_APP/WEB    — "open / launch / start / run ..."  (resolved by target)
  8. COMPOUND        — "open{target}" with no space (STT artifact like "openvscode")
  9. UNKNOWN
"""
import re

from friday.intent.models import Action, Intent
from friday.intent.normalizer import normalize
from friday.intent.resolver import resolve_app, resolve_website
from friday.intent.confidence import compute

# High confidence for most intent patterns; lower for ambiguous ones.
_HIGH   = 0.98
_MEDIUM = 0.90
_LOW    = 0.75

# OPEN_FOLDER recognises these words as common system folders.
_FOLDERS = r"(downloads?|documents?|desktop|pictures?|music|videos?)"

# Ordered list of (compiled_pattern, handler)
# handler(match) → (Action | None, target_raw, intent_confidence)
# Action=None means "open something — resolve by target type"
_PATTERNS: list[tuple[re.Pattern, callable]] = [
    # System Intents
    (re.compile(r"^(?:stop|shut down|exit|quit|goodbye)$"),
     lambda m: (Action.SYSTEM_STOP, "", 1.0)),

    (re.compile(r"^(?:cancel|never mind|nevermind|abort)$"),
     lambda m: (Action.SYSTEM_CANCEL, "", 1.0)),

    (re.compile(r"^(?:help|what can you do|options|commands)$"),
     lambda m: (Action.SYSTEM_HELP, "", 1.0)),

    (re.compile(r"^(?:repeat|say that again|pardon|what did you say)$"),
     lambda m: (Action.SYSTEM_REPEAT, "", 1.0)),

    # 1. GET_TIME — no target needed
    (re.compile(r"^what(?:s| is)?(?: the)? time(?:(?: is it)?(?: now)?)?$|"
                r"^(?:current time|time now|tell me the time)$"),
     lambda m: (Action.GET_TIME, "", _HIGH)),

    # 2. CLOSE_APP
    (re.compile(r"^(?:close|quit|exit|kill|stop|terminate)\s+(?:the\s+)?(.+)$"),
     lambda m: (Action.CLOSE_APP, m.group(1), _HIGH)),

    # 3. SEARCH_WEB
    (re.compile(r"^(?:search(?:\s+(?:for|the web for|online for))?|"
                r"look up|google|find online)\s+(.+)$"),
     lambda m: (Action.SEARCH_WEB, m.group(1), _MEDIUM)),

    # 4. OPEN_FOLDER — specific system folders
    (re.compile(r"^open(?:\s+my)?\s+" + _FOLDERS + r"(?:\s+folder)?$"),
     lambda m: (Action.OPEN_FOLDER, m.group(1), _HIGH)),

    # 5. FIND_FILE
    (re.compile(r"^find(?:\s+my)?\s+(.+)$"),
     lambda m: (Action.FIND_FILE, m.group(1), _MEDIUM)),

    # 6. OPEN_WEBSITE (explicit)
    (re.compile(r"^(?:go to|visit|navigate to|browse to|open website)\s+(.+)$"),
     lambda m: (Action.OPEN_WEBSITE, m.group(1), _MEDIUM)),

    # 7. OPEN — "open / launch / start / run X" (resolve by target)
    (re.compile(r"^(?:open|launch|start|run)\s+(?:the\s+|my\s+)?(.+)$"),
     lambda m: (None, m.group(1), _MEDIUM)),

    # 8. COMPOUND — STT artifact: "openvscode", "closechrome" (no space)
    (re.compile(r"^(open|close|launch)([\w]+)$"),
     lambda m: (
         Action.CLOSE_APP if m.group(1) == "close" else None,
         m.group(2),
         _LOW,
     )),
]


def _resolve_open(target_raw: str) -> tuple[Action, str, float]:
    """
    Decide OPEN_APP vs OPEN_WEBSITE based on which resolver wins.
    """
    app_name,  app_conf  = resolve_app(target_raw)
    site_name, site_conf = resolve_website(target_raw)

    if site_conf > app_conf and site_conf > 0.7:
        return Action.OPEN_WEBSITE, site_name, site_conf
    if app_conf > 0.0:
        return Action.OPEN_APP, app_name, app_conf
    # Unknown target — still classify as OPEN_APP but with zero confidence
    return Action.OPEN_APP, target_raw, 0.0


def route(raw_text: str) -> Intent:
    """
    Classify ``raw_text`` (raw STT transcript) into a structured Intent.

    Never executes anything.  Returns Intent(action=UNKNOWN) when no pattern
    matches or confidence is too low to be meaningful.
    """
    text = normalize(raw_text)

    for pattern, handler in _PATTERNS:
        m = pattern.match(text)
        if not m:
            continue

        action, target_raw, intent_conf = handler(m)

        # --- resolve action and target ---
        if action is None:
            # "open X" — let the target decide whether it's app or website
            action, target_name, target_conf = _resolve_open(target_raw)

        elif action == Action.CLOSE_APP:
            target_name, target_conf = resolve_app(target_raw)
            if target_conf == 0.0:
                action = Action.UNKNOWN

        elif action == Action.OPEN_WEBSITE:
            target_name, target_conf = resolve_website(target_raw)

        elif action in (
            Action.SEARCH_WEB, Action.FIND_FILE, Action.GET_TIME,
            Action.SYSTEM_STOP, Action.SYSTEM_CANCEL, Action.SYSTEM_HELP, Action.SYSTEM_REPEAT
        ):
            target_name, target_conf = target_raw, 1.0

        elif action == Action.OPEN_FOLDER:
            # Normalize folder name (strip trailing 's' for "downloads" → "download")
            target_name = target_raw.lower().rstrip("s")  # "downloads"→"download"
            target_conf = 1.0

        else:
            target_name, target_conf = target_raw, 0.5

        conf = compute(intent_conf, target_conf)
        return Intent(
            action=action,
            target=target_name,
            intent_confidence=intent_conf,
            target_confidence=target_conf,
            confidence=conf,
            requires_confirmation=conf < 0.85,
            raw_text=raw_text,
        )

    # Attempt fuzzy / phonetic target matching before returning UNKNOWN
    from friday.intent.fuzzy_router import fuzzy_route
    fuzzy_match = fuzzy_route(raw_text)
    if fuzzy_match:
        return fuzzy_match

    # No pattern matched
    return Intent(action=Action.UNKNOWN, raw_text=raw_text)
