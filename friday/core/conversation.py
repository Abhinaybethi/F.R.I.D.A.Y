"""
Conversation Manager and Context for F.R.I.D.A.Y. v2.

Owns session state, conversation context, pending confirmations,
system command handling, and tool execution dispatch.
"""
from dataclasses import dataclass, field
from typing import Optional
import time

from friday.core.state import ConversationState, StateMachine
from friday.intent.models import Action, Intent
from friday.intent.router import route
from friday.intent.normalizer import normalize
from friday.safety.validator import validate, Policy
from friday.safety.confirmation import parse_confirmation_response, format_confirmation_prompt
from friday.tools import registry
from friday.utils.logger import get_logger

from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.goal_models import GoalContext, GoalState
from friday.planning.planner import parse_plan
from friday.planning.executor import execute_plan_step
from friday.planning.plan_validator import validate_plan
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.reasoning.interface import Reasoner
from friday.reasoning.local_reasoner import OllamaReasoner
from friday.reasoning.gating import should_call_reasoner

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
    confirmation_start_time: float = 0.0

    # Phase 6 & 22 & 23
    current_plan: Optional[ActionPlan] = None
    current_goal: Optional[GoalContext] = None
    last_search_query: str = ""
    last_search_results: list = field(default_factory=list)
    last_tool_result: dict = None

    # Phase 20: N-turn rolling context
    history: list[dict] = field(default_factory=list)

    def push_turn(self):
        if self.last_transcript or self.last_intent:
            self.history.append({
                "transcript": self.last_transcript,
                "intent": self.last_intent,
                "response": self.last_response,
                "tool_result": self.last_tool_result,
                "search_query": self.last_search_query,
            })
            if len(self.history) > 5:
                self.history.pop(0)


def _extract_results(res_obj) -> list:
    if not res_obj:
        return []
    if isinstance(res_obj, dict):
        return res_obj.get("results") or []
    if hasattr(res_obj, "execution") and hasattr(res_obj.execution, "raw_tool_result"):
        raw = res_obj.execution.raw_tool_result
        if isinstance(raw, dict):
            return raw.get("results") or []
    if hasattr(res_obj, "raw_tool_result") and isinstance(res_obj.raw_tool_result, dict):
        return res_obj.raw_tool_result.get("results") or []
    return []


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
        if self.state_machine.current_state == ConversationState.WAITING_FOR_CONFIRMATION:
            if self.context.confirmation_start_time > 0 and (time.time() - self.context.confirmation_start_time > 30.0):
                logger.info("Confirmation timeout expired. Auto-reverting state to LISTENING.")
                self.context.pending_intent = None
                if self.context.current_plan:
                    self.context.current_plan.state = PlanState.CANCELLED
                    self.context.current_plan = None
                self.state_machine.transition_to(ConversationState.LISTENING)
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
        target = self.context.last_intent.target if self.context.last_intent else ""
        search_results = getattr(self.context, "last_search_results", None) or _extract_results(self.context.last_tool_result)

        tool_res_dict = self.context.last_tool_result if isinstance(self.context.last_tool_result, dict) else (
            self.context.last_tool_result.execution.raw_tool_result if hasattr(self.context.last_tool_result, "execution") else None
        )

        goal_entities = dict(self.context.current_goal.entities) if self.context.current_goal else {}
        if self.context.last_search_results == [] and self.context.last_tool_result is None:
            goal_entities.pop("search_results", None)

        return ShortTermContext(
            last_search_query=self.context.last_search_query,
            last_search_results=search_results,
            last_tool_result=tool_res_dict,
            last_action=action,
            last_target=target,
            last_transcript=self.context.last_transcript,
            last_response=self.context.last_response,
            history=self.context.history,
            goal_entities=goal_entities
        )

    def _continue_plan(self, is_resume: bool = False) -> tuple[str, bool]:
        """Runs the execution loop for the current plan."""
        plan = self.context.current_plan
        responses = []
        first_step = True

        if not self.context.current_goal:
            self.context.current_goal = GoalContext(
                objective=self.context.last_transcript,
                state=GoalState.IN_PROGRESS,
                active_plan=plan
            )
        else:
            self.context.current_goal.active_plan = plan
            self.context.current_goal.state = GoalState.IN_PROGRESS

        while plan.state in (PlanState.READY, PlanState.EXECUTING):
            if self.state_machine.current_state != ConversationState.EXECUTING:
                self.state_machine.transition_to(ConversationState.EXECUTING)

            if plan.current_step_index < len(plan.steps):
                step_intent = plan.steps[plan.current_step_index]
                self.context.last_intent = step_intent

            is_confirmed = is_resume and first_step
            response, requires_conf, is_completed, tool_result = execute_plan_step(
                plan, self.dry_run, self.allow_real_execution,
                is_confirmed=is_confirmed, permissions=self.permissions,
                goal_context=self.context.current_goal
            )
            first_step = False

            if response:
                responses.append(response)

            if tool_result:
                self.context.last_tool_result = tool_result
                if step_intent.action == Action.SEARCH_WEB:
                    self.context.last_search_query = step_intent.target
                if self.context.current_goal:
                    if step_intent.target:
                        self.context.current_goal.entities["last_target"] = step_intent.target
                    if step_intent.action == Action.SEARCH_WEB:
                        res_items = _extract_results(tool_result)
                        if res_items:
                            self.context.current_goal.entities["search_results"] = res_items

            if requires_conf:
                if self.context.current_goal:
                    self.context.current_goal.state = GoalState.WAITING_FOR_USER
                self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
                self.context.confirmation_start_time = time.time()
                self.context.last_response = " ".join(responses)
                return self.context.last_response, True

            if is_completed:
                break

        # Plan completed or failed
        if plan.state == PlanState.COMPLETED:
            if self.context.current_goal:
                self.context.current_goal.state = GoalState.COMPLETED
            self.context.current_plan = None
        elif plan.state in (PlanState.FAILED, PlanState.CANCELLED):
            if self.context.current_goal:
                self.context.current_goal.state = GoalState.FAILED
            self.context.current_plan = None

        final_response = " ".join(responses) if responses else "Done."

        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = final_response
        self.context.push_turn()
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

            if self.state == ConversationState.LISTENING:
                self.state_machine.transition_to(ConversationState.PROCESSING)
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Cancelled."
            return "Cancelled.", True

        # ------------------------------------------------------------------
        # State: WAITING_FOR_CONFIRMATION
        # ------------------------------------------------------------------
        if self.state == ConversationState.WAITING_FOR_CONFIRMATION:
            if time.time() - self.context.confirmation_start_time > 30.0:
                logger.info("Confirmation timeout expired. Resetting state.")
                self.context.pending_intent = None
                if self.context.current_plan:
                    self.context.current_plan.state = PlanState.CANCELLED
                    self.context.current_plan = None
                self.state_machine.transition_to(ConversationState.LISTENING)
                # Fall through to treat the current transcript as a new command
            else:
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
                    if result:
                        self.context.last_tool_result = result
                        raw_dict = result.raw_tool_result if hasattr(result, "raw_tool_result") and isinstance(result.raw_tool_result, dict) else (result if isinstance(result, dict) else {})
                        if raw_dict.get("results"):
                            self.context.last_search_results = raw_dict.get("results")
                        if pending.action == Action.SEARCH_WEB:
                            self.context.last_search_query = pending.target
                        if self.context.current_goal:
                            if pending.target:
                                self.context.current_goal.entities["last_target"] = pending.target

                    if self.context.current_goal:
                        self.context.current_goal.state = GoalState.COMPLETED

                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = result.get("spoken_message") or result.get("message", "Done.")
                    self.context.push_turn()
                    return self.context.last_response, True

                elif confirmed is False:
                    self.context.pending_intent = None
                    if self.context.current_plan:
                        self.context.current_plan.state = PlanState.CANCELLED
                        self.context.current_plan = None

                    # If user said "no, <new command>", process new transcript
                    if len(transcript.strip().split()) > 1 and not transcript.strip().lower() in ("no", "cancel", "never mind", "nevermind", "abort", "n"):
                        self.state_machine.transition_to(ConversationState.PROCESSING)
                        st_text = transcript.strip()
                        if st_text.lower().startswith("no, "):
                            st_text = st_text[4:].strip()
                        resolved_text, err = resolve_context(st_text, self._get_short_term_context())
                        if not err:
                            intent = route(resolved_text)
                            if intent.action != Action.UNKNOWN:
                                self.context.last_intent = intent
                                policy = validate(intent)
                                if policy == Policy.SAFE:
                                    self.state_machine.transition_to(ConversationState.EXECUTING)
                                    result = registry.execute(
                                        intent, dry_run=self.dry_run,
                                        allow_real_execution=self.allow_real_execution,
                                        permissions=self.permissions
                                    )
                                    if isinstance(result, dict) and result.get("results"):
                                        self.context.last_search_results = result.get("results")
                                    self.context.last_tool_result = result
                                    self.state_machine.transition_to(ConversationState.RESPONDING)
                                    self.state_machine.transition_to(ConversationState.LISTENING)
                                    self.context.last_response = result.get("spoken_message") or result.get("message", "Done.")
                                    self.context.push_turn()
                                    return self.context.last_response, True

                    self.state_machine.transition_to(ConversationState.RESPONDING)
                    self.state_machine.transition_to(ConversationState.LISTENING)
                    self.context.last_response = "Cancelled."
                    self.context.push_turn()
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

        low_trans = transcript.lower().strip()
        is_correction = self.context.last_intent and (
            low_trans.startswith("no, i meant ") or low_trans.startswith("i meant ") or
            low_trans.startswith("no, the ") or low_trans.startswith("no, search ") or
            low_trans.startswith("no, ")
        )
        if is_correction:
            corr_target = low_trans.replace("no, i meant ", "").replace("i meant ", "").replace("no, search ", "").replace("no, ", "").strip()
            if corr_target.endswith(" instead"):
                corr_target = corr_target[:-8].strip()
            resolved_text, _ = resolve_context(corr_target, st_context)
            intent = route(resolved_text)
            if intent.action == Action.UNKNOWN or intent.confidence < 0.85:
                act = self.context.last_intent.action
                if act == Action.SEARCH_WEB:
                    resolved_text = f"search for {corr_target}"
                elif act == Action.OPEN_WEBSITE:
                    resolved_text = f"go to {corr_target}"
                elif act == Action.READ_WEBSITE:
                    resolved_text = f"read {corr_target}"
                elif act == Action.OPEN_APP:
                    resolved_text = f"open {corr_target}"
                elif act == Action.CLOSE_APP:
                    resolved_text = f"close {corr_target}"
                elif act == Action.FIND_FILE:
                    resolved_text = f"find file {corr_target}"
                else:
                    resolved_text = corr_target
                intent = route(resolved_text)
        else:
            intent = route(resolved_text)

        # --- Local Reasoner Fallback Gate ---
        call_reasoner, gating_reason = should_call_reasoner(
            resolved_text,
            intent,
            is_in_confirmation=(self.state == ConversationState.WAITING_FOR_CONFIRMATION),
        )
        if call_reasoner and self.reasoner and self.reasoner.is_available():
            logger.info("[REASONER] %s -> invoking reasoner layer", gating_reason)
            try:
                reasoned = self.reasoner.request(resolved_text, st_context)
            except Exception as e:
                logger.warning("[REASONER] Reasoner request failed: %s", e)
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                err_msg = "Reasoning service unavailable."
                self.context.last_response = err_msg
                self.context.push_turn()
                return err_msg, True

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
                self.context.push_turn()
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
            self.context.push_turn()
            return response, True

        if not self.context.current_goal:
            self.context.current_goal = GoalContext(objective=transcript, state=GoalState.IN_PROGRESS)

        if policy == Policy.CONFIRM:
            if self.context.current_goal:
                self.context.current_goal.state = GoalState.WAITING_FOR_USER
            self.context.pending_intent = intent
            self.context.confirmation_start_time = time.time()
            self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
            prompt = format_confirmation_prompt(intent)
            self.context.last_response = prompt
            return prompt, True

        # Policy: SAFE
        self.state_machine.transition_to(ConversationState.EXECUTING)
        result = registry.execute(
            intent,
            dry_run=self.dry_run,
            allow_real_execution=self.allow_real_execution,
            permissions=self.permissions,
        )

        if result:
            self.context.last_tool_result = result
            res_list = _extract_results(result)
            if res_list:
                self.context.last_search_results = res_list
            if intent.action == Action.SEARCH_WEB:
                self.context.last_search_query = intent.target
            if self.context.current_goal:
                if intent.target:
                    self.context.current_goal.entities["last_target"] = intent.target
                if res_list:
                    self.context.current_goal.entities["search_results"] = res_list

        if self.context.current_goal:
            self.context.current_goal.state = GoalState.COMPLETED

        response = result.get("spoken_message") or result.get("message", "Done.")

        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = response
        self.context.push_turn()
        return response, True
