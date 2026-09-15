"""
Deterministic request classifier.

Decides, BEFORE routing, what kind of user request arrived so the assistant
picks the cheapest correct path:

  SESSION_CONTROL   wake/session tokens ("yes", "no", "cancel", "help")
  EXIT              stop / quit / goodbye
  COMMAND           concrete command / compound multi-step request
  CONTEXT_REFERENCE follow-up reference that the deterministic context resolver
                    understands ("play it", "the first one", "close it")
  SCREEN_QUESTION    screen/vision query — answered truthfully as unavailable
  QUESTION           knowledge / explanation question -> reasoner CHAT mode
  CHAT               casual conversation -> reasoner CHAT mode
  UNKNOWN            nothing meaningful

Priority (lowest number first) mirrors the task's ordering: session control,
exit, deterministic commands, multi-step, context references, knowledge
question, chat, unknown.
"""
import re
from enum import Enum, auto

from friday.intent.normalizer import normalize
from friday.utils.logger import get_logger

logger = get_logger(__name__)


class RequestClass(Enum):
    SESSION_CONTROL = auto()
    EXIT = auto()
    COMMAND = auto()
    CONTEXT_REFERENCE = auto()
    SCREEN_QUESTION = auto()
    QUESTION = auto()
    CHAT = auto()
    UNKNOWN = auto()


_EXIT = re.compile(
    r"^(?:goodbye|stop|exit|quit|shut\s+down|stop\s+speaking)$", re.IGNORECASE
)

_SESSION_CONTROL = re.compile(
    r"^(?:yes|yeah|yep|sure|ok|okay|no|nope|nah|cancel|never\s+mind|nevermind|abort|help|repeat|say\s+that\s+again|pardon|what\s+can\s+you\s+do|options|commands"
    r"|go\s+to\s+sleep|stop\s+listening|end\s+session|go\s+idle|sleep)$",
    re.IGNORECASE,
)

# Screen / vision question — if not implemented, answer truthfully.
_SCREEN_QUESTION = re.compile(
    r"^(?:what(?:'?s|\s+is|\s+are)?\s+(?:on|showing\s+on)\s+(?:my|your|the|this)\s*screen"
    r"|(?:what|whats|what's)\s+(?:on\s+(?:my|the|this)\s+screen)"
    r"|what(?:\s+is|\s+are)(?:\s+you)?\s+showing\s+on\s+(?:my|your|the|this)\s+screen"
    r"|\s*(?:look|take\s+a\s+look)\s+at\s+(?:my|the|this|your)\s*screen"
    r"|(?:can|could)\s+you\s+(?:see|describe)\s+(?:my|the|this)\s*screen"
    r"|what\s+do\s+you\s+see)$",
    re.IGNORECASE | re.VERBOSE,
)

# Conversational continuation / reference tokens the deterministic resolver handles.
_CONTEXT_REF = re.compile(
    r"^(?:"
    r"play\s+(?:it|that|this|(?:the\s+)?(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|next|another|last)(?:\s+(?:one|result|video))?|another\s+one|the\s+next\s+one)"  # youtube follow-ups
    r"|(?:next|previous|the\s+next|the\s+previous)\s+(?:video|one|result)"
    r"|the\s+(?:first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|next|another|last)(?:\s+(?:one|result))?"
    r"|(?:open|go\s+to|visit|read|use|select|show|find)\s+(?:the\s+)?(?:first|second|third|1st|2nd|3rd|another|next|last|result\s+\d+)(?:\s+(?:result|one))?"
    r"|close\s+(?:it|that|the\s+app|the\s+(?:chrome|vscode|browser|youtube))"
    r"|open\s+(?:it|that)"
    r"|(?:play|search)\s+(?:it|that|again)"
    r"|search\s+again|search\s+the\s+same\s+thing|same\s+search"
    r"|(?:tell\s+me\s+more|more\s+about\s+it|expand\s+on\s+that|go\s+on)"
    r")$",
    re.IGNORECASE | re.VERBOSE,
)

# Question starters — route to reasoner CHAT mode.
_QUESTION_START = re.compile(
    r"^(?:"
    r"what|whats|what's|why|how|when|where|who|which|whose|whom"
    r"|is|are|am|do\s+you|does\s+it|can\s+you|could\s+you|would\s+you"
    r"|should\s+(?:i|you)|will\s+you|can\s+i|am\s+i|have\s+you"
    r"|explain|describe|define|tell\s+me\s+about|teach\s+me\n|does\s+[a-z]"
    r"|how\s+(?:does|do|is|are|can|could|would)"
    r")",
    re.IGNORECASE | re.VERBOSE,
)

# Chat / casual — reasoner CHAT mode.
_CHAT = re.compile(
    r"^(?:"
    r"let'?s\s+(?:talk|chat|discuss|converse)"
    r"|(?:tell\s+me\s+something\s+(?:interesting|new|fun|exciting))"
    r"|i'?m\s+(?:bored|happy|sad|tired|excited)"
    r"|how\s+are\s+you|how'?s\s+it\s+going|what'?s\s+up|what\s+are\s+you\s+up\s+to"
    r"|are\s+you\s+(?:ok|okay|fine|alive|there|awake)"
    r"|do\s+you\s+(?:like|enjoy|know\s+what\s+i\s+mean|understand\s+me)"
    r"|talk\s+to\s+me|entertain\s+me|impress\s+me"
    r"|what\s+do\s+you\s+(?:think|feel)\s+about\s+.+"
    r"|(?:your|friday'?s)\s+(?:thoughts|opinion)\s+on\s+.+"
    r")",
    re.IGNORECASE | re.VERBOSE,
)

# Compound request markers — deterministic multi-step planning path.
_COMPOUND_MARKERS = re.compile(r"\b(?:and|then|,\s*|;\s*)\b", re.IGNORECASE)

# A compound chunk only counts when at least one segment is a real command
# ("open chrome, play jazz") — not "hi, how are you" or "well, I guess".
_COMMAND_VERBS = re.compile(
    r"^(?:open|launch|start|play|search|go|go\s+to|find|read|close|kill|show|"
    r"tell|set|pause|resume|stop|enable|disable|get|take|turn\s+on|turn\s+off)",
    re.IGNORECASE,
)


def _has_command_verb(segments: list) -> bool:
    return any(_COMMAND_VERBS.match(seg) for seg in segments)


def classify(transcript: str) -> RequestClass:
    """Deterministically classify a transcript (no LLM, no execution)."""
    raw = (transcript or "").strip().strip("?.,! ")
    text = normalize(raw)
    if not text:
        return RequestClass.UNKNOWN

    # 1. Exit
    if _EXIT.match(text):
        return RequestClass.EXIT

    # 2. Session control (confirmations, cancel, help)
    if _SESSION_CONTROL.match(text):
        return RequestClass.SESSION_CONTROL

    # 3. Screen / vision question — truthful unavailable response. Checked
    #    against BOTH forms because normalize() strips "can you"/"please".
    if _SCREEN_QUESTION.match(raw) or _SCREEN_QUESTION.match(text):
        return RequestClass.SCREEN_QUESTION

    # 4. Knowledge question ("what is X ...", "explain X")
    if _QUESTION_START.match(text):
        return RequestClass.QUESTION

    # 5. Casual chat
    if _CHAT.match(text):
        return RequestClass.CHAT

    # 6. Context reference ("play it", "open the first one", "close it")
    if _CONTEXT_REF.match(text):
        return RequestClass.CONTEXT_REFERENCE

    # 7. Compound multi-step command ("open chrome, play jazz").
    #    This runs on the RAW transcript because normalize() strips commas.
    if (
        _COMPOUND_MARKERS.search(raw)
        and len(_COMPOUND_MARKERS.split(raw)) >= 2
        and _has_command_verb(_COMPOUND_MARKERS.split(raw))
    ):
        return RequestClass.COMMAND

    # 8. Anything concrete (router will decide) vs unknown
    return RequestClass.UNKNOWN


def log_class(transcript: str, cls: RequestClass) -> RequestClass:
    logger.info("[CLASSIFIER] %s <- %r", cls.name, (transcript or "")[:80])
    return cls