"""Intent models — dataclass + Action enum."""
from dataclasses import dataclass, field
from enum import Enum, auto


class Action(Enum):
    OPEN_APP      = auto()
    CLOSE_APP     = auto()
    OPEN_WEBSITE  = auto()
    SEARCH_WEB    = auto()
    FIND_FILE     = auto()
    OPEN_FILE     = auto()
    OPEN_FOLDER   = auto()
    GET_TIME      = auto()
    SYSTEM_STOP   = auto()
    SYSTEM_CANCEL = auto()
    SYSTEM_HELP   = auto()
    SYSTEM_REPEAT = auto()
    MINIMIZE_APP   = auto()
    MAXIMIZE_APP   = auto()
    TAKE_SCREENSHOT = auto()
    UNKNOWN       = auto()


@dataclass
class Intent:
    action:               Action  = Action.UNKNOWN
    target:               str     = ""
    arguments:            dict    = field(default_factory=dict)
    intent_confidence:    float   = 0.0
    target_confidence:    float   = 1.0
    confidence:           float   = 0.0   # min(intent, target) — set in __post_init__
    requires_confirmation: bool   = False
    raw_text:             str     = ""

    def __post_init__(self):
        # Weakest link wins — a shaky target kills the overall confidence
        self.confidence = min(self.intent_confidence, self.target_confidence)
