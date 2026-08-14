"""
Tool registry — maps Action → tool function with Phase 9 execution verification.

Every executable action must go through a registered tool.
Raw transcript text never reaches this layer.

Phase 9 additions:
  - Structured ExecutionResult, VerificationResult, and ActionOutcome returned
  - Verification subsystem integration via friday.verification.verifier
  - ActionOutcome provides dict-indexing (__getitem__, get) for 100% backward compatibility
"""
import time

from friday.intent.models import Action, Intent
from friday.safety.permissions import check_permission, PermissionResult
from friday.utils.audit_logger import log_action
from friday.tools import apps, browser, files, system

from friday.verification.models import (
    ExecutionStatus,
    ExecutionResult,
    VerificationStatus,
    VerificationResult,
    FinalStatus,
    ActionOutcome,
)
from friday.verification.verifier import verify_execution
from friday.verification.formatter import format_outcome


def execute(
    intent: Intent,
    dry_run: bool = True,
    allow_real_execution: bool = False,
    permissions: dict | None = None,
) -> ActionOutcome:
    """
    Execute the tool for the given intent, perform verification, and return ActionOutcome.

    Real execution requires ALL THREE gates:
      Gate 1: dry_run == False
      Gate 2: allow_real_execution == True
      Gate 3: permissions[action] == True  AND  permission policy != DENIED

    Returns:
        ActionOutcome containing intent, execution, verification, final_status, and user_message.
        Also acts as a dict for backward compatibility (outcome["success"], outcome["message"]).
    """
    # Resolve permission config — None means "all enabled" for backward compat
    perms = permissions if permissions is not None else _DEFAULT_PERMISSIONS

    t0 = time.perf_counter()

    # --- Gate 3: Permission check ---
    perm_result = check_permission(intent, perms)

    if perm_result == PermissionResult.DENIED:
        exec_res = ExecutionResult(
            action=intent.action,
            target=intent.target,
            status=ExecutionStatus.BLOCKED,
            message=f"Action {intent.action.name}({intent.target!r}) is not permitted.",
            blocked=True,
            execution_latency_ms=0.0,
        )
        ver_res = VerificationResult(
            status=VerificationStatus.SKIPPED,
            message="Verification skipped because permission was denied.",
            verification_latency_ms=0.0,
        )
        outcome = ActionOutcome(
            intent=intent,
            execution=exec_res,
            verification=ver_res,
            final_status=FinalStatus.BLOCKED,
            user_message=exec_res.message,
        )
        log_action(
            action=intent.action.name,
            target=intent.target,
            permission="DENIED",
            confirmation="N/A",
            execution="BLOCKED",
            verification="SKIPPED",
            final_status="BLOCKED",
            result="BLOCKED",
            latency_ms=0.0,
        )
        return outcome

    # Gates 1 & 2: dry-run / real-execution switch
    is_dry_run = dry_run or (not allow_real_execution)
    a = intent.action
    t = intent.target

    confirmation = "CONFIRMED" if perm_result == PermissionResult.CONFIRM_REQUIRED else "N/A"
    execution_mode = "DRY_RUN" if is_dry_run else "REAL"

    # Tool Execution
    t_exec_0 = time.perf_counter()
    raw_result = _dispatch(a, t, is_dry_run)
    exec_latency = (time.perf_counter() - t_exec_0) * 1000

    exec_success = raw_result.get("success", False)
    exec_status = ExecutionStatus.SUCCESS if exec_success else ExecutionStatus.FAILED
    exec_msg = raw_result.get("message", "Done." if exec_success else "Execution failed.")

    exec_res = ExecutionResult(
        action=a,
        target=t,
        status=exec_status,
        message=exec_msg,
        blocked=raw_result.get("blocked", False),
        raw_tool_result=raw_result,
        execution_latency_ms=exec_latency,
    )

    # Verification
    ver_res = verify_execution(intent, exec_res, is_dry_run=is_dry_run)

    # Formatter & Final Status
    final_status, user_msg = format_outcome(intent, exec_res, ver_res, is_dry_run)

    outcome = ActionOutcome(
        intent=intent,
        execution=exec_res,
        verification=ver_res,
        final_status=final_status,
        user_message=user_msg,
    )

    total_latency = (time.perf_counter() - t0) * 1000

    log_action(
        action=a.name,
        target=t,
        permission=perm_result.value.upper(),
        confirmation=confirmation,
        execution=execution_mode if exec_success else "FAILED",
        verification=ver_res.status.value,
        final_status=final_status.value,
        result="SUCCESS" if outcome.is_success else "FAILURE",
        latency_ms=total_latency,
    )

    return outcome


def _dispatch(action: Action, target: str, is_dry_run: bool) -> dict:
    """Pure dispatch table — no policy logic here."""
    if action == Action.OPEN_APP:
        return apps.open_app(target, dry_run=is_dry_run)

    if action == Action.CLOSE_APP:
        return apps.close_app(target, dry_run=is_dry_run)

    if action == Action.OPEN_WEBSITE:
        return browser.open_website(target, dry_run=is_dry_run)

    if action == Action.SEARCH_WEB:
        return browser.search_web(target, dry_run=is_dry_run)

    if action == Action.FIND_FILE:
        return files.find_file(target)         # read-only, no dry_run needed

    if action == Action.OPEN_FILE:
        return files.open_file(target, dry_run=is_dry_run)

    if action == Action.OPEN_FOLDER:
        return files.open_folder(target, dry_run=is_dry_run)

    if action == Action.GET_TIME:
        return system.get_time()               # read-only, no dry_run needed

    return {"success": False, "message": f"No tool registered for action: {action.name}"}


# Backward-compat default: all actions enabled
_DEFAULT_PERMISSIONS: dict = {
    "open_app":     True,
    "close_app":    True,
    "open_folder":  True,
    "open_website": True,
    "search_web":   True,
    "get_time":     True,
    "find_file":    True,
    "open_file":    True,
}
