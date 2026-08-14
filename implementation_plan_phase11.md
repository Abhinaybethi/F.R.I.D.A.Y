# Phase 11 — Real-World End-to-End Integration & Release Candidate Validation
## Implementation Plan

---

## 1. Runtime Pipeline & Failure Boundary Mapping

```
Microphone Stream (AudioInput)
 ↓ (PCM audio frames)  <-- BOUNDARY 1: Hardware mic availability & volume level
Silero VAD (vad.py)
 ↓ (Audio chunks with speech)  <-- BOUNDARY 2: Speech activity segmentation
faster-whisper STT (speech_to_text.py)
 ↓ (Raw transcript string)  <-- BOUNDARY 3: STT transcription accuracy
ConversationManager.handle_transcript() (conversation.py)
 ↓ (System stop/cancel, Pending confirmation check)  <-- BOUNDARY 4: Session state transitions
Deterministic Router / Multi-step Planner (router.py, planner.py)
 ↓ (Intent or ActionPlan)
Ollama Reasoning Fallback (local_reasoner.py)
 ↓ (Validated Intent/Plan)  <-- BOUNDARY 5: Ollama availability & JSON validation
Upfront Plan Pre-Validation (plan_validator.py)
 ↓ (check_permission on all steps)  <-- BOUNDARY 6: Upfront whole-plan permission gate
Safety Policy & Confirmation Gate (validator.py, confirmation.py)
 ↓ (Confidence threshold check; Policy.CONFIRM for CLOSE_APP)  <-- BOUNDARY 7: User confirmation
Permission Check (permissions.py)
 ↓ (Per-action opt-in in config.yaml)  <-- BOUNDARY 8: Per-action permission gate
Tool Execution (registry.py + apps/browser/files/system)
 ↓ (ExecutionResult)  <-- BOUNDARY 9: Subprocess / OS file dispatch
Post-Action Verification (verifier.py + action_verifiers.py)
 ↓ (VerificationResult)  <-- BOUNDARY 10: Observational process/path checks
Outcome Aggregator & Response Formatter (formatter.py)
 ↓ (ActionOutcome + user_message)
Audit Logging (audit_logger.py)
 ↓ (Structured log line in friday_audit.log)  <-- BOUNDARY 11: Structured audit logging
Piper TTS Synthesis (text_to_speech.py)
 ↓ (Audio playback)  <-- BOUNDARY 12: Audio output device playback
User
```

---

## 2. Real Command Validation Matrix

| Category | Utterance | Target Intent | Confidence | Policy | Permission | Execution (Dry/Real) | Verification | Final Response |
|---|---|---|---|---|---|---|---|---|
| **Safe App** | `"open chrome"` | `OPEN_APP(chrome)` | `0.98` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open Chrome."` / `"Opening Chrome."` |
| **Safe Website** | `"open youtube"` | `OPEN_WEBSITE(youtube)` | `0.98` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open YouTube."` |
| **Safe Search** | `"search for python tutorials"` | `SEARCH_WEB(python tutorials)` | `0.95` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would search Google for 'python tutorials'."` |
| **Safe Time** | `"what time is it"` | `GET_TIME()` | `1.00` | `SAFE` | `ALLOWED` | `SUCCESS` | `NOT_APPLICABLE` | `"It's 3:30 PM."` |
| **Safe File** | `"find my resume"` | `FIND_FILE(resume)` | `0.95` | `SAFE` | `ALLOWED` | `SUCCESS` | `NOT_APPLICABLE` | `"Found 1 file matching 'resume'..."` |
| **Safe Folder** | `"open downloads"` | `OPEN_FOLDER(downloads)` | `0.98` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open Downloads folder."` |
| **Ambiguous** | `"open grove"` | `UNKNOWN` -> Reasoner | `<0.45` | `REJECT` / Clarify | `N/A` | `SKIPPED` | `SKIPPED` | `"I didn't understand that."` / `"Did you mean Chrome?"` |
| **Ambiguous** | `"open groom"` | `UNKNOWN` -> Reasoner | `<0.45` | `REJECT` / Clarify | `N/A` | `SKIPPED` | `SKIPPED` | `"I didn't understand that."` |
| **Ambiguous** | `"openvscode"` | `OPEN_APP(vscode)` | `0.90` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open VS Code."` |
| **Confirmation** | `"close chrome"` | `CLOSE_APP(chrome)` | `0.98` | `CONFIRM` | `CONFIRM_REQUIRED` | `HELD` | `SKIPPED` | `"Are you sure you want to close Chrome?"` |
| **System** | `"help"` | `SYSTEM_HELP()` | `1.00` | `SAFE` | `N/A` | `SUCCESS` | `NOT_APPLICABLE` | `"I can open applications and websites..."` |
| **System** | `"repeat"` | `SYSTEM_REPEAT()` | `1.00` | `SAFE` | `N/A` | `SUCCESS` | `NOT_APPLICABLE` | *(Repeats last response)* |
| **System** | `"cancel"` | `CANCEL` | `1.00` | `SAFE` | `N/A` | `SUCCESS` | `NOT_APPLICABLE` | `"Cancelled."` |
| **System** | `"stop"` | `STOP` | `1.00` | `SAFE` | `N/A` | `SUCCESS` | `NOT_APPLICABLE` | `"Goodbye."` |
| **Nonsense** | `"blood growing"` | `UNKNOWN` -> Reasoner | `<0.45` | `REJECT` | `N/A` | `SKIPPED` | `SKIPPED` | `"I didn't understand that."` |
| **Nonsense** | `"million dollars"` | `UNKNOWN` -> Reasoner | `<0.45` | `REJECT` | `N/A` | `SKIPPED` | `SKIPPED` | `"I didn't understand that."` |
| **Natural Language** | `"could you open chrome for me"` | `OPEN_APP(chrome)` | `0.95` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open Chrome."` |
| **Natural Language** | `"find python tutorials on the web"` | `SEARCH_WEB(python tutorials)` | `0.92` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would search Google for 'python tutorials'."` |
| **Natural Language** | `"what time is it right now"` | `GET_TIME()` | `0.98` | `SAFE` | `ALLOWED` | `SUCCESS` | `NOT_APPLICABLE` | `"It's 3:30 PM."` |
| **Multi-Step** | `"open chrome and open youtube"` | `Plan[OPEN_APP(chrome), OPEN_WEBSITE(youtube)]` | `0.95` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open Chrome. [DRY RUN] Would open YouTube."` |
| **Multi-Step** | `"open chrome then search for python tutorials"` | `Plan[OPEN_APP(chrome), SEARCH_WEB(python tutorials)]` | `0.95` | `SAFE` | `ALLOWED` | `SUCCESS` | `DRY_RUN` / `VERIFIED` | `"[DRY RUN] Would open Chrome. [DRY RUN] Would search Google..."` |

---

## 3. Controlled Release Test Mode (`RELEASE_TEST_MODE`)

Do NOT flip global config to `dry_run: false, allow_real_execution: true`.
Create a dedicated `RELEASE_TEST_MODE` context in `friday/tools/registry.py` that permits real execution **only** for an explicit whitelist of harmless targets:

```python
_RELEASE_TEST_WHITELIST = {
    (Action.OPEN_APP, "chrome"),
    (Action.OPEN_WEBSITE, "youtube"),
    (Action.OPEN_FOLDER, "downloads"),
}
```

- Any action outside this whitelist (including `CLOSE_APP`, arbitrary file execution, or arbitrary URLs) remains strictly in dry-run mode or blocked.
- Config default `dry_run: true` and `allow_real_execution: false` remains untouched.

---

## 4. End-to-End Performance & Resource Benchmarking

Create `scripts/benchmark_e2e_performance.py`:
- **Latency Metrics**: STT latency, Intent routing latency, Ollama fallback latency, Plan parsing latency, Tool execution latency, Post-action verification latency, Piper TTS synthesis latency, End-to-end command latency.
- **Resource Metrics**: Process RAM (MB), CPU usage (%), Model VRAM/RAM footprints, startup time (s).

---

## 5. Failure Mode Recovery Matrix

Validate fail-closed recovery for:
- Microphone unavailable -> Graceful error message, fallback to CLI transcript input.
- VAD fails -> Fallback to fixed silence threshold segmentation.
- Whisper unavailable -> Graceful error reporting.
- Ollama offline -> Route unknown intents to `"I didn't understand that."` without crash.
- Ollama timeout (60s) -> Graceful exception catch and user notification.
- Malformed Ollama JSON -> Fails closed to `"I didn't understand that."`.
- TTS engine unavailable -> Fallback from Kokoro to Piper or console text output.
- Tool execution exception -> ExecutionResult `FAILED`, verification `SKIPPED`, user informed.
- Verification failure -> FinalStatus `FAILED`, TTS announces `"I tried to open X, but couldn't confirm it succeeded."`.
- Confirmation rejected -> Plan/Intent cancelled, user informed `"Cancelled."`.
- Ctrl+C signal during listening/TTS -> Clean shutdown via context managers (`__exit__`), releasing mic & sound device.
- Multi-step plan failure on Step 2 -> Plan state `FAILED`, Step 1 outcome recorded, execution halts.

---

## 6. Release Candidate Checklist

```markdown
[ ] All 220 automated unit/integration tests pass
[ ] Config validation & fail-closed defaults verified (dry_run: true, allow_real_execution: false)
[ ] Real hardware diagnostics pass (mic, VAD, STT, TTS, audio device)
[ ] Deterministic router & context resolver pass command matrix
[ ] Ollama local reasoning fallback passes robustness & security checks
[ ] Confirmation gate enforced for CLOSE_APP
[ ] Per-action permission gates enforced
[ ] Upfront plan pre-validation enforced
[ ] Post-action verification enforced (process/folder checks)
[ ] Audit logging emits structured [ACTION] entries with verification & latency
[ ] Controlled RELEASE_TEST_MODE validates real app launch safety
[ ] End-to-end latency benchmarked (< 1.5s warm for router, < 3.5s warm for reasoner)
[ ] Failure recovery verified (Ollama offline, mic missing, bad JSON, step failure)
[ ] Zero shell=True, zero os.system, zero eval/exec in active codebase
[ ] Legacy code quarantined in friday/legacy_deprecated/
```

---

## 7. Incremental Implementation Plan

### Increment 1: End-to-End Real Command Matrix Test Suite
- Create `tests/test_command_matrix.py` testing all 21 utterances in the command matrix through `ConversationManager`.
- Verification: `pytest tests/test_command_matrix.py`.

### Increment 2: Controlled Release Test Mode (`RELEASE_TEST_MODE`)
- Add `release_test_mode: bool = False` support in `friday/tools/registry.py` with `_RELEASE_TEST_WHITELIST`.
- Create `tests/test_release_test_mode.py`.
- Verification: `pytest tests/test_release_test_mode.py`.

### Increment 3: Real Hardware Integration Harness
- Create `tests/test_real_hardware_integration.py` / `scripts/validate_hardware_e2e.py` testing live audio stream initialization, VAD, STT transcription, and TTS synthesis.
- Verification: `pytest tests/test_real_hardware_integration.py`.

### Increment 4: End-to-End Performance & Resource Benchmarking
- Create `scripts/benchmark_e2e_performance.py` measuring latency across STT, router, reasoner, verifier, and TTS.
- Verification: Run benchmark script and log performance summary.

### Increment 5: Failure Mode Recovery Suite
- Create `tests/test_failure_recovery.py` testing Ollama offline, timeout, bad JSON, tool exceptions, verification failure, and Ctrl+C cleanup.
- Verification: `pytest tests/test_failure_recovery.py`.

### Increment 6: Security & Release Candidate Audit
- Create `tests/test_phase11_security.py` auditing trust boundaries, zero shell execution, and release checklist items.
- Verification: `pytest tests/test_phase11_security.py`.

### Increment 7: Phase 11 Gate & Full Regression Suite
- Create `tests/test_phase11_gate.py` implementing 20-point Phase 11 gate test.
- Run complete system regression suite across all 40+ test modules.
- Verification: `pytest tests/test_phase11_gate.py` and full regression suite.

---

## 8. Proposed Files Created / Modified

### [NEW] `friday/tools/release_mode.py`
### [NEW] `scripts/benchmark_e2e_performance.py`
### [NEW] `scripts/validate_hardware_e2e.py`
### [MODIFY] `friday/tools/registry.py`
### [NEW] `tests/test_command_matrix.py`
### [NEW] `tests/test_release_test_mode.py`
### [NEW] `tests/test_real_hardware_integration.py`
### [NEW] `tests/test_failure_recovery.py`
### [NEW] `tests/test_phase11_security.py`
### [NEW] `tests/test_phase11_gate.py`
