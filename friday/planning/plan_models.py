"""Models for the multi-step action plan."""
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto

from friday.intent.models import Intent


class PlanState(Enum):
    NO_PLAN = auto()
    PLANNING = auto()
    READY = auto()
    EXECUTING = auto()
    WAITING_FOR_CONFIRMATION = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class ActionPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: list[Intent] = field(default_factory=list)
    current_step_index: int = 0
    state: PlanState = PlanState.READY
