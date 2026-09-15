"""
Active conversation / voice session owner.

This is the single clean owner of the active-session lifecycle for F.R.I.D.A.Y.
It is deliberately independent of any single caller (voice loop, text loop, or
ConversationManager) so session state is not scattered across modules.

Semantics:
    - ``timeout_seconds`` represents USER INACTIVITY, not total session length.
    - Every new valid interaction calls ``touch()`` which resets the inactivity
      timer.
    - ``is_active()`` returns False once the configured inactivity timeout has
      elapsed, signalling the caller to return to wake-word listening.
"""
from dataclasses import dataclass, field
import time


@dataclass
class ConversationSession:
    """Tracks whether F.R.I.D.A.Y. is in an active conversation and when it expires."""

    active: bool = False
    started_at: float = 0.0
    last_interaction_at: float = 0.0
    timeout_seconds: int = 300

    def __post_init__(self):
        self.timeout_seconds = int(max(30, self.timeout_seconds or 300))

    # -- lifecycle ----------------------------------------------------------

    def start(self, now: float | None = None) -> "ConversationSession":
        """Activate the session and initialise its timestamps."""
        now = time.time() if now is None else now
        self.active = True
        self.started_at = now
        self.last_interaction_at = now
        return self

    def end(self) -> "ConversationSession":
        """Deactivate the session and reset its timestamps."""
        self.active = False
        self.started_at = 0.0
        self.last_interaction_at = 0.0
        return self

    def touch(self, now: float | None = None) -> "ConversationSession":
        """Refresh the inactivity timer. Called after every processed interaction."""
        self.last_interaction_at = time.time() if now is None else now
        return self

    # -- queries ------------------------------------------------------------

    def is_expired(self, now: float | None = None) -> bool:
        """True when the session has gone past its inactivity timeout."""
        if not self.active:
            return False
        now = time.time() if now is None else now
        return (now - self.last_interaction_at) >= self.timeout_seconds

    def is_active(self, now: float | None = None) -> bool:
        """True when the session is active AND has not timed out."""
        return self.active and not self.is_expired(now)

    def remaining_seconds(self, now: float | None = None) -> float:
        """Seconds until the session times out (0 if already expired/inactive)."""
        if not self.active:
            return 0.0
        now = time.time() if now is None else now
        return max(0.0, self.timeout_seconds - (now - self.last_interaction_at))