"""
Phase 9 Core Verifier Orchestrator.

Routes an Intent + ExecutionResult to the appropriate action verifier.
"""
import time
from typing import Callable, Optional

from friday.intent.models import Action, Intent
from friday.verification.models import (
    ExecutionStatus,
    ExecutionResult,
    VerificationStatus,
    VerificationResult,
)
from friday.verification import action_verifiers

_VERIFIER_TABLE: dict[Action, Callable[[str, bool], VerificationResult]] = {
    Action.OPEN_APP:     action_verifiers.verify_open_app,
    Action.CLOSE_APP:    action_verifiers.verify_close_app,
    Action.OPEN_FOLDER:  action_verifiers.verify_open_folder,
    Action.OPEN_WEBSITE: action_verifiers.verify_open_website,
    Action.SEARCH_WEB:   action_verifiers.verify_search_web,
    Action.GET_TIME:     action_verifiers.verify_get_time,
    Action.FIND_FILE:    action_verifiers.verify_find_file,
    Action.OPEN_FILE:    action_verifiers.verify_open_file,
}


def verify_execution(
    intent: Intent,
    execution_result: ExecutionResult,
    is_dry_run: bool = True,
) -> VerificationResult:
    """
    Verify the execution outcome for ``intent``.

    If execution failed, was blocked, or denied, verification is skipped.

    Args:
        intent:           The intent being executed.
        execution_result: The ExecutionResult object returned from tool dispatch.
        is_dry_run:       Whether dry-run mode is active.

    Returns:
        VerificationResult describing the observation outcome.
    """
    t0 = time.perf_counter()

    # Skip verification if execution did not succeed
    if execution_result.status != ExecutionStatus.SUCCESS:
        return VerificationResult(
            status=VerificationStatus.SKIPPED,
            message=f"Verification skipped because execution status was {execution_result.status.value}.",
            verification_latency_ms=(time.perf_counter() - t0) * 1000,
        )

    verifier_func = _VERIFIER_TABLE.get(intent.action)
    if not verifier_func:
        return VerificationResult(
            status=VerificationStatus.NOT_APPLICABLE,
            message=f"No verifier registered for action {intent.action.name}.",
            verification_latency_ms=(time.perf_counter() - t0) * 1000,
        )

    v_result = verifier_func(intent.target, is_dry_run)
    v_result.verification_latency_ms = (time.perf_counter() - t0) * 1000
    return v_result
