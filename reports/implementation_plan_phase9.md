# Phase 9 — Verification, Observability & Action Feedback
## Implementation Plan

---

## 1. Inspection of Existing Architecture

### 1. Current Architecture Summary
- Voice pipeline: Audio Input -> Silero VAD -> faster-whisper STT -> raw transcript.
- Command pipeline: `ConversationManager.handle_transcript()` -> `normalize()` -> system commands (`stop`/`cancel`).
- Routing & Intent: Multi-step check (` and ` / ` then `) or `resolve_context()` -> `route(resolved_text)`.
- Reasoning fallback: If `Action.UNKNOWN`, falls back to local `OllamaReasoner.request()` -> `parse_reasoning_output()` -> `validate_reasoning_output()`.
- Plan Pre-Validation: `validate_plan()` checks all plan steps against `check_permission()` before execution begins.
- Safety & Confirmation: `validate(intent)` enforces confidence thresholds and `CLOSE_APP` confirmation (`Policy.CONFIRM`).
- Tool execution: `registry.execute()` checks per-action permissions (`check_permission()`), logs audit (`log_action()`), dispatches to tool (`apps`, `browser`, `files`, `system`).
- TTS output: Returns message string to caller for Piper TTS synthesis.

### 2. Existing Execution Flow
```
User Utterance
    ↓
STT Transcript
    ↓
ConversationManager.handle_transcript()
    ↓
Deterministic Router / OllamaReasoner
    ↓
Safety Policy & Upfront Permission Check
    ↓ (Confirmation if required)
tool registry.execute()
    ↓
Tool Function (apps/browser/files/system)
    ↓ returns dict {"success": bool, "message": str}
ConversationManager sets last_response
    ↓
Piper TTS speaks message
```

### 3. Existing Safety Boundaries
- `config.yaml`: `dry_run: true`, `allow_real_execution: false` by default.
- Triple Gate in `registry.execute()`: (1) `dry_run == False`, (2) `allow_real_execution == True`, (3) `permissions[action] == True` and `PermissionResult != DENIED`.
- Explicit Whitelists: `Action` enum (no `RUN_COMMAND`, `DELETE_FILE`, `EXECUTE_CODE`), `apps._APP_EXECUTABLES`, `browser._WEBSITE_URLS`, `files._SAFE_DIRS`.
- Codebase Invariants: Zero `shell=True`, zero `os.system`, zero `eval`/`exec`, no raw transcript text passed to `subprocess.Popen()`.
- Confirmation Gate: `CLOSE_APP` always requires `CONFIRM_REQUIRED` policy and explicit user "yes".

### 4. Existing Tool Result Format
- Tools currently return a simple Python `dict`: `{"success": bool, "message": str, ...}`.
- If permission is denied in `registry.execute()`, returns `{"success": False, "message": str, "blocked": True}`.

### 5. Existing Audit Logging
- `friday/utils/audit_logger.py` emits structured lines to `logs/friday_audit.log`:
  `[ACTION] action=... target=... permission=... confirmation=... execution=... result=... latency_ms=...`
- Currently records execution outcome (`SUCCESS`/`FAILURE`/`BLOCKED`), but lacks verification status and final status.

### 6. Existing Permission Enforcement
- `friday/safety/permissions.py` defines `check_permission(intent, permissions) -> PermissionResult` (`ALLOWED`, `CONFIRM_REQUIRED`, `DENIED`).
- Centralized policy evaluated in `registry.execute()` and `validate_plan()`.

### 7. Existing Plan Validation
- `friday/planning/plan_validator.py` defines `validate_plan(plan, permissions) -> (bool, str)`.
- Pre-validates every step in an `ActionPlan` before execution starts. Any `DENIED` step aborts the entire plan.

### 8. Existing Ollama Reasoning Path
- `OllamaReasoner` in `friday/reasoning/local_reasoner.py` connects to `http://localhost:11434/api/generate` (`llama3:latest`).
- Returns parsed & validated JSON dict (`intent`, `plan`, `response`).
- Reasoner output is converted to `Intent` or `ActionPlan` and passed through `validate_plan()`, `validate()`, and `registry.execute()`. LLM output cannot directly call tools or execute commands.

### 9. Existing TTS Response Path
- Returns human-readable response text string from `ConversationManager` to voice loop for Piper TTS synthesis.
- Currently uses raw tool `result.get("message")` without distinguishing whether execution vs verification succeeded.

### 10. Architectural Gaps Preventing Post-Action Verification
- **No Verification Subsystem**: No dedicated verification module exists to observe system state after tool execution.
- **No Result Typing**: Tool execution result is an untyped dictionary without explicit separation of `ExecutionStatus` vs `VerificationStatus`.
- **Blind Success Assumption**: `registry.execute()` assumes success if the tool call finishes without error (or returns dry-run text).
- **Multi-Step Continuation**: Multi-step plans continue to subsequent steps even if an earlier step's execution or verification failed silently.
- **Incomplete Audit Log**: Audit logger does not capture post-execution verification state or final verified status.
- **Unverified Voice Feedback**: TTS speaks tool messages directly, potentially telling the user "Chrome is open" when process launch failed or was only simulated in dry-run mode.

---

## Architectural Problem Report (Outside Phase 9 Scope)

| File | Problem | Security / Functional Impact | Recommended Future Phase |
|---|---|---|---|
| `friday/system_control/app_control.py` | Legacy unused module contains `os.startfile(spoken_name)` with un-whitelisted target lookup. | Medium potential risk if ever imported or wired into pipeline. Currently disconnected & inactive. | Phase 10 (Legacy Cleanup & Refactoring) |

---

## 2. Design & Architecture for Phase 9

### Trust Boundaries & Flow

```
UNTRUSTED                         TRUSTED
─────────────────────────────────────────────────────────────────────────────
User Speech / Audio
Raw STT Transcript
LLM Reasoning JSON
                                  Deterministic Router (Intent)
                                  Reasoning Validator (validated dict)
                                  Permission Policy (check_permission)
                                  Plan Pre-Validator (validate_plan)
                                  Safety Policy & Confirmation Gate
                                  tool registry.execute()
                                  ───────────────────────────────────────────
                                  NEW: Execution & Verification Layer
                                  - Tool Execution (ExecutionResult)
                                  - Deterministic Verifier (VerificationResult)
                                  - Final Result Aggregator (FinalStatus)
                                  ───────────────────────────────────────────
                                  Audit Logger (log_action with Verification)
                                  Verified Response Renderer -> Piper TTS
```

### Subsystem Design

#### 1. Structured Models (`friday/verification/models.py`)

```python
class ExecutionStatus(Enum):
    SUCCESS               = "SUCCESS"
    FAILED                = "FAILED"
    BLOCKED               = "BLOCKED"
    DENIED                = "DENIED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"

class VerificationStatus(Enum):
    VERIFIED_SUCCESS      = "VERIFIED_SUCCESS"
    FAILED                = "FAILED"
    NOT_APPLICABLE        = "NOT_APPLICABLE"
    DRY_RUN               = "DRY_RUN"
    SKIPPED               = "SKIPPED"

class FinalStatus(Enum):
    SUCCESS               = "SUCCESS"
    FAILED                = "FAILED"
    BLOCKED               = "BLOCKED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    DRY_RUN               = "DRY_RUN"

@dataclass
class ExecutionResult:
    action: Action
    target: str
    status: ExecutionStatus
    message: str
    blocked: bool = False
    raw_tool_result: dict = field(default_factory=dict)
    execution_latency_ms: float = 0.0

@dataclass
class VerificationResult:
    status: VerificationStatus
    message: str
    details: dict = field(default_factory=dict)
    verification_latency_ms: float = 0.0

@dataclass
class ActionOutcome:
    intent: Intent
    execution: ExecutionResult
    verification: VerificationResult
    final_status: FinalStatus
    user_message: str
```

#### 2. Verification Subsystem (`friday/verification/`)

- `friday/verification/verifier.py`: Core verification orchestrator.
- `friday/verification/action_verifiers.py`: Deterministic verifiers per action type:
  - `OPEN_APP(target)`: Inspect active Windows processes via `psutil` or process listing to confirm target executable/process is running.
  - `CLOSE_APP(target)`: Inspect active Windows processes via `psutil` to verify process is **no longer** running.
  - `OPEN_FOLDER(target)`: Verify path existence of designated safe folder (`Downloads`, `Documents`, `Desktop`).
  - `OPEN_WEBSITE(target)`: Verify browser process exists and navigation URL mapping was valid.
  - `SEARCH_WEB(query)`: Verify search URL construction & browser invocation succeeded.
  - `GET_TIME`: Return `VerificationStatus.NOT_APPLICABLE` (pure stdlib function).
  - `FIND_FILE`: Verify search result structure is valid.
  - `OPEN_FILE`: Verify target file exists in safe directory.
  - In `dry_run` mode: Returns `VerificationStatus.DRY_RUN` with clear message `"[DRY RUN] Verification simulated (dry run mode)"`.

> [!IMPORTANT]
> **Verification Safety Rule**: Verifiers are strictly observational (read-only process checks, filesystem existence checks). They NEVER launch processes, kill processes, execute shell commands, or modify files.

#### 3. Registry & Executor Integration (`friday/tools/registry.py`, `friday/planning/executor.py`)

- `registry.execute()` runs tool execution, then invokes the verifier to obtain `VerificationResult`.
- Combines into `ActionOutcome`.
- If execution is `BLOCKED` or `FAILED`, verification is `SKIPPED`.
- In `executor.py` (`execute_plan_step`): If `ActionOutcome.final_status` is `FAILED` or `BLOCKED`, the multi-step plan immediately transitions to `PlanState.FAILED` and halts execution, returning an informative message explaining which step failed.

#### 4. Extended Audit Logging (`friday/utils/audit_logger.py`)

Extend `log_action()` parameters:
```python
def log_action(
    *,
    action: str,
    target: str,
    permission: str,
    confirmation: str,
    execution: str,
    verification: str,    # NEW
    final_status: str,    # NEW
    result: str,
    latency_ms: float = 0.0,
) -> None:
```
Logs structured format:
`[ACTION] action=OPEN_APP target='chrome' permission=ALLOWED confirmation=N/A execution=SUCCESS verification=VERIFIED_SUCCESS final=SUCCESS latency_ms=12.4`

#### 5. User-Facing Response & TTS Integration (`friday/verification/formatter.py`)

Formats clean, human-readable user messages without exposing internal enums:
- `FinalStatus.SUCCESS` (real): `"Chrome is open and verified."` / `"Opened Chrome."`
- `FinalStatus.DRY_RUN`: `"[DRY RUN] Would open Chrome."`
- `FinalStatus.FAILED` (execution failed): `"I couldn't open Chrome."`
- `FinalStatus.FAILED` (verification failed): `"I tried to open Chrome, but I couldn't confirm that it opened."`
- `FinalStatus.BLOCKED`: `"Action OPEN_APP('chrome') is not permitted."`

---

## 3. Incremental Implementation Plan

### Increment 1: Structured Result Models & Unit Tests
- Create `friday/verification/models.py` with `ExecutionStatus`, `VerificationStatus`, `FinalStatus`, `ExecutionResult`, `VerificationResult`, `ActionOutcome`.
- Create `tests/test_execution_result.py` testing model creation, state serialization, and helper methods.
- Verification: `pytest tests/test_execution_result.py`.

### Increment 2: Deterministic Verifiers & Subsystem
- Create `friday/verification/action_verifiers.py` implementing process check (`psutil`), folder/file existence check, browser check, and dry-run verifier.
- Create `friday/verification/verifier.py` (registry for action verifiers).
- Create `tests/test_verification.py` testing process verification, folder verification, dry-run handling, and failure modes.
- Verification: `pytest tests/test_verification.py`.

### Increment 3: Tool Registry Integration & Verified Execution
- Update `friday/tools/registry.py` to execute tool, call verifier, construct `ActionOutcome`, and record extended audit log.
- Create `tests/test_verified_tools.py` testing tool execution + verification pairing for safe tools.
- Verification: `pytest tests/test_verified_tools.py`.

### Increment 4: ConversationManager & Single-Utterance Integration
- Update `friday/core/conversation.py` to process `ActionOutcome` from tool registry execution and store verification results in context.
- Update response formatting to speak verified status.
- Verification: `pytest tests/test_verified_tools.py tests/test_conversation_state.py`.

### Increment 5: Multi-Step Plan Verification & Abort Logic
- Update `friday/planning/executor.py` (`execute_plan_step`) to check `ActionOutcome.final_status`.
- If execution or verification fails on step N: stop plan, set `plan.state = PlanState.FAILED`, and return `"I couldn't [action target], so I stopped the plan."`.
- Create `tests/test_plan_verification.py` testing multi-step plan abortion on verification failure.
- Verification: `pytest tests/test_plan_verification.py`.

### Increment 6: Audit Logger Extension & User-Facing Response Formatting
- Update `friday/utils/audit_logger.py` to accept `verification` and `final_status` parameters.
- Create `friday/verification/formatter.py` to render clean TTS text strings based on `ActionOutcome`.
- Update `tests/test_real_execution_gate.py` to assert new audit log fields.
- Verification: `pytest tests/test_real_execution_gate.py`.

### Increment 7: Security Tests, Phase 9 Gate & Full Regression
- Create `tests/test_verification_security.py` verifying read-only nature of verifiers (no command execution, no shell=True, no os.system, no state mutation).
- Create `tests/test_phase9_gate.py` implementing comprehensive 20-point verification gate.
- Run full system regression suite across all 28+ test modules.
- Verification: `pytest tests/test_phase9_gate.py` and full regression suite.

---

## 4. Verification & Testing Strategy

### Automated Tests To Add
1. `tests/test_execution_result.py`: Models, statuses, immutability, data structures.
2. `tests/test_verification.py`: Action-specific verifiers (`psutil` process check, path check, dry-run mode, unknown action handling).
3. `tests/test_verified_tools.py`: Tool registry dispatch + verifier integration, execution/verification separation.
4. `tests/test_plan_verification.py`: Plan step execution + verification, plan abort on step failure.
5. `tests/test_verification_security.py`: Verifier isolation, read-only enforcement, zero shell execution.
6. `tests/test_phase9_gate.py`: 20-point Phase 9 gate test.

### Non-Negotiable Gate Requirements (Phase 9 Gate)
- Verification layer exists and is separate from tool execution.
- Verifiers are strictly observational (read-only).
- `dry_run: true` and `allow_real_execution: false` defaults remain untouched.
- `CLOSE_APP` still requires confirmation before execution + verification.
- Permission policy still enforced before execution.
- Multi-step plans stop immediately if step N execution or verification fails.
- Audit log includes `execution`, `verification`, and `final_status`.
- TTS receives clean human-readable text based on verified outcome.
- Legacy `friday/system_control` is not wired into the pipeline.

---

## 5. Proposed Files Created / Modified

### [NEW] `friday/verification/__init__.py`
### [NEW] `friday/verification/models.py`
### [NEW] `friday/verification/verifier.py`
### [NEW] `friday/verification/action_verifiers.py`
### [NEW] `friday/verification/formatter.py`
### [MODIFY] `friday/tools/registry.py`
### [MODIFY] `friday/planning/executor.py`
### [MODIFY] `friday/core/conversation.py`
### [MODIFY] `friday/utils/audit_logger.py`
### [NEW] `tests/test_execution_result.py`
### [NEW] `tests/test_verification.py`
### [NEW] `tests/test_verified_tools.py`
### [NEW] `tests/test_plan_verification.py`
### [NEW] `tests/test_verification_security.py`
### [NEW] `tests/test_phase9_gate.py`
