# Phase 10 — Production Hardening, Legacy Cleanup & Observability
## Implementation Plan

---

## 1. Runtime Dependency Map & Trust Boundaries

### Execution Pipeline

```
Microphone Stream (AudioInput)
    ↓ Raw PCM audio
Silero VAD (vad.py)
    ↓ Audio chunks with speech
faster-whisper STT (speech_to_text.py)
    ↓ Raw text transcript string  <-- TRUST BOUNDARY 1: UNTRUSTED USER SPEECH
ConversationManager.handle_transcript() (conversation.py)
    ↓ System command check ("stop", "cancel")
    ↓ WAITING_FOR_CONFIRMATION state check ("yes", "no", "cancel")
    ↓ Multi-step detection (" and ", " then ") -> parse_plan() (planner.py)
    ↓ OR Single utterance context resolution -> resolve_context()
    ↓ Deterministic Router -> route() (router.py)
    ↓ Intent(action, target, confidence)
    ↓ (Fallback if UNKNOWN) -> OllamaReasoner.request() (local_reasoner.py)
    ↓   <-- TRUST BOUNDARY 2: UNTRUSTED LLM JSON
    ↓   JSON Parser (parser.py) -> Reasoning Validator (validator.py)
    ↓   Validates action in Action enum, bounds steps <= 5, blocks injection keys
    ↓ Intent or ActionPlan
Upfront Plan Pre-Validation -> validate_plan() (plan_validator.py)
    ↓ Checks all plan steps against check_permission() -> rejects plan if ANY step is DENIED
Safety Policy Validation -> validate(intent) (validator.py)
    ↓ Confidence thresholds (SAFE >= 0.85, CONFIRM >= 0.45, REJECT < 0.45)
    ↓ CLOSE_APP always requires Policy.CONFIRM -> WAITING_FOR_CONFIRMATION
Permission Policy -> check_permission(intent, perms) (permissions.py)
    ↓ Per-action opt-in in config.yaml
Triple Lock Gate -> registry.execute() (registry.py)
    ↓ Gate 1: dry_run == False
    ↓ Gate 2: allow_real_execution == True
    ↓ Gate 3: permissions[action] == True and permission != DENIED
Tool Execution -> dispatch to apps / browser / files / system
    ↓ Target Whitelist Check (_APP_EXECUTABLES, _WEBSITE_URLS, _SAFE_DIRS)
    ↓ Subprocess list form / os.startfile on path-checked safe path
    ↓ ExecutionResult(status, message, raw_tool_result)
Post-Action Verification -> verify_execution() (verifier.py)
    ↓ Deterministic Observational Checks (psutil process inspect, Path.exists())
    ↓ VerificationResult(status, message)
Outcome Aggregation & Response Formatter -> format_outcome() (formatter.py)
    ↓ ActionOutcome(final_status, user_message)
Audit Logging -> log_action() (audit_logger.py)
    ↓ Appends [ACTION] line to logs/friday_audit.log
User Response Feedback
    ↓ Piper TTS (text_to_speech.py) -> Audio playback
```

---

## 2. Legacy Code Decisions

| Module / Directory | File(s) | Status | Classification | Action in Phase 10 |
|---|---|---|---|---|
| `friday/system_control/` | `app_control.py`, `file_control.py`, `system_info.py` | Completely Dead (Unused prototype code containing un-whitelisted `os.startfile`) | **REMOVE / ISOLATE** | Move to `friday/legacy_deprecated/` or remove with test verification that active runtime is 100% unaffected. |
| `friday/skills/` | `app_skill.py`, `file_skill.py`, `system_skill.py`, `knowledge_skill.py` | Completely Dead (Legacy skill wrappers around `system_control`) | **REMOVE / ISOLATE** | Move to `friday/legacy_deprecated/` or remove. |
| `friday/core/command_router.py` | `command_router.py` | Completely Dead (Early regex router using `skills`) | **REMOVE / ISOLATE** | Move to `friday/legacy_deprecated/` or remove. |
| `friday/brain/` | `llm_client.py`, `web_search.py` | Completely Dead (Early prototype brain replaced by `local_reasoner.py` and `browser.py`) | **REMOVE / ISOLATE** | Move to `friday/legacy_deprecated/` or remove. |

---

## 3. Observability & Failure-Mode Hardening

### Config Validation (`friday/utils/config_validator.py`)
- Strict type checking on startup:
  - `dry_run`: Coerced strictly to `bool`. Missing/invalid values fail closed to `True`.
  - `allow_real_execution`: Coerced strictly to `bool`. Missing/invalid values fail closed to `False`.
  - `permissions`: Dict validation. Unknown permission keys are rejected; non-boolean values fail closed to `False`.
  - `reasoning.endpoint`: URL string format check.
  - Startup failure: Clean, structured configuration error message instead of raw tracebacks.

### Audit Logger Hardening (`friday/utils/audit_logger.py`)
- Add optional traceability fields: `plan_id: str = ""`, `step_index: int = 0`, `error: str = ""`.
- Format:
  `[ACTION] action=OPEN_APP target='chrome' permission=ALLOWED confirmation=N/A execution=FAILED verification=SKIPPED final=FAILED result=FAILURE plan_id='p-123' step=1/2 error='Not in registry' latency_ms=0.5`

### Health & Runtime Diagnostics (`friday/utils/health_diagnostics.py`)
- Standardized health check function `get_system_health() -> dict`:
  - Microphone availability
  - VAD model availability
  - STT model availability
  - TTS model availability
  - Ollama reachable & model loaded check
  - Config validity check

---

## 4. Incremental Implementation Plan

### Increment 1: Legacy Code Isolation & Quarantining
- Quarantined dead legacy modules (`friday/system_control/`, `friday/skills/`, `friday/brain/`, `command_router.py`) into `friday/legacy_deprecated/` or clean removal.
- Create `tests/test_legacy_isolation.py` verifying active runtime imports zero legacy code.
- Verification: `pytest tests/test_legacy_isolation.py`.

### Increment 2: Configuration Validation Subsystem
- Create `friday/utils/config_validator.py` implementing `validate_config(config_dict) -> (bool, dict, list[str])`.
- Enforce strict fail-closed defaults for safety gates.
- Create `tests/test_config_validation.py`.
- Verification: `pytest tests/test_config_validation.py`.

### Increment 3: Fail-Closed Diagnostics & Startup Hardening
- Integrate `config_validator` into `Friday.__init__()` in `friday/core/assistant.py`.
- Provide clean startup error reporting for missing/invalid config, missing models, or system errors.
- Create `tests/test_failure_modes.py`.
- Verification: `pytest tests/test_failure_modes.py`.

### Increment 4: Audit Logger & Observability Hardening
- Update `friday/utils/audit_logger.py` to accept `plan_id`, `step_index`, and `error`.
- Update `friday/tools/registry.py` and `friday/planning/executor.py` to pass plan context and error messages to audit logger.
- Update `tests/test_real_execution_gate.py` and `tests/test_phase9_gate.py` for audit schema updates.
- Verification: `pytest tests/test_real_execution_gate.py`.

### Increment 5: System Health Diagnostics
- Create `friday/utils/health_diagnostics.py` implementing `check_system_health(config) -> dict`.
- Update `main.py` `--voice-test` to use `check_system_health()`.
- Create `tests/test_health_diagnostics.py`.
- Verification: `pytest tests/test_health_diagnostics.py`.

### Increment 6: Integration & Security Hardening Tests
- Create `tests/test_phase10_security.py` verifying all safety boundaries, trust boundary isolation, and fail-closed behaviors.
- Verification: `pytest tests/test_phase10_security.py`.

### Increment 7: Phase 10 Gate & Full System Regression
- Create `tests/test_phase10_gate.py` implementing 20-point Phase 10 gate test.
- Run complete system regression suite across all 35+ test files.
- Verification: `pytest tests/test_phase10_gate.py` and full regression suite.

---

## 5. Proposed Files Created / Modified

### [NEW] `friday/utils/config_validator.py`
### [NEW] `friday/utils/health_diagnostics.py`
### [NEW] `friday/legacy_deprecated/__init__.py`
### [MODIFY] `friday/core/assistant.py`
### [MODIFY] `friday/tools/registry.py`
### [MODIFY] `friday/planning/executor.py`
### [MODIFY] `friday/utils/audit_logger.py`
### [MODIFY] `main.py`
### [NEW] `tests/test_legacy_isolation.py`
### [NEW] `tests/test_config_validation.py`
### [NEW] `tests/test_failure_modes.py`
### [NEW] `tests/test_health_diagnostics.py`
### [NEW] `tests/test_phase10_security.py`
### [NEW] `tests/test_phase10_gate.py`
