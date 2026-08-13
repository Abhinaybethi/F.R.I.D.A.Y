"""
Splits multi-step commands into deterministic plans.
"""
from typing import Optional
from friday.intent.router import route
from friday.intent.models import Action
from friday.planning.plan_models import ActionPlan, PlanState
from friday.planning.context_resolver import ShortTermContext, resolve_context
from friday.utils.logger import get_logger

logger = get_logger(__name__)

MAX_STEPS = 5

def parse_plan(transcript: str, context: ShortTermContext) -> tuple[Optional[ActionPlan], str]:
    """
    Parses a transcript into an ActionPlan.
    Returns (ActionPlan, "") on success.
    Returns (None, error_message) on failure.
    """
    parts = []
    for part in transcript.split(" and "):
        for subpart in part.split(" then "):
            if subpart.strip():
                parts.append(subpart.strip())
                
    if len(parts) > MAX_STEPS:
        return None, "I can only perform up to five actions in one plan."
        
    plan = ActionPlan(state=PlanState.READY)
    
    for i, part in enumerate(parts):
        resolved_text, err = resolve_context(part, context)
        if err:
            return None, err
            
        intent = route(resolved_text)
        if intent.action == Action.UNKNOWN:
            return None, f"I didn't understand part of that command: '{part}'"
            
        plan.steps.append(intent)
        
    logger.info("[PLAN] Created plan with %d steps.", len(plan.steps))
    return plan, ""
