"""
Phase 9 Structured Result Models.

Explicitly separates:
  1. ExecutionStatus   — Did the tool call execute / complete without error?
  2. VerificationStatus — Was observable evidence found that the action succeeded?
  3. FinalStatus        — Aggregated status for conversation control and TTS.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any

from friday.intent.models import Action, Intent


class ExecutionStatus(Enum):
    SUCCESS               = "SUCCESS"
    FAILED                = "FAILED"
    BLOCKED               = "BLOCKED"
    DENIED                = "DENIED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"


class VerificationStatus(Enum):
    VERIFIED_SUCCESS      = "VERIFIED_SUCCESS"
    FAILED                = "FAILED"
    NOT_APPLICABLE        = "NOT_APPLICABLE"
    DRY_RUN               = "DRY_RUN"
    SKIPPED               = "SKIPPED"


class FinalStatus(Enum):
    SUCCESS               = "SUCCESS"
    FAILED                = "FAILED"
    BLOCKED               = "BLOCKED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    DRY_RUN               = "DRY_RUN"


@dataclass
class ExecutionResult:
    action: Action
    target: str
    status: ExecutionStatus
    message: str
    blocked: bool = False
    raw_tool_result: dict = field(default_factory=dict)
    execution_latency_ms: float = 0.0


@dataclass
class VerificationResult:
    status: VerificationStatus
    message: str
    details: dict = field(default_factory=dict)
    verification_latency_ms: float = 0.0


@dataclass
class ActionOutcome:
    intent: Intent
    execution: ExecutionResult
    verification: VerificationResult
    final_status: FinalStatus
    user_message: str

    @property
    def is_success(self) -> bool:
        """True if the action ended in FinalStatus.SUCCESS or FinalStatus.DRY_RUN."""
        return self.final_status in (FinalStatus.SUCCESS, FinalStatus.DRY_RUN)

    def __getitem__(self, key: str) -> Any:
        """Dict-compatibility accessor for backward compatibility."""
        if key == "success":
            return self.is_success
        if key == "message":
            return self.user_message
        if key == "blocked":
            return self.execution.blocked
        if key == "outcome":
            return self
        if key in self.execution.raw_tool_result:
            return self.execution.raw_tool_result[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-compatibility get() for backward compatibility."""
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        """Dict-compatibility in operator."""
        if key in ("success", "message", "blocked", "outcome"):
            return True
        return key in self.execution.raw_tool_result
