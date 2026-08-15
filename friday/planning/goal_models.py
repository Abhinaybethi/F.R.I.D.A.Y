"""
Models for Phase 23 Goal-Oriented Personal Assistant Orchestration.
"""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

from friday.intent.models import Intent
from friday.planning.plan_models import ActionPlan


class GoalState(Enum):
    IDLE = auto()
    IN_PROGRESS = auto()
    WAITING_FOR_USER = auto()
    COMPLETED = auto()
    PAUSED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class GoalContext:
    """
    Parent boundary for multi-turn user goals.
    Persists goal identity, accumulated entities, completed steps, and idempotency keys across turns.
    """
    goal_id: str = field(default_factory=lambda: f"g-{uuid.uuid4().hex[:8]}")
    objective: str = ""
    state: GoalState = GoalState.IDLE
    active_plan: Optional[ActionPlan] = None
    completed_steps: List[Dict[str, Any]] = field(default_factory=list)
    pending_steps: List[Intent] = field(default_factory=list)
    entities: Dict[str, Any] = field(default_factory=dict)
    user_corrections: List[Dict[str, Any]] = field(default_factory=list)
    idempotency_keys: Set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self):
        self.updated_at = time.time()

    def record_completed_step(self, step_intent: Intent, result: dict, idempotency_key: str):
        self.completed_steps.append({
            "action": step_intent.action.name,
            "target": step_intent.target,
            "result": result,
            "timestamp": time.time(),
            "idempotency_key": idempotency_key
        })
        self.idempotency_keys.add(idempotency_key)
        self.touch()

    def is_step_already_completed(self, idempotency_key: str) -> bool:
        return idempotency_key in self.idempotency_keys
