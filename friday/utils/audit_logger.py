"""
Structured audit logger for tool execution and verification events.

Every tool execution emits a single structured log line
to logs/friday_audit.log (separate from the main debug log).

Format:
    [ACTION] action=OPEN_APP target='chrome' permission=ALLOWED
             confirmation=N/A execution=SUCCESS verification=VERIFIED_SUCCESS
             final=SUCCESS latency_ms=12.4

Never logs secrets or user personal data beyond the action target string.
"""
import logging
import time
from pathlib import Path

_LOG_PATH = Path(__file__).parent.parent.parent / "logs" / "friday_audit.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_audit = logging.getLogger("friday.audit")
if not _audit.handlers:
    _handler = logging.FileHandler(str(_LOG_PATH), encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _audit.addHandler(_handler)
    _audit.setLevel(logging.INFO)
    _audit.propagate = False


def log_action(
    *,
    action: str,
    target: str,
    permission: str,
    confirmation: str,
    execution: str,
    result: str,
    verification: str = "N/A",
    final_status: str = "N/A",
    latency_ms: float = 0.0,
) -> None:
    """
    Emit one structured audit line.

    Args:
        action:       Action enum name, e.g. "OPEN_APP"
        target:       Canonical target string, e.g. "chrome"
        permission:   "ALLOWED" | "CONFIRM_REQUIRED" | "DENIED"
        confirmation: "NOT_REQUIRED" | "PENDING" | "CONFIRMED" | "N/A"
        execution:    "SUCCESS" | "FAILED" | "BLOCKED" | "DENIED" | "DRY_RUN"
        result:       "SUCCESS" | "FAILURE" | "BLOCKED" | "N/A" (legacy compat)
        verification: "VERIFIED_SUCCESS" | "FAILED" | "NOT_APPLICABLE" | "DRY_RUN" | "SKIPPED"
        final_status: "SUCCESS" | "FAILED" | "BLOCKED" | "CONFIRMATION_REQUIRED" | "DRY_RUN"
        latency_ms:   Wall-clock milliseconds for tool call + verification
    """
    _audit.info(
        "[ACTION] action=%s target=%r permission=%s confirmation=%s "
        "execution=%s verification=%s final=%s result=%s latency_ms=%.1f",
        action, target, permission, confirmation, execution, verification, final_status, result, latency_ms,
    )
