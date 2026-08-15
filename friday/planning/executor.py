"""
Executes ActionPlans sequentially with step recovery support.
"""
from typing import Optional, Any
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
    goal_context: Optional[Any] = None,
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
    idempotency_key = f"{plan.id}_step_{plan.current_step_index}_{step_intent.action.name}_{step_intent.target}"

    if goal_context and hasattr(goal_context, "is_step_already_completed") and goal_context.is_step_already_completed(idempotency_key):
        logger.info("[GOAL] Step %d already completed (%s). Skipping.", plan.current_step_index + 1, idempotency_key)
        plan.current_step_index += 1
        if plan.current_step_index >= len(plan.steps):
            plan.state = PlanState.COMPLETED
            return "All steps completed.", False, True, {}
        return "Step already completed.", False, False, {}

    logger.info("[PLAN] Step %d/%d: %s(%s)", plan.current_step_index + 1, len(plan.steps), step_intent.action.name, step_intent.target)
    
    if not is_confirmed:
        policy = validate(step_intent)
        
        if policy == Policy.REJECT:
            if plan.current_step_index in plan.fallbacks and plan.fallbacks[plan.current_step_index]:
                fallback_intent = plan.fallbacks[plan.current_step_index].pop(0)
                logger.info("[PLAN] Step %d policy rejected. Retrying with fallback: %s(%s)", plan.current_step_index + 1, fallback_intent.action.name, fallback_intent.target)
                plan.steps[plan.current_step_index] = fallback_intent
                return execute_plan_step(
                    plan, dry_run=dry_run, allow_real_execution=allow_real_execution,
                    is_confirmed=is_confirmed, permissions=permissions
                )
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
        # Check if fallback intent exists for this step
        if plan.current_step_index in plan.fallbacks and plan.fallbacks[plan.current_step_index]:
            fallback_intent = plan.fallbacks[plan.current_step_index].pop(0)
            logger.info("[PLAN] Step %d failed. Retrying with fallback: %s(%s)", plan.current_step_index + 1, fallback_intent.action.name, fallback_intent.target)
            plan.steps[plan.current_step_index] = fallback_intent
            return execute_plan_step(
                plan, dry_run=dry_run, allow_real_execution=allow_real_execution,
                is_confirmed=is_confirmed, permissions=permissions
            )

        plan.state = PlanState.FAILED
        logger.warning("[PLAN] Step %d failed execution or verification.", plan.current_step_index + 1)
        return response, False, True, result

    logger.info("[PLAN] Step %d result: success", plan.current_step_index + 1)
    if goal_context and hasattr(goal_context, "record_completed_step"):
        goal_context.record_completed_step(step_intent, result if isinstance(result, dict) else {}, idempotency_key)
    plan.current_step_index += 1
    
    if plan.current_step_index >= len(plan.steps):
        plan.state = PlanState.COMPLETED
        logger.info("[PLAN] Completed")
        return response, False, True, result
        
    return response, False, False, result
