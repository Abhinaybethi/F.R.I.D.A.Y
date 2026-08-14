"""
User-facing response formatter for Phase 9 ActionOutcomes.

Renders clean, human-readable feedback based on execution and verification results.
Internal status enums (e.g. VERIFIED_SUCCESS) are NEVER exposed to the end user.
"""
from friday.intent.models import Action, Intent
from friday.verification.models import (
    ExecutionStatus,
    ExecutionResult,
    VerificationStatus,
    VerificationResult,
    FinalStatus,
)


def format_outcome(
    intent: Intent,
    exec_res: ExecutionResult,
    ver_res: VerificationResult,
    is_dry_run: bool,
) -> tuple[FinalStatus, str]:
    """
    Compute FinalStatus and render human-readable user message.

    Returns:
        (FinalStatus, user_message_string)
    """
    # 1. Blocked / Denied
    if exec_res.blocked or exec_res.status in (ExecutionStatus.BLOCKED, ExecutionStatus.DENIED):
        return FinalStatus.BLOCKED, exec_res.message

    # 2. Execution Failed (e.g. unknown app/website target)
    if exec_res.status != ExecutionStatus.SUCCESS:
        action_readable = intent.action.name.replace("_", " ").lower()
        msg = exec_res.message or f"I couldn't {action_readable} {intent.target}."
        return FinalStatus.FAILED, msg

    # 3. Dry Run mode (for successful execution simulation)
    if is_dry_run:
        return FinalStatus.DRY_RUN, exec_res.message

    # 4. Real Execution — Check Verification Result
    if ver_res.status in (VerificationStatus.VERIFIED_SUCCESS, VerificationStatus.NOT_APPLICABLE):
        return FinalStatus.SUCCESS, exec_res.message

    if ver_res.status == VerificationStatus.FAILED:
        action_readable = intent.action.name.replace("_", " ").lower()
        target_str = f" {intent.target}" if intent.target else ""
        return (
            FinalStatus.FAILED,
            f"I tried to {action_readable}{target_str}, but I couldn't confirm that it succeeded.",
        )

    # Fallback for SKIPPED or UNKNOWN verification status
    return FinalStatus.SUCCESS, exec_res.message
