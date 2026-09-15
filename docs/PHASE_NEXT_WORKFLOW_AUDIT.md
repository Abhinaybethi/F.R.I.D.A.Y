# F.R.I.D.A.Y. v2 — Next Phase Workflow Audit & Gap Analysis
**Document Status**: COMPLETED AUDIT (Pre-Implementation)  
**Target Repository**: `F.R.I.D.A.Y v2` (Base Release: `v1.1.0`)  
**Safety Invariants**: `dry_run=True`, `allow_real_execution=False` defaults preserved; no cloud LLMs; `v1.1.0` tag immutable.

---

## 1. Executive Summary & Objective

The objective of this engineering audit is to rigorously analyze the F.R.I.D.A.Y. v2 voice assistant across the complete interaction lifecycle:
$$\text{VOICE} \to \text{STT} \to \text{INTENT} \to \text{TARGET} \to \text{CONTEXT} \to \text{PLAN} \to \text{CONFIRMATION} \to \text{EXECUTION} \to \text{OS/NET/DB STATE} \to \text{INDEPENDENT VERIFICATION} \to \text{FEEDBACK} \to \text{NEXT TURN}$$

### Core Invariant
> **F.R.I.D.A.Y. must never claim an action succeeded unless the external host environment (Windows process table, filesystem, SQLite database, network response, or audio stream) provides verifiable, observational proof that the side effect actually occurred.**

---

## 2. Comprehensive System Architecture (Section A)

```
+----------------------------------------------------------------------------------------------------+
|                                    F.R.I.D.A.Y. v2 RUNTIME ARCHITECTURE                            |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  [ Physical Audio Input ] (16 kHz Mono Microphones)                                                |
|            │                                                                                       |
|            ▼                                                                                       |
|  [ Silero VAD (ONNX) ] ─── (Speech Triggered) ───► [ faster-whisper (small.en, int8 CPU) ]          |
|                                                               │                                    |
|                                                               ▼ Transcript                         |
|                                            [ Text Normalization & Routing ]                        |
|                                                               │                                    |
|                         ┌─────────────────────────────────────┴─────────────────────────┐          |
|                         ▼ Deterministic Match                                           ▼ Complex  |
|               [ Rule-Based / Fuzzy Router ]                                   [ Ollama Reasoner ]  |
|                         │                                                     (llama3 local only)  |
|                         └───────────────────────┬───────────────────────┘                          |
|                                                 ▼                                                  |
|                                      [ Intent / Action Plan ]                                      |
|                                                 │                                                  |
|                                                 ▼                                                  |
|                                      [ Short-Term Context ]                                        |
|                             (Anaphora, Ordinals, Search Cache, Entities)                           |
|                                                 │                                                  |
|                                                 ▼                                                  |
|                                      [ Safety Policy Validator ]                                   |
|                                                 │                                                  |
|                         ┌───────────────────────┴───────────────────────┐                          |
|                         ▼ Policy.SAFE                                   ▼ Policy.CONFIRM           |
|                [ Execution Dispatch ]                      [ WAITING_FOR_CONFIRMATION ]            |
|                         │                                               │                          |
|                         │                                       ┌───────┴───────┐                  |
|                         │                                       ▼ YES           ▼ NO               |
|                         │                              [ Execute Action ]   [ Zero Side Effect ]   |
|                         ▼                                       │                                  |
|            [ Tool Registry Dispatch ] ◄─────────────────────────┘                                  |
|            (Apps, Browser, Files, Memory, System)                                                  |
|                         │                                                                          |
|                         ▼ REAL OS / DB / NET SIDE EFFECT                                           |
|             ┌───────────────────────────────────────────────┐                                      |
|             │ • Windows Process Launch/Terminate (psutil)   │                                      |
|             │ • Browser Navigation & Search API (ddgs/bs4)  │                                      |
|             │ • Local SQLite Persistence (ACID queries)     │                                      |
|             │ • Filesystem Traversals (Pathlib / scandir)   │                                      |
|             │ • Sounddevice / Piper TTS Playback            │                                      |
|             └───────────────────────┬───────────────────────┘                                      |
|                                     │                                                              |
|                                     ▼                                                              |
|                     [ Independent Action Verifier ]                                                |
|                     (Fresh read-only observational queries)                                        |
|                                     │                                                              |
|                         ┌───────────┴───────────┐                                                  |
|                         ▼ VERIFIED_SUCCESS      ▼ FAILED / SKIPPED                                 |
|                [ Accurate User Feedback ]   [ Failure Recovery Notice ]                            |
|                         │                               │                                          |
|                         └───────────┬───────────────────┘                                          |
|                                     ▼                                                              |
|                           [ Piper / Kokoro TTS ] (with Hardware Barge-In Abort)                     |
|                                     │                                                              |
|                                     ▼                                                              |
|                        [ Context Roll & Next Turn ]                                                |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 3. Action Pipeline Specification (Section B)

Every action request flows strictly through the standardized Action Contract:

```
ActionRequest (Intent, Target, Arguments)
       ↓
Gate 1: dry_run Check (Config / Override)
       ↓
Gate 2: allow_real_execution Check (Config / Override)
       ↓
Gate 3: Permissions & Safety Policy (SAFE, CONFIRM, REJECT)
       ↓
Execution Dispatch (_dispatch to dedicated tool module)
       ↓
External OS / Environment Mutation
       ↓
ExecutionResult(status, raw_tool_result, latency_ms)
       ↓
Independent Verifier Observation
       ↓
VerificationResult(status, details, latency_ms)
       ↓
ActionOutcome(final_status, user_message, spoken_message)
```

### Action Contracts by Tool Category

| Action | Handler Module | Physical Side Effect | Verification Mechanism |
|---|---|---|---|
| `OPEN_APP` | `friday/tools/apps.py` | Launches process (`subprocess.Popen`) | Inspects Windows process table via `psutil.process_iter` for candidate process name |
| `CLOSE_APP` | `friday/tools/apps.py` | Terminates process (`proc.terminate/kill`) | Confirms 0 running instances in Windows process table |
| `OPEN_WEBSITE` | `friday/tools/browser.py` | Spawns browser process (`webbrowser.open`) | Validates URL scheme/SSRF and detects active browser process (`chrome.exe`, `msedge.exe`, etc.) |
| `SEARCH_WEB` | `friday/tools/browser.py` | Performs DuckDuckGo API/HTML search | Validates non-empty query string and verifies `len(results) > 0` in payload |
| `READ_WEBSITE` | `friday/tools/browser.py` | Fetches URL via `requests.get` + BeautifulSoup | Validates HTTP 200 and non-empty extracted text ($< 2000$ chars) |
| `OPEN_FOLDER` | `friday/tools/files.py` | Launches `explorer.exe <safe_path>` | Checks directory existence on disk and detects active `explorer.exe` process |
| `FIND_FILE` | `friday/tools/files.py` | Read-only directory traversal (`os.scandir`) | Verifies physical candidate file existence on disk, safe root containment, and read permissions |
| `OPEN_FILE` | `friday/tools/files.py` | Launches default handler via `os.startfile` | Validates file exists on disk and is within `_SAFE_DIRS` |
| `REMEMBER` | `friday/tools/memory.py` | SQLite `INSERT`/`UPDATE` into `memories` table | Fresh independent SQLite `SELECT` query confirming row was persisted |
| `RECALL` | `friday/tools/memory.py` | SQLite `SELECT` from `memories` table | Fresh independent SQLite read verifying exact key/content match |
| `FORGET` | `friday/tools/memory.py` | SQLite `DELETE` from `memories` table | Fresh independent SQLite read verifying exactly 0 matching rows remain |
| `SET_VOLUME` / `MUTE` | `friday/tools/system.py` | Adjusts system audio endpoint | Confirms execution status and verifies volume parameter |
| `SYSTEM_STOP` | `friday/tools/system.py` | Halts active TTS & voice stream | Verifies abort event signaled and sounddevice stream stopped |

---

## 4. Verification Pipeline Specification (Section C)

The verification subsystem ([`friday/verification/verifier.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/verification/verifier.py)) is decoupled from tool execution logic.

### Rules of Independent Verification
1. **Verifiers are Read-Only**: Verifiers NEVER spawn processes, kill processes, write to databases, or mutate filesystem structures.
2. **Never Trust Execution Status Alone**: If an executor reports `success: True`, the verifier independently checks external reality. If reality does not match, the verifier overrides the outcome to `FAILED` or `NOT_APPLICABLE`.
3. **Skipped on Prior Failure**: If tool execution fails (`status != ExecutionStatus.SUCCESS`), verification is skipped (`VerificationStatus.SKIPPED`) to avoid false-positive error attribution.
4. **Dry-Run Transparency**: When `is_dry_run=True`, verifiers return `VerificationStatus.DRY_RUN`, preventing fake claims of OS modification.

---

## 5. Lifecycles: Context, Confirmation, Failure Recovery & Reset (Sections D, E, F, G)

### D. Context Lifecycle
```
[User Utterance] 
  → Context Normalizer 
  → ShortTermContext Snapshot
      ├── last_search_query: str
      ├── last_search_results: list[dict] (stable IDs: result_1, result_2, result_3)
      ├── last_tool_result: dict
      ├── last_action: Action
      ├── last_target: str
      ├── history: list[5-turn rolling]
      └── goal_entities: dict
  → Anaphora / Ordinal Resolver ("it", "the first result", "the second one", "another one")
  → Routed Intent / Plan
  → Post-Execution Context Update
```

### E. Confirmation Lifecycle
```
[Destructive Action: FORGET, CLOSE_APP, etc.]
  → Safety Policy = Policy.CONFIRM
  → State = WAITING_FOR_CONFIRMATION
  → Store context.pending_intent & start 30s timer
  → Prompt User: "Are you sure you want to..."
  ├── User: "NO" / "cancel" → Pending intent cleared → 0 Side Effects → State = LISTENING
  ├── User: "YES" → Execute pending intent → Real Side Effect → Independent Verification → State = LISTENING
  ├── User: "No, <new command>" → Clear pending → Process new command immediately
  └── Timeout (> 30s) → Auto-cancel pending intent → State = LISTENING
```

### F. Failure Recovery Lifecycle
```
[Tool Execution Failure / Verifier Failure / Environment Error]
  → ExecutionResult(status=FAILED)
  → Verifier returns SKIPPED or FAILED
  → Formatter generates clean conversational error notice (no stack traces to user)
  → Goal state marked FAILED / CANCELLED
  → Ephemeral pending state cleared
  → State Machine cleanly transitions: EXECUTING → RESPONDING → LISTENING
  → Ready for next user turn without restart
```

### G. Session Reset Lifecycle
```
[User says "Stop" / "Exit" / Session Termination]
  → ConversationManager.stop_session()
  → context = ConversationContext() (wipes pending, goals, search results, history)
  → state_machine.transition_to(STOPPING) → transition_to(IDLE)
  → Active TTS stream halted via abort_event.set()
  → Guarantees STATE_LEAK_RATE = 0% across sessions
```

---

## 6. State Machine Audit & Transition Table

```
+--------------------------------------------------------------------------------------------------------------------------+
| State                      | Allowed Next States                          | Recovery Action upon Error / Interrupt       |
+----------------------------+----------------------------------------------+----------------------------------------------+
| IDLE                       | LISTENING, PAUSED, STOPPING                  | Clean reset to IDLE                          |
| LISTENING                  | PROCESSING, IDLE, PAUSED, STOPPING           | Drain audio buffer, retry listen             |
| PROCESSING                 | EXECUTING, WAITING_FOR_CONFIRMATION,         | Clean fallback to RESPONDING                 |
|                            | RESPONDING, STOPPING                         |                                              |
| WAITING_FOR_CONFIRMATION   | EXECUTING, RESPONDING, LISTENING,            | 30s timeout reset to LISTENING               |
|                            | WAITING_FOR_CONFIRMATION, STOPPING           |                                              |
| EXECUTING                  | RESPONDING, WAITING_FOR_CONFIRMATION,        | Trap exceptions, return error notice         |
|                            | STOPPING                                     |                                              |
| RESPONDING                 | LISTENING, IDLE, PAUSED, STOPPING            | Clear speaking state, enter LISTENING        |
| PAUSED                     | LISTENING, IDLE, STOPPING                    | Resume listening on explicit unpause         |
| STOPPING                   | IDLE                                         | Reset all context and state                  |
+--------------------------------------------------------------------------------------------------------------------------+
```

---

## 7. Granular Test Taxonomy & Separation (Sections H, I, J)

Every test in the repository is separated into its exact evidence category:

```
+---------------------------------------------------------------------------------------------+
| Category               | Description & Test Files                                           |
+---------------------------------------------------------------------------------------------+
| AUTOMATED              | • tests/test_command_matrix.py, tests/test_intent_router.py         |
|                        | • tests/test_permission_policy.py, tests/test_config_validation.py  |
|                        | • tests/test_phase10_gate.py through tests/test_phase24_gate.py     |
+------------------------+--------------------------------------------------------------------+
| REAL WINDOWS OS        | • tests/test_real_apps.py (real process launch via psutil)        |
|                        | • tests/test_real_files.py (real NTFS filesystem operations)        |
|                        | • tests/test_phase29_5_real_world.py (Windows OS commands)         |
+------------------------+--------------------------------------------------------------------+
| REAL BROWSER           | • tests/test_real_browser.py (live browser launch & URL schemes)   |
+------------------------+--------------------------------------------------------------------+
| REAL NETWORK           | • tests/test_real_browser.py (live DuckDuckGo & HTTP GET requests) |
|                        | • tests/test_phase30_workflows.py (real web searches & reading)    |
+------------------------+--------------------------------------------------------------------+
| REAL AUDIO / HARDWARE  | • tests/test_tts.py (sounddevice audio stream playback & abort)    |
|                        | • tests/test_barge_in_hardware.py (live audio buffer interruption) |
|                        | • tests/test_vad_capture.py (Silero ONNX VAD stream capture)       |
+------------------------+--------------------------------------------------------------------+
| REAL DATABASE          | • tests/test_phase20_memory.py (ACID SQLite operations on disk)    |
|                        | • tests/test_phase30_workflows.py (multi-turn SQLite verification) |
+------------------------+--------------------------------------------------------------------+
| SIMULATED / DRY-RUN    | • tests/test_phase29_real_action_certification.py (dry_run=True)   |
|                        | • tests/test_verification.py (simulated dry-run outcome branches)  |
+------------------------+--------------------------------------------------------------------+
| MOCKED / UNIT          | • tests/test_plan_execution.py (mocked executor returns)           |
|                        | • tests/test_local_stt.py (synthetic audio buffers)                |
+------------------------+--------------------------------------------------------------------+
| INSTRUMENTED           | • scripts/real_world_action_stress.py (24-field live telemetry)    |
|                        | • tests/test_phase30_workflows.py (context & side-effect probes)   |
+------------------------+--------------------------------------------------------------------+
```

### Function Return vs. Real External State Change Analysis

| Action Category | Tests that only prove "function returned True" | Tests that prove "External OS State Actually Changed" |
|---|---|---|
| **Applications** | `test_tools.py` (dry-run dict check) | `test_real_apps.py`, `test_phase30_workflows.py` (`psutil` PID table check) |
| **Web Navigation** | `test_phase29_real_action_certification.py` | `test_real_browser.py` (active browser process + HTTP 200 validation) |
| **Web Search** | `test_tools.py` (static mock results) | `test_phase30_workflows.py` (real DuckDuckGo payload + stable IDs) |
| **Memory** | `test_conversation_state.py` (in-memory mock) | `test_phase30_workflows.py` (fresh disk SQLite `SELECT` verification) |
| **File Operations**| `test_phase20_files.py` (mocked path) | `test_verification.py` (`Path.exists()`, safe-root check, `os.access`) |
| **Audio Interruption**| `test_barge_in.py` (event flag test) | `test_tts.py`, `test_barge_in_hardware.py` (sounddevice stream halt) |

---

## 8. Gap Analysis & Highest-Risk Workflow Boundaries (Sections J, K)

```
+-----------------------------------------------------------------------------------------------+
| Risk Boundary                     | Demonstrated Vulnerability       | Hardening Mitigation   |
+-----------------------------------+----------------------------------+------------------------+
| 1. Search Result Rate-Limiting    | Rapid consecutive DDG queries    | 60s TTL caching +      |
|    in Multi-Turn Workflows        | trigger HTTP 429 rate limit      | HTML scraping fallback |
+-----------------------------------+----------------------------------+------------------------+
| 2. Ordinal Context Resolution     | User saying "the second one" vs  | Multi-turn entity      |
|    under Correction               | "no, the third one"              | index mapping in       |
|                                   |                                  | ShortTermContext       |
+-----------------------------------+----------------------------------+------------------------+
| 3. Duplicate Process Spawning     | Repeated "open Notepad" spawns   | Process table inspect  |
|                                   | duplicate OS instances           | before Popen launch    |
+-----------------------------------+----------------------------------+------------------------+
| 4. Memory Key Stale Persistence   | Updating preference creates      | SQLite query uses      |
|                                   | duplicate keys in SQLite table   | deduplication &        |
|                                   |                                  | updated_at ordering    |
+-----------------------------------+----------------------------------+------------------------+
| 5. Confirmation State Leakage     | Cancelled confirmation retains   | Strict context purge   |
|                                   | pending intent into next command | on NO/Cancel/Timeout   |
+-----------------------------------+----------------------------------+------------------------+
```

---

## 9. Recommended Implementation & Verification Order (Section L)

1. **Step 1: Test Plan Formulation** (`docs/PHASE_NEXT_REAL_WORLD_TEST_PLAN.md`) — Specify the exact matrix of deterministic trials, workflow progressions, and observation criteria.
2. **Step 2: Real-World Test Harness Execution** (`scripts/phase_next_real_world_campaign.py` & `tests/test_phase_next_real_world.py`) — Execute 180+ real OS trials across Workflows A through J.
3. **Step 3: Forensic Failure Classification & Root Cause Fixes** — Patch only demonstrated production defects.
4. **Step 4: Regression Test Verification** — Run full automated test suite, security static scans, and re-run real-world campaign.
5. **Step 5: Scorecard & Final Certification Report Generation** (`docs/PHASE_NEXT_ACTION_SCORECARD.md` & `docs/PHASE_NEXT_REAL_WORLD_REPORT.md`).
