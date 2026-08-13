"""
Conversation Manager and Context for F.R.I.D.A.Y. v2.

Owns session state, conversation context, pending confirmations,
system command handling, and tool execution dispatch.
"""
from dataclasses import dataclass
from typing import Optional

from friday.core.state import ConversationState, StateMachine
from friday.intent.models import Action, Intent
from friday.intent.router import route
from friday.safety.validator import validate, Policy
from friday.safety.confirmation import parse_confirmation_response, format_confirmation_prompt
from friday.tools import registry
from friday.utils.logger import get_logger

logger = get_logger(__name__)

_HELP_TEXT = (
    "I can open applications and websites, search the web, find files, "
    "open folders, and tell you the time."
)


@dataclass
class ConversationContext:
    last_transcript: str = ""
    last_intent: Optional[Intent] = None
    last_response: str = ""
    pending_intent: Optional[Intent] = None


class ConversationManager:
    """
    Manages state transitions, context, system intents, confirmation, and tool execution.
    """

    def __init__(self, dry_run: bool = True, allow_real_execution: bool = False):
        self.state_machine = StateMachine(ConversationState.IDLE)
        self.context = ConversationContext()
        self.dry_run = dry_run
        self.allow_real_execution = allow_real_execution

    @property
    def state(self) -> ConversationState:
        return self.state_machine.current_state

    def start_session(self):
        """Transition from IDLE to LISTENING."""
        if self.state == ConversationState.IDLE:
            self.state_machine.transition_to(ConversationState.LISTENING)

    def stop_session(self):
        """Transition to STOPPING then IDLE."""
        self.state_machine.transition_to(ConversationState.STOPPING)
        self.state_machine.transition_to(ConversationState.IDLE)

    def handle_transcript(self, transcript: str) -> tuple[str, bool]:
        """
        Process a user transcript.

        Returns:
            (response_text, should_continue)
            where should_continue is False if state becomes STOPPING.
        """
        if not transcript or not transcript.strip():
            return "", True

        self.context.last_transcript = transcript

        # ------------------------------------------------------------------
        # State: WAITING_FOR_CONFIRMATION
        # Priority order:
        #   1. SYSTEM_STOP
        #   2. SYSTEM_CANCEL
        #   3. CONFIRMATION RESPONSE (Affirmative / Negative)
        #   4. NEW USER COMMAND
        #   5. UNKNOWN / Ambiguous Speech
        # ------------------------------------------------------------------
        if self.state == ConversationState.WAITING_FOR_CONFIRMATION:
            from friday.intent.normalizer import normalize
            norm_trans = normalize(transcript)

            # Priority 1: SYSTEM_STOP
            if norm_trans in ("stop", "shut down", "exit", "quit", "goodbye"):
                self.context.pending_intent = None
                self.state_machine.transition_to(ConversationState.STOPPING)
                self.context.last_response = "Goodbye."
                return "Goodbye.", False

            # Priority 2: SYSTEM_CANCEL
            if norm_trans in ("cancel", "never mind", "nevermind", "abort"):
                self.context.pending_intent = None
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = "Cancelled."
                return "Cancelled.", True

            # Priority 3: CONFIRMATION RESPONSE (yes / yeah / no / nope, etc.)
            confirmed = parse_confirmation_response(transcript)

            if confirmed is True:
                pending = self.context.pending_intent
                self.context.pending_intent = None
                self.state_machine.transition_to(ConversationState.EXECUTING)

                result = registry.execute(
                    pending,
                    dry_run=self.dry_run,
                    allow_real_execution=self.allow_real_execution,
                )
                response = result.get("message", "Done.")

                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = response
                return response, True

            elif confirmed is False:
                self.context.pending_intent = None
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = "Cancelled."
                return "Cancelled.", True

            # Priority 4: NEW USER COMMAND
            routed = route(transcript)
            if routed.action != Action.UNKNOWN:
                response = "You have a pending confirmation. Say yes, no, or cancel."
                self.context.last_response = response
                return response, True

            # Priority 5: UNKNOWN / Ambiguous Speech
            response = "Please say yes, no, or cancel."
            self.context.last_response = response
            return response, True


        # ------------------------------------------------------------------
        # Normal State: LISTENING -> PROCESSING
        # ------------------------------------------------------------------
        self.state_machine.transition_to(ConversationState.PROCESSING)

        intent = route(transcript)
        self.context.last_intent = intent

        # System Commands
        if intent.action == Action.SYSTEM_STOP:
            self.state_machine.transition_to(ConversationState.STOPPING)
            self.context.last_response = "Goodbye."
            return "Goodbye.", False

        if intent.action == Action.SYSTEM_CANCEL:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Nothing to cancel."
            return "Nothing to cancel.", True

        if intent.action == Action.SYSTEM_HELP:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = _HELP_TEXT
            return _HELP_TEXT, True

        if intent.action == Action.SYSTEM_REPEAT:
            response = self.context.last_response or "I haven't said anything yet."
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            return response, True

        # Safety Validation
        policy = validate(intent)

        if policy == Policy.REJECT:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            response = "I didn't understand that."
            self.context.last_response = response
            return response, True

        if policy == Policy.CONFIRM:
            self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
            self.context.pending_intent = intent
            prompt = format_confirmation_prompt(intent)
            self.context.last_response = prompt
            return prompt, True

        # Policy: SAFE
        self.state_machine.transition_to(ConversationState.EXECUTING)
        result = registry.execute(
            intent,
            dry_run=self.dry_run,
            allow_real_execution=self.allow_real_execution,
        )
        response = result.get("message", "Done.")

        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = response
        return response, True
