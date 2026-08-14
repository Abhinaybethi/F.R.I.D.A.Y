"""
Executes ActionPlans sequentially.
"""
from typing import Optional
from friday.planning.plan_models import ActionPlan, PlanState
from friday.intent.models import Intent
from friday.safety.validator import validate, Policy
from friday.safety.confirmation import format_confirmation_prompt
from friday.tools import registry
from friday.utils.logger import get_logger

logger = get_logger(__name__)

def execute_plan_step(
    plan: ActionPlan, 
    dry_run: bool = True, 
    allow_real_execution: bool = False,
    is_confirmed: bool = False,
    permissions: Optional[dict] = None,
) -> tuple[str, bool, bool, dict]:
    """
    Executes the current step of the plan.
    
    Returns:
        (response_text, requires_confirmation, plan_completed, tool_result)
    """
    if plan.state not in (PlanState.READY, PlanState.EXECUTING):
        return "Plan is not ready to execute.", False, True, {}
        
    if plan.current_step_index >= len(plan.steps):
        plan.state = PlanState.COMPLETED
        logger.info("[PLAN] Completed")
        return "All steps completed.", False, True, {}
        
    step_intent = plan.steps[plan.current_step_index]
    logger.info("[PLAN] Step %d/%d: %s(%s)", plan.current_step_index + 1, len(plan.steps), step_intent.action.name, step_intent.target)
    
    if not is_confirmed:
        policy = validate(step_intent)
        
        if policy == Policy.REJECT:
            plan.state = PlanState.FAILED
            logger.warning("[PLAN] Step %d rejected.", plan.current_step_index + 1)
            return "I cannot safely execute that step.", False, True, {}
            
        if policy == Policy.CONFIRM:
            plan.state = PlanState.WAITING_FOR_CONFIRMATION
            logger.info("[PLAN] Step %d requires confirmation.", plan.current_step_index + 1)
            prompt = format_confirmation_prompt(step_intent)
            return prompt, True, False, {}
        
    # Policy.SAFE
    plan.state = PlanState.EXECUTING
    result = registry.execute(
        step_intent,
        dry_run=dry_run,
        allow_real_execution=allow_real_execution,
        permissions=permissions,
    )
    
    # Check execution and verification success
    if hasattr(result, "is_success"):
        step_success = result.is_success
    else:
        step_success = result.get("success", False)

    response = result.get("message", "Done.")

    if not step_success:
        plan.state = PlanState.FAILED
        logger.warning("[PLAN] Step %d failed execution or verification.", plan.current_step_index + 1)
        return response, False, True, result

    logger.info("[PLAN] Step %d result: success", plan.current_step_index + 1)
    plan.current_step_index += 1
    
    if plan.current_step_index >= len(plan.steps):
        plan.state = PlanState.COMPLETED
        logger.info("[PLAN] Completed")
        return response, False, True, result
        
    return response, False, False, result
