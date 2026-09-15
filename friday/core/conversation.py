"""
Conversation Manager and Context for F.R.I.D.A.Y. v2.

Owns session state, conversation context, pending confirmations,
system command handling, and tool execution dispatch.
"""
from dataclasses import dataclass, field
from typing import Optional
import time

from friday.core.state import ConversationState, StateMachine
from friday.core.session import ConversationSession
from friday.intent.models import Action, Intent
from friday.intent.router import route
from friday.intent.normalizer import normalize
from friday.intent.classifier import RequestClass, classify, log_class
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

# Surrogate permissions if the caller supplied none — same set the planner used.
_DEFAULT_PERMS = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True,
}

_REASONER_CONF = 0.9


@dataclass
class ConversationContext:
    """Structured working memory for the current conversation / active voice session.

    Ownership rules:
      - ``history`` is an N-turn rolling buffer.
      - ``current_media`` / ``previous_media`` / ``last_search`` are populated
        exclusively by tool-result evidence — never by the LLM.
      - Ephemeral fields (active_goal, pending_reference, current_plan …) are
        cleared on session expiry but media/search context is optionally
        retained so repeated sessions can pick up where a fresh one left off.
    """
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

    # Voice action context (current single-turn state for follow-ups)
    last_opened_application: str = ""
    last_opened_website: str = ""
    active_media: str = ""

    # Phase 20: N-turn rolling context
    history: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Structured working memory — short-term session context
    # ------------------------------------------------------------------
    conversation_turn: int = 0
    active_app: str = ""
    active_website: str = ""

    last_action: dict = field(default_factory=dict)       # {type, query, target}
    last_search: dict = field(default_factory=dict)       # {provider, query, results}
    current_media: dict = field(default_factory=dict)     # {provider, query, title, url, video_id}
    previous_media: list = field(default_factory=list)
    pending_reference: str = ""
    active_goal: str = ""

    def push_turn(self):
        if self.last_transcript or self.last_intent:
            self.conversation_turn += 1
            self.history.append({
                "transcript": self.last_transcript,
                "intent": self.last_intent,
                "response": self.last_response,
                "tool_result": self.last_tool_result,
                "search_query": self.last_search_query,
                "opened_application": self.last_opened_application,
                "opened_website": self.last_opened_website,
                "active_media": self.active_media,
            })
            if len(self.history) > 5:
                self.history.pop(0)

    def clear_ephemeral(self):
        """Clear ephemeral state on session expiry.

        Clears active_goal, pending_reference, current_plan, current_goal,
        pending_intent, and pending_intent.  Retains last_search / current_media
        as optionally-reusable context across sessions.
        """
        self.active_goal = ""
        self.pending_reference = ""
        self.current_plan = None
        self.current_goal = None
        self.pending_intent = None


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
        conversation_timeout_seconds: int = 300,
    ):
        self.state_machine = StateMachine(ConversationState.IDLE)
        self.context = ConversationContext()
        self.session = ConversationSession(timeout_seconds=conversation_timeout_seconds)
        self.dry_run = dry_run
        self.allow_real_execution = allow_real_execution
        self.reasoner = reasoner or OllamaReasoner()
        # None means "use registry defaults" (all enabled) — backward compatible
        self.permissions = permissions

    # ------------------------------------------------------------------
    # Active-session helpers
    # ------------------------------------------------------------------

    def _check_session_expiry(self):
        """End the active session + clear ephemeral context after user inactivity."""
        if self.session.is_expired():
            logger.info("[SESSION] Session timeout reached")
            self.session.end()
            self.context.clear_ephemeral()
            logger.info("[SESSION] Returning to wake-word mode")

    def _end_session_soft(self) -> str:
        """Explicit session end (go to sleep / stop listening) — stays running."""
        self.session.end()
        self.context.clear_ephemeral()
        logger.info("[SESSION] Explicit session end; returning to wake-word mode")
        return "Going to sleep. Say 'Hey Friday' to wake me up."

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
        """Transition from IDLE or STOPPING to LISTENING."""
        if self.state == ConversationState.STOPPING:
            self.state_machine.transition_to(ConversationState.IDLE)
        if self.state == ConversationState.IDLE:
            self.state_machine.transition_to(ConversationState.LISTENING)

    def stop_session(self):
        """Transition to STOPPING then IDLE and reset ephemeral session context."""
        self.context = ConversationContext()
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
            goal_entities=goal_entities,
            active_app=self.context.active_app,
            active_website=self.context.active_website,
            last_search=self.context.last_search or None,
            current_media=self.context.current_media or None,
            previous_media=self.context.previous_media,
            last_action_info=self.context.last_action or None,
            conversation_turn=self.context.conversation_turn,
        )

    @staticmethod
    def _tool_succeeded(result) -> bool:
        """True when a tool result reports success (dict or ActionOutcome)."""
        if not result:
            return False
        if isinstance(result, dict):
            return bool(result.get("success"))
        if hasattr(result, "is_success"):
            return bool(result.is_success)
        if hasattr(result, "execution"):
            return getattr(result.execution, "status", None).name == "SUCCESS"
        return False

    def _record_tool_result(self, intent: Intent, result, res_list: list):
        """Stores tool output and updates structured working memory.

        Memory is updated ONLY on successful tool results — a failed step never
        fabricates media/search/action context (no false memory).
        """
        if not result:
            return
        self.context.last_tool_result = result
        if res_list:
            self.context.last_search_results = res_list

        if not self._tool_succeeded(result):
            return

        self.context.active_goal = intent.raw_text or self.context.last_transcript
        self.context.last_action = {
            "type": intent.action.name,
            "query": intent.target,
            "target": intent.target,
        }

        if intent.action == Action.OPEN_APP:
            self.context.last_opened_application = intent.target or ""
            self.context.active_app = intent.target or ""
        if intent.action == Action.OPEN_WEBSITE:
            self.context.last_opened_website = intent.target or ""
            self.context.active_website = intent.target or ""
        if intent.action in (Action.SEARCH_WEB, Action.PLAY_VIDEO) and intent.target:
            self.context.last_search_query = intent.target
            self.context.active_media = intent.target
        if self.context.current_goal:
            if intent.target:
                self.context.current_goal.entities["last_target"] = intent.target
            if res_list:
                self.context.current_goal.entities["search_results"] = res_list

        # ---- structured media / search evidence (tool-driven, no LLM) ----
        if intent.action == Action.PLAY_VIDEO:
            media = self._media_from_tool_result(intent.target, result)
            if media:
                if self.context.current_media:
                    self.context.previous_media.append(dict(self.context.current_media))
                    if len(self.context.previous_media) > 10:
                        self.context.previous_media.pop(0)
                self.context.current_media = media
                logger.info(
                    "[MEMORY] Current media updated: %s (%s)",
                    media.get("title") or media.get("query"), media.get("video_id") or "",
                )
        elif intent.action == Action.SEARCH_WEB:
            self.context.last_search = {
                "provider": "google",
                "query": intent.target,
                "results": res_list,
            }
            logger.info("[MEMORY] Search context updated: %r", (intent.target or "")[:60])
        logger.info("[MEMORY] Last action updated: %s(%s)", intent.action.name, intent.target or "")

    def _media_from_tool_result(self, target: str, result) -> dict:
        """Extract structured media evidence from a tool result (defaults empty)."""
        result_dict = result if isinstance(result, dict) else (
            result.execution.raw_tool_result if hasattr(result, "execution") and hasattr(result.execution, "raw_tool_result") else {}
        )
        if not isinstance(result_dict, dict):
            return {}
        provider = result_dict.get("provider") or "youtube"
        watch_url = result_dict.get("watch_url") or ""
        video_id = result_dict.get("video_id") or ""
        if not video_id and "watch?v=" in watch_url:
            video_id = watch_url.split("watch?v=", 1)[1].split("&", 1)[0]
        return {
            "provider": provider,
            "query": target,
            "title": result_dict.get("title") or "",
            "url": watch_url or result_dict.get("url") or "",
            "video_id": video_id,
        }

    def _intent_from_reasoned(self, reasoned: dict) -> Intent:
        conf = reasoned.get("confidence", _REASONER_CONF)
        if reasoned.get("action") not in Action._member_names_:
            raise KeyError(reasoned.get("action"))
        return Intent(
            action=Action[reasoned["action"]],
            target=reasoned.get("target", ""),
            arguments=reasoned.get("arguments", {}),
            intent_confidence=conf,
            target_confidence=conf,
        )

    def _reasoned_plan(self, reasoned: dict) -> tuple[Optional[ActionPlan], str]:
        """Builds + validates a reasoner-produced plan. (plan, "") or (None, error)."""
        conf = reasoned.get("confidence", _REASONER_CONF)
        steps = []
        for s in reasoned.get("steps", []):
            if s.get("action") not in Action._member_names_:
                return None, f"Plan contained an unknown action: {s.get('action')!r}"
            steps.append(Intent(
                action=Action[s["action"]],
                target=s.get("target", ""),
                arguments=s.get("arguments", {}),
                intent_confidence=conf,
                target_confidence=conf,
            ))
        plan = ActionPlan(steps=steps)
        perms = self.permissions if self.permissions else _DEFAULT_PERMS
        ok, reason = validate_plan(plan, perms)
        if not ok:
            return None, reason
        return plan, ""

    def _start_reasoned_plan(self, reasoned: dict) -> tuple[str, bool]:
        plan, err = self._reasoned_plan(reasoned)
        if err:
            return self._respond(err)
        self.context.current_plan = plan
        return self._continue_plan()

    def _respond(self, text: str) -> tuple[str, bool]:
        self.state_machine.transition_to(ConversationState.RESPONDING)
        self.state_machine.transition_to(ConversationState.LISTENING)
        self.context.last_response = text
        self.context.push_turn()
        return text, True

    def _answer_memory_question(self, transcript: str) -> str:
        """Answer short-term memory questions directly from structured context.

        Returns a response string when the transcript is a recognised memory
        question and structured context contains the answer; otherwise "".
        """
        text = normalize(transcript).lower().strip("?!. ")
        if not text:
            return ""

        # "what did you just do?" — reconstruct from tool-driven context.
        if (
            "what" in text and any(word in text for word in ("did you just do", "did we just do", "did you do", "did we do", "have you done"))
        ):
            parts = []
            la = self.context.last_action
            if la:
                parts.append(
                    la.get("type", "")
                    .lower()
                    .replace("play_video", "played a video")
                    .replace("open_app", "opened an app")
                    .replace("open_website", "opened a website")
                    .replace("search_web", "searched the web")
                    .replace("_", " ")
                )
                if la.get("target"):
                    parts.append(la["target"])
            elif self.context.last_search_query:
                parts.append(f"searched for {self.context.last_search_query}")
            if parts:
                return "I " + " for ".join(parts) + "."
            if self.context.last_response:
                return f"I said: {self.context.last_response}"
            return "I haven't done anything yet in this conversation."

        # "what are we watching?" / "what video is playing?"
        if "watching" in text or ("what" in text and "video" in text):
            media = self.context.current_media
            if media:
                title = media.get("title") or media.get("query")
                provider = media.get("provider", "youtube")
                return f"We're watching {title} on {provider}."
            if self.context.active_media:
                return f"We're on {self.context.active_media}."
            if self.context.last_search_query:
                return f"We were looking at {self.context.last_search_query}."
            return "We're not watching anything right now."

        # "what did I ask you to search?" / "what was my last search?"
        if "ask" in text and "search" in text or ("last search" in text) or ("search for" in text and "did i" in text):
            query = (self.context.last_search or {}).get("query", "") or self.context.last_search_query
            if query:
                provider = (self.context.last_search or {}).get("provider", "youtube")
                return f"You asked me to search for {query} on {provider}."
            return "You haven't asked me to search for anything yet."

        return ""

    def _chat_response(self, resolved_text: str, st_context: ShortTermContext) -> tuple[str, bool]:
        """
        Reasoner CHAT mode for knowledge questions and casual conversation.
        Never routes simple deterministic commands through the model.
        """
        if self.reasoner and self.reasoner.is_available():
            try:
                reasoned = self.reasoner.request(resolved_text, st_context, mode="chat")
            except Exception as e:
                logger.error("[ERROR] Reasoning server unavailable: %s", e)
                return self._respond("Reasoning service unavailable.")

            r_type = reasoned.get("type")
            if r_type in ("response", "clarification"):
                text = reasoned.get("text") or reasoned.get("question") or "I didn't understand that."
                return self._respond(text)
            if r_type == "plan":
                return self._start_reasoned_plan(reasoned)
            if r_type == "intent":
                # Unexpected but safe: route through normal validated execution.
                try:
                    intent = self._intent_from_reasoned(reasoned)
                except KeyError:
                    return self._respond("I didn't understand that.")
                self.context.last_intent = intent
                policy = validate(intent)
                if policy == Policy.REJECT:
                    return self._respond("I didn't understand that.")
                if policy == Policy.CONFIRM:
                    if self.context.current_goal:
                        self.context.current_goal.state = GoalState.WAITING_FOR_USER
                    self.context.pending_intent = intent
                    self.context.confirmation_start_time = time.time()
                    self.state_machine.transition_to(ConversationState.WAITING_FOR_CONFIRMATION)
                    prompt = format_confirmation_prompt(intent)
                    self.context.last_response = prompt
                    return prompt, True
                return self._execute_single_intent(intent)
            return self._respond("I didn't understand that.")

        return self._respond("I didn't understand that. The reasoning model is unavailable right now.")

    def _execute_single_intent(self, intent: Intent) -> tuple[str, bool]:
        """Validated single-intent execution + context recording (SAFE policy)."""
        self.state_machine.transition_to(ConversationState.EXECUTING)
        result = registry.execute(
            intent,
            dry_run=self.dry_run,
            allow_real_execution=self.allow_real_execution,
            permissions=self.permissions,
        )
        res_list = _extract_results(result) if result else []
        self._record_tool_result(intent, result, res_list)
        if self.context.current_goal:
            self.context.current_goal.state = GoalState.COMPLETED
        response = result.get("spoken_message") or result.get("message", "Done.")
        return self._respond(response)

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
                self._record_tool_result(step_intent, tool_result, _extract_results(tool_result))
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

        # Session lifecycle: expire the active session after user inactivity,
        # then refresh the inactivity timer on every processed interaction.
        self._check_session_expiry()
        self.session.touch()
        self.context.last_transcript = transcript
        norm_trans = normalize(transcript)

        # Priority 0: Explicit session end — exit active conversation, keep running.
        if norm_trans in ("go to sleep", "stop listening", "end session", "go idle", "sleep"):
            response = self._end_session_soft()
            st = self.state_machine.current_state
            if st == ConversationState.STOPPING:
                self.state_machine.transition_to(ConversationState.IDLE)
            if st in (ConversationState.IDLE, ConversationState.STOPPING):
                self.state_machine.transition_to(ConversationState.LISTENING)
            if self.state_machine.current_state == ConversationState.LISTENING:
                self.state_machine.transition_to(ConversationState.PROCESSING)
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = response
            return response, True

        # Priority 1 & 2: Global System Commands (Stop & Cancel)
        if norm_trans in ("stop", "shut down", "exit", "quit", "goodbye"):
            self.session.end()
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

        # Ensure active listening state for incoming commands
        if self.state == ConversationState.STOPPING:
            self.state_machine.transition_to(ConversationState.IDLE)
        if self.state == ConversationState.IDLE:
            self.state_machine.transition_to(ConversationState.LISTENING)

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
                        res_list = _extract_results(result)
                        self._record_tool_result(pending, result, res_list)

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

        # Deterministic request classification (no LLM).
        cls = log_class(transcript, classify(transcript))

        # Screen / vision question — truthful: we have no screen access.
        if cls == RequestClass.SCREEN_QUESTION:
            return self._respond("I don't currently have access to your screen.")

        # Knowledge question / casual chat -> reasoner CHAT mode, unless the
        # deterministic router already knows a concrete command (time, memory).
        if cls in (RequestClass.QUESTION, RequestClass.CHAT):
            memory_answer = self._answer_memory_question(transcript)
            if memory_answer:
                return self._respond(memory_answer)
            early_intent = route(transcript)
            if early_intent.action == Action.UNKNOWN or early_intent.confidence < 0.75:
                resolved_text, _ = resolve_context(transcript, st_context)
                if not resolved_text:
                    resolved_text = transcript
                return self._chat_response(resolved_text, st_context)

        # Check if multi-step planner is needed
        if cls == RequestClass.COMMAND or " and " in transcript or " then " in transcript:
            plan, err = parse_plan(transcript, st_context)
            if not err:
                # Phase 8: validate the ENTIRE plan before any step executes
                effective_perms = self.permissions if self.permissions else _DEFAULT_PERMS
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
                logger.error("[ERROR] Reasoning server unavailable: %s", e)
                self.state_machine.transition_to(ConversationState.RESPONDING)
                self.state_machine.transition_to(ConversationState.LISTENING)
                err_msg = "Reasoning service unavailable."
                self.context.last_response = err_msg
                self.context.push_turn()
                return err_msg, True

            r_type = reasoned.get("type")

            if r_type == "plan":
                return self._start_reasoned_plan(reasoned)

            elif r_type == "intent":
                intent = self._intent_from_reasoned(reasoned)

            elif r_type in ("response", "clarification"):
                text = reasoned.get("text") or reasoned.get("question") or "I didn't understand that."
                return self._respond(text)

        # --- End Reasoner Fallback ---

        self.context.last_intent = intent

        if intent.action != Action.UNKNOWN:
            logger.info(
                "[ROUTER] Deterministic route selected: %s target=%r",
                intent.action.name, intent.target,
            )

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

        if intent.action == Action.SYSTEM_CANCEL:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Cancelled."
            self.context.pending_intent = None
            self.context.current_plan = None
            self.context.current_goal = None
            return "Cancelled.", True

        if intent.action == Action.SYSTEM_STOP:
            self.state_machine.transition_to(ConversationState.RESPONDING)
            self.state_machine.transition_to(ConversationState.LISTENING)
            self.context.last_response = "Stopped."
            return "Stopped.", True

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
        return self._execute_single_intent(intent)
