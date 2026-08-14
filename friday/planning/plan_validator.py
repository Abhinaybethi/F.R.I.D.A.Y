"""
Upfront plan validator — validates the entire ActionPlan before any step executes.

Phase 8 safety requirement:
    A plan with ANY DENIED step must be rejected as a whole before execution begins.
    This prevents partial execution of a malicious multi-step request.

CONFIRM_REQUIRED steps are valid — they pause execution at that step for user
confirmation. Only DENIED steps abort the plan.
"""
from friday.planning.plan_models import ActionPlan
from friday.safety.permissions import check_permission, PermissionResult


def validate_plan(plan: ActionPlan, permissions: dict) -> tuple[bool, str]:
    """
    Validate every step in the plan against the permission policy.

    Args:
        plan:        The ActionPlan produced by the planner.
        permissions: The tools.permissions dict from config.yaml.

    Returns:
        (True, "")            — plan is safe to execute
        (False, reason_str)   — plan has at least one DENIED step; include why
    """
    for idx, step in enumerate(plan.steps, start=1):
        result = check_permission(step, permissions)
        if result == PermissionResult.DENIED:
            return False, (
                f"Plan step {idx} ({step.action.name} / {step.target!r}) "
                f"is not permitted. Plan rejected."
            )
    return True, ""
