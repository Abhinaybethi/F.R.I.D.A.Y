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
from friday.intent.normalizer import normalize
from friday.safety.validator import validate, Policy
from friday.safety.confirmation import parse_confirmation_response, format_confirmation_prompt
from friday.tools import registry
from friday.utils.logger import get_logger

from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.planner import parse_plan
from friday.planning.executor import execute_plan_step
from friday.planning.plan_validator import validate_plan
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.reasoning.interface import Reasoner
from friday.reasoning.local_reasoner import OllamaReasoner

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
    
    # Phase 6
    current_plan: Optional[ActionPlan] = None
    last_search_query: str = ""
    last_tool_result: dict = None


class ConversationManager:
    """
    Manages state transitions, context, system intents, confirmation, and tool execution.
    """

    def __init__(
        self,
        dry_run: bool = True,
        allow_real_execution: bool = False,
        reasoner: Optional[Reasoner] = None,
        permissions: Optional[dict] = None,
    ):
        self.state_machine = StateMachine(ConversationState.IDLE)
        self.context = ConversationContext()
        self.dry_run = dry_run
        self.allow_real_execution = allow_real_execution
        self.reasoner = reasoner or OllamaReasoner()
        # None means "use registry defaults" (all enabled) — backward compatible
        self.permissions = permissions

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
        
    def _get_short_term_context(self) -> ShortTermContext:
        action = self.context.last_intent.action if self.context.last_intent else None
        return ShortTermContext(
            last_search_query=self.context.last_search_query,
            last_tool_result=self.context.last_tool_result,
            last_action=action,
            last_transcript=self.context.last_transcript,
            last_response=self.context.last_response
        )
        
    def _continue_plan(self, is_resume: bool = False) -> tuple[str, bool]:
        """Runs the execution loop for the current plan."""
        plan = self.context.current_plan
        responses = []
        first_step = True
        
        while plan.state in (PlanState.READY, PlanState.EXECUTING):
            if self.state_machine.current_state != ConversationState.EXECUTING:
                self.state_machine.transition_to(ConversationState.EXECUTING)
            
            if plan.current_step_index < len(plan.steps):
                step_intent = plan.steps[plan.current_step_index]
                self.context.last_intent = step_intent
                
            is_confirmed = is_resume and first_step
            response, requires_conf, is_completed, tool_result = execute_plan_step(
                plan, self.dry_run, self.allow_real_execution,
                is_confirmed=is_confirmed, permissions=self.permissions
            )
            first_step = False
            
            if response:
                responses.append(response)
                
            if tool_result:
                self.context.last_tool_result = tool_result
                if step_intent.action == Action.SEARCH_WEB:
                    self.context.last_search_query = step_intent.target
                    
            if requires_conf:
                self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
                self.context.last_response = " ".join(responses)
                return self.context.last_response, True
                
            if is_completed:
                break
                
        # Plan completed or failed
        if plan.state in (PlanState.COMPLETED, PlanState.FAILED, PlanState.CANCELLED):
            self.context.current_plan = None
            
        final_response = " ".join(responses) if responses else "Done."
        
        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = final_response
        return final_response, True

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
        norm_trans = normalize(transcript)
        
        # Priority 1 & 2: Global System Commands (Stop & Cancel)
        if norm_trans in ("stop", "shut down", "exit", "quit", "goodbye"):
            self.context.pending_intent = None
            if self.context.current_plan:
                self.context.current_plan.state = PlanState.CANCELLED
                self.context.current_plan = None
            self.state_machine.transition_to(ConversationState.STOPPING)
            self.context.last_response = "Goodbye."
            return "Goodbye.", False

        if norm_trans in ("cancel", "never mind", "nevermind", "abort"):
            self.context.pending_intent = None
            if self.context.current_plan:
                self.context.current_plan.state = PlanState.CANCELLED
                self.context.current_plan = None
                
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Cancelled."
            return "Cancelled.", True

        # ------------------------------------------------------------------
        # State: WAITING_FOR_CONFIRMATION
        # ------------------------------------------------------------------
        if self.state == ConversationState.WAITING_FOR_CONFIRMATION:
            confirmed = parse_confirmation_response(transcript)

            if confirmed is True:
                # If we have an active plan, resume it.
                if self.context.current_plan and self.context.current_plan.state == PlanState.WAITING_FOR_CONFIRMATION:
                    self.context.current_plan.state = PlanState.EXECUTING
                    return self._continue_plan(is_resume=True)
                    
                # Otherwise, it's a single intent confirmation
                pending = self.context.pending_intent
                self.context.pending_intent = None
                self.state_machine.transition_to(ConversationState.EXECUTING)

                result = registry.execute(
                    pending,
                    dry_run=self.dry_run,
                    allow_real_execution=self.allow_real_execution,
                    permissions=self.permissions,
                )
                response = result.get("message", "Done.")
                
                if result:
                    self.context.last_tool_result = result
                    if pending.action == Action.SEARCH_WEB:
                        self.context.last_search_query = pending.target

                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = response
                return response, True

            elif confirmed is False:
                self.context.pending_intent = None
                if self.context.current_plan:
                    self.context.current_plan.state = PlanState.CANCELLED
                    self.context.current_plan = None
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = "Cancelled."
                return "Cancelled.", True

            routed = route(transcript)
            if routed.action != Action.UNKNOWN:
                response = "You have a pending confirmation. Say yes, no, or cancel."
                self.context.last_response = response
                return response, True

            response = "Please say yes, no, or cancel."
            self.context.last_response = response
            return response, True


        # ------------------------------------------------------------------
        # Normal State: LISTENING -> PROCESSING
        # ------------------------------------------------------------------
        self.state_machine.transition_to(ConversationState.PROCESSING)
        st_context = self._get_short_term_context()
        
        # Check if multi-step planner is needed
        if " and " in transcript or " then " in transcript:
            plan, err = parse_plan(transcript, st_context)
            if not err:
                # Phase 8: validate the ENTIRE plan before any step executes
                perms = self.permissions if self.permissions is not None else {}
                # Use a fully-enabled default if no permissions were configured
                _DEFAULT_PERMS = {
                    "open_app": True, "close_app": True, "open_folder": True,
                    "open_website": True, "search_web": True, "get_time": True,
                    "find_file": True, "open_file": True,
                }
                effective_perms = perms if perms else _DEFAULT_PERMS
                plan_ok, plan_reason = validate_plan(plan, effective_perms)
                if not plan_ok:
                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = plan_reason
                    return plan_reason, True
                self.context.current_plan = plan
                return self._continue_plan()
                
            # If deterministic planner fails, fall through to single-step/reasoner
            # We don't return the err immediately.
            resolved_text = transcript
        else:
            resolved_text, err = resolve_context(transcript, st_context)
            if err:
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = err
                return err, True
            
        intent = route(resolved_text)
        
        # --- Local Reasoner Fallback ---
        if intent.action == Action.UNKNOWN and self.reasoner and self.reasoner.is_available():
            logger.info("[REASONER] Route unknown, falling back to reasoning layer")
            reasoned = self.reasoner.request(resolved_text, st_context)
            r_type = reasoned.get("type")
            
            if r_type == "plan":
                plan_steps = []
                for s in reasoned.get("steps", []):
                    conf = reasoned.get("confidence", 0.9)
                    plan_steps.append(Intent(
                        action=Action[s["action"]],
                        target=s.get("target", ""),
                        arguments=s.get("arguments", {}),
                        intent_confidence=conf,
                        target_confidence=conf
                    ))
                reasoner_plan = ActionPlan(steps=plan_steps)
                # Phase 8: validate the reasoner-generated plan before any step executes
                _DEFAULT_PERMS = {
                    "open_app": True, "close_app": True, "open_folder": True,
                    "open_website": True, "search_web": True, "get_time": True,
                    "find_file": True, "open_file": True,
                }
                effective_perms = self.permissions if self.permissions else _DEFAULT_PERMS
                plan_ok, plan_reason = validate_plan(reasoner_plan, effective_perms)
                if not plan_ok:
                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = plan_reason
                    return plan_reason, True
                self.context.current_plan = reasoner_plan
                return self._continue_plan()
                
            elif r_type == "intent":
                conf = reasoned.get("confidence", 0.9)
                intent = Intent(
                    action=Action[reasoned["action"]],
                    target=reasoned.get("target", ""),
                    arguments=reasoned.get("arguments", {}),
                    intent_confidence=conf,
                    target_confidence=conf
                )
                
            elif r_type in ("response", "clarification"):
                text = reasoned.get("text") or reasoned.get("question") or "I didn't understand that."
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                self.context.last_response = text
                return text, True
                
        # --- End Reasoner Fallback ---

        self.context.last_intent = intent

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
        
        if result:
            self.context.last_tool_result = result
            if intent.action == Action.SEARCH_WEB:
                self.context.last_search_query = intent.target
                
        response = result.get("message", "Done.")

        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = response
        return response, True
