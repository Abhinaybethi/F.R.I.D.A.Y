# PHASE 8 REPORT — Controlled Real Tool Execution

Generated: 2026-08-14
Status: **PASS** *(pending full regression confirmation)*

---

## 1. Architecture

```
Raw Audio
    ↓
Silero VAD
    ↓
faster-whisper STT
    ↓ (raw transcript)
Deterministic Router
    ↓ (Intent)
Local Llama 3 Reasoning fallback (OllamaReasoner)
    ↓ (validated dict)
JSON Parser + Reasoning Validator
    ↓ (Intent)
────────────────────────── PHASE 8 ADDITIONS ─────────────────────────
Permission Layer (friday/safety/permissions.py)
    ↓ PermissionResult: ALLOWED | CONFIRM_REQUIRED | DENIED
Plan Pre-Validator (friday/planning/plan_validator.py)
    ↓ rejects plan if ANY step is DENIED before execution starts
────────────────────────────────────────────────────────────────────
Safety Validator (confidence-based policy)
    ↓
Confirmation Gate (WAITING_FOR_CONFIRMATION state)
    ↓ explicit user "yes" required
tool registry.execute() + Audit Logger
    ↓ (structured log to logs/friday_audit.log)
apps / browser / files / system (whitelisted tools)
    ↓
Piper TTS
```

### Trust Boundaries

```
UNTRUSTED                          TRUSTED
────────────────────────────────────────────────────────────────
Raw audio
Raw transcript
LLM output (JSON)
                                   Deterministic router (Intent)
                                   Reasoning Validator (validated dict)
                                   Permission Layer (PermissionResult)  ← NEW
                                   Plan Pre-Validator                   ← NEW
                                   Safety Validator (confidence policy)
                                   Confirmation Gate (explicit "yes")
                                   tool registry.execute(Intent)
                                   Audit Logger                         ← NEW
                                   apps / browser / files / system (whitelisted)
```

---

## 2. Permission Model

### New module: `friday/safety/permissions.py`

```python
class PermissionResult(Enum):
    ALLOWED          = "allowed"
    CONFIRM_REQUIRED = "confirm_required"
    DENIED           = "denied"
```

**`check_permission(intent, permissions)` rules (in order):**

1. `UNKNOWN` action → `DENIED`
2. Action not in `_ACTION_PERMISSION_KEY` map → `DENIED`
3. `permissions[key] == False` → `DENIED`
4. `CLOSE_APP` → `CONFIRM_REQUIRED` (always, regardless of confidence)
5. Otherwise → `ALLOWED`

**Centralized.** No scattered if-statements elsewhere. All policy decisions go through this single function.

### Triple Execution Gate

Real execution requires **all three gates** simultaneously:

```
Gate 1: config.tools.dry_run == False
Gate 2: config.tools.allow_real_execution == True
Gate 3: permissions[action] == True  AND  PermissionResult != DENIED
```

Any single gate closed → dry-run mode. No exceptions.

---

## 3. Allowed Actions

| Action | Allowed Targets | Confirmation Required | Notes |
|---|---|---|---|
| `OPEN_APP` | chrome, edge, vscode, notepad, explorer | No | Fixed executable map, `subprocess.Popen([exe])` |
| `CLOSE_APP` | chrome, edge, vscode, notepad | **ALWAYS YES** | `psutil.terminate()` |
| `OPEN_WEBSITE` | youtube, google, github | No | Fixed HTTPS URL map, `webbrowser.open()` |
| `SEARCH_WEB` | any user text | No | `urllib.parse.quote_plus()` + fixed Google URL |
| `GET_TIME` | — | No | `datetime.now()`, stdlib only |
| `FIND_FILE` | any text | No | Read-only directory scan, safe dirs only |
| `OPEN_FOLDER` | downloads, documents, desktop | No | `os.startfile()` on fixed paths |
| `OPEN_FILE` | files within safe dirs | No | `os.startfile()` with path check |

---

## 4. Denied Actions

| Denial | Mechanism |
|---|---|
| `RUN_COMMAND` | Does not exist in `Action` enum — structurally impossible |
| `RUN_POWERSHELL` | Does not exist in `Action` enum — structurally impossible |
| `EXECUTE_CODE` | Does not exist in `Action` enum — structurally impossible |
| `DELETE_FILE` | Does not exist in `Action` enum — structurally impossible |
| `MOVE_FILE` | Does not exist in `Action` enum — structurally impossible |
| `shell=True` | Absent from all tool files (verified by test) |
| `os.system` | Absent from all tool files |
| `eval` / `exec` | Absent from all tool files |
| Unknown app name | `apps.py` whitelist rejects at tool level |
| Unknown website | `browser.py` whitelist rejects at tool level |
| Arbitrary path/URL | Not in whitelist → `"Not in registry"` |
| `permissions[action] == False` | Permission layer → `DENIED` |
| `Action.UNKNOWN` | Permission layer → `DENIED` |
| System dirs in FIND_FILE | `_SAFE_DIRS` limits search scope |
| File outside safe dirs | `open_file()` path check → rejected |

---

## 5. Confirmation Model

### CLOSE_APP always requires confirmation

The `CLOSE_APP` action is handled at **two independent layers**:

1. **Permission layer** (`permissions.py`): Returns `CONFIRM_REQUIRED` regardless of confidence
2. **Safety validator** (`validator.py`): Returns `Policy.CONFIRM` for `CLOSE_APP`

Both layers independently enforce confirmation. The conversation state machine transitions to `WAITING_FOR_CONFIRMATION` and **halts** until the user says an explicit affirmative word.

### Confirmation cannot be bypassed

- **By LLM**: Even if the reasoner returns `{"action": "CLOSE_APP", "confidence": 0.99}`, the safety validator still returns `CONFIRM` → state machine pauses. Verified by Gate 12.
- **By planner**: Multi-step plans with `CLOSE_APP` pause at that step for confirmation. Verified by Gate 13.
- **By second "yes" with no pending intent**: The state machine only acts on confirmation when `state == WAITING_FOR_CONFIRMATION` and `pending_intent != None`.

### Confirmation words

Affirmative: `yes, y, yeah, yep, yup, correct, sure, ok, okay, that's right, do it, go ahead`
Negative: `no, n, nope, cancel, abort, stop, never mind, nevermind`

---

## 6. Real Execution Gate

### Configuration to enable real execution

```yaml
tools:
  dry_run: false               # Gate 1
  allow_real_execution: true   # Gate 2

  permissions:                 # Gate 3 (all three must be true)
    open_app: true
    close_app: true
    open_folder: true
    open_website: true
    search_web: true
    get_time: true
    find_file: true
    open_file: true
```

**Default (safe) configuration:**
```yaml
tools:
  dry_run: true
  allow_real_execution: false
```

All real execution is disabled by default. No change is needed in the code to remain safe — the config alone controls it.

---

## 7. Security Analysis

### Static Scan Results (all `friday/tools/*.py`)

| Token | Files Scanned | Violations |
|---|---|---|
| `shell=True` | 5 | **0** |
| `os.system` | 5 | **0** |
| `subprocess` | 5 | 1 (`apps.py` — safe: `Popen([exe], close_fds=True)`) |
| `eval(` | 5 | **0** |
| `exec(` | 5 | **0** |

### `subprocess` usage in `apps.py`
```python
subprocess.Popen([exe], close_fds=True)
```
- `exe` is a **whitelisted string** from `_APP_EXECUTABLES` — not from user input or LLM output
- **List form** — no shell interpretation
- `shell=True` is absent
- `close_fds=True` — no file descriptor leakage

### Trust Chain

```
User speaks: "open chrome"
    → STT: "open chrome"
    → Router: Intent(OPEN_APP, "chrome", 0.98)
    → Permission: ALLOWED (open_app=True)
    → Validator: SAFE (confidence >= 0.85)
    → registry.execute(intent, dry_run, allow_real_execution, permissions)
    → apps.open_app("chrome", dry_run=False)
    → _find_executable("chrome")  →  fixed path from _APP_EXECUTABLES
    → subprocess.Popen(["/path/to/chrome.exe"], close_fds=True)
```

At no point does user text or LLM output reach `subprocess`.

### Legacy Dead Code
`friday/system_control/app_control.py` contains `os.startfile(target)` where `target` can be a spoken name. This module is **not imported** anywhere in the active pipeline. It is not invoked by the router, conversation manager, or tool registry. Flagged as technical debt for cleanup in a future phase.

---

## 8. Audit Logging

Every `registry.execute()` call emits one structured line to `logs/friday_audit.log`:

**Allowed execution:**
```
[ACTION] action=OPEN_APP target='chrome' permission=ALLOWED confirmation=N/A execution=DRY_RUN result=SUCCESS latency_ms=0.2
```

**Blocked execution:**
```
[ACTION] action=OPEN_APP target='C:\malicious.exe' permission=DENIED confirmation=N/A execution=BLOCKED result=BLOCKED latency_ms=0.0
```

**CLOSE_APP (confirmation required):**
```
[ACTION] action=CLOSE_APP target='chrome' permission=confirm_required confirmation=CONFIRMED execution=DRY_RUN result=SUCCESS latency_ms=0.1
```

---

## 9. Phase 8 Test Results

### New Phase 8 Test Modules

| Module | Tests | Type | Result |
|---|---|---|---|
| `test_permission_policy.py` | 17 | UNIT | ✅ 17/17 PASS |
| `test_real_execution_gate.py` | 11 | UNIT | ✅ 11/11 PASS |
| `test_execution_security.py` | 19 | UNIT/DRY RUN | ✅ 19/19 PASS |
| `test_real_apps.py` | 10 | DRY RUN | ✅ 10/10 PASS |
| `test_real_browser.py` | 11 | DRY RUN | ✅ 11/11 PASS |
| `test_real_files.py` | 11 | REAL READ-ONLY + DRY RUN | ✅ 11/11 PASS |
| `test_phase8_gate.py` | 17 | UNIT/DRY RUN | ✅ 17/17 PASS |
| **Total (Phase 8)** | **96** | | **✅ 96/96 PASS** |

### Phase 8 Gate — 17 Points

| Gate | Invariant | Result |
|---|---|---|
| 1 | Default config is safe (`dry_run=true`, `allow_real_execution=false`) | ✅ |
| 2 | `dry_run=true` prevents real execution | ✅ |
| 3 | `allow_real_execution=false` prevents real execution | ✅ |
| 4 | Both gates required for real execution | ✅ |
| 5 | `UNKNOWN` action is denied | ✅ |
| 6 | Unknown target rejected by tool whitelist | ✅ |
| 7 | Arbitrary executable paths denied | ✅ |
| 8 | `shell=True` absent from all tool files | ✅ |
| 9 | PowerShell command rejected | ✅ |
| 10 | Destructive actions not in `Action` enum | ✅ |
| 11 | `CLOSE_APP` requires confirmation | ✅ |
| 12 | LLM cannot bypass confirmation for `CLOSE_APP` | ✅ |
| 13 | Planner cannot bypass confirmation for `CLOSE_APP` | ✅ |
| 14 | Plan steps independently validated | ✅ |
| 15 | Denied step aborts entire plan before execution | ✅ |
| 16 | Audit log written with action details | ✅ |
| 17 | `permissions:` section present in `config.yaml` | ✅ |

### Security Test Results

| Attack Vector | Result |
|---|---|
| `"run powershell"` | ✅ DENIED |
| `"execute cmd"` | ✅ DENIED |
| `"run rm -rf on my computer"` | ✅ DENIED |
| `"delete my files"` | ✅ DENIED |
| `"delete C:\Users"` | ✅ DENIED |
| `"open C:\malicious.exe"` | ✅ DENIED |
| `"execute shell command dir /s"` | ✅ DENIED |
| `"execute python"` | ✅ DENIED |
| LLM JSON `{"action":"RUN_COMMAND","arguments":{"command":"..."}}` | ✅ REJECTED by reasoning validator |
| LLM JSON `{"arguments":{"shell":"powershell..."}}` | ✅ REJECTED by reasoning validator |
| `eval(os.system(...))` as app target | ✅ REJECTED by app whitelist |
| Plan with permission-denied step | ✅ ENTIRE PLAN REJECTED |

---

## 10. Regression Results

**134 passed in 158.02s (0:02:38) — ZERO failures.**

| Test Module | Tests | Phase | Result |
|---|---|---|---|
| `test_tts.py` | 1 | Phase 5 | ✅ |
| `test_voice_response.py` | 1 | Phase 5 | ✅ |
| `test_planner.py` | 1 | Phase 6 | ✅ |
| `test_context.py` | 1 | Phase 6 | ✅ |
| `test_plan_execution.py` | 1 | Phase 6 | ✅ |
| `test_multi_step_commands.py` | 1 | Phase 6 | ✅ |
| `test_phase6_gate.py` | 1 | Phase 6 | ✅ |
| `test_reasoning_parser.py` | 5 | Phase 7 | ✅ |
| `test_reasoning_validator.py` | 6 | Phase 7 | ✅ |
| `test_reasoning_router.py` | 5 | Phase 7 | ✅ |
| `test_reasoning_context.py` | 1 | Phase 7 | ✅ |
| `test_reasoning_security.py` | 2 | Phase 7 | ✅ |
| `test_real_reasoning.py` | 12 | Phase 7 | ✅ |
| `test_permission_policy.py` | 17 | Phase 8 | ✅ |
| `test_real_execution_gate.py` | 11 | Phase 8 | ✅ |
| `test_execution_security.py` | 19 | Phase 8 | ✅ |
| `test_real_apps.py` | 10 | Phase 8 | ✅ |
| `test_real_browser.py` | 11 | Phase 8 | ✅ |
| `test_real_files.py` | 11 | Phase 8 | ✅ |
| `test_phase8_gate.py` | 17 | Phase 8 | ✅ |
| **TOTAL** | **134** | | **✅ ALL PASS** |

---

## 11. Known Limitations

1. **`friday/system_control/` dead code** — Contains `app_control.py` with `os.startfile(spoken_name)` where `spoken_name` comes from user input. **Not in active pipeline**, but is a latent risk if imported in the future. Recommend deletion in Phase 9.

2. **`open_file` not wired to router** — `OPEN_FILE` action exists in the registry and tool layer but the deterministic router has no pattern for "open file X". It can only be invoked via the reasoner. This means it's practically inaccessible without a specific Ollama output. Not a security risk (safe-dir check is still enforced), but a usability gap.

3. **Hardware TTS/microphone** — Not verified in automated tests. Out of scope for Phase 8.

4. **`find_file` scans only top-level of each safe dir** — It calls `dir.iterdir()` (one level deep). Nested files are not found. Acceptable for Phase 8; recursive search can be added later.

5. **`CLOSE_APP` with `dry_run=True`** — After user confirms, `apps.close_app("chrome", dry_run=True)` is called. This returns `"[DRY RUN] Would close Chrome."` — no actual process is terminated. Real close requires both config gates enabled.

---

## 12. Configuration to Enable Real Execution

To enable real execution, make **all three** of these changes in `config.yaml`:

```yaml
tools:
  dry_run: false               # Change from: true
  allow_real_execution: true   # Change from: false
  permissions:
    open_app: true             # already true
    close_app: true            # already true
    ...
```

Then restart F.R.I.D.A.Y. No code changes required.

> [!CAUTION]
> Never set `dry_run: false` and `allow_real_execution: true` simultaneously in automated test environments.
> The regression suite runs with `dry_run: true` and `allow_real_execution: false` by default.
> Real execution tests require the `--allow-real` CLI flag AND the config changes above.

---

## 13. Files Changed

| File | Change |
|---|---|
| `friday/safety/permissions.py` | **NEW** — centralized permission layer |
| `friday/utils/audit_logger.py` | **NEW** — structured audit log |
| `friday/planning/plan_validator.py` | **NEW** — upfront whole-plan validation |
| `friday/tools/registry.py` | **MODIFIED** — integrates permission check + audit logging |
| `friday/planning/executor.py` | **MODIFIED** — forwards `permissions` arg to registry |
| `friday/core/conversation.py` | **MODIFIED** — `permissions` param; `validate_plan()` before execution; reasoner-generated plans also validated |
| `config.yaml` | **MODIFIED** — added `permissions:` section (Gate 3) |
| `tests/test_permission_policy.py` | **NEW** — 17 unit tests |
| `tests/test_real_execution_gate.py` | **NEW** — 11 gate tests |
| `tests/test_execution_security.py` | **NEW** — 19 security tests |
| `tests/test_real_apps.py` | **NEW** — 10 app tool tests |
| `tests/test_real_browser.py` | **NEW** — 11 browser tool tests |
| `tests/test_real_files.py` | **NEW** — 11 file tool tests |
| `tests/test_phase8_gate.py` | **NEW** — 17-point gate |

**Unchanged:** STT, VAD, TTS, deterministic router, planner, safety validator confidence logic, confirmation engine, reasoning layer, intent models.

---

## 14. Phase 8 Status

```
PHASE 8 CONTROLLED REAL TOOL EXECUTION: PASS
PERMISSION LAYER:        IMPLEMENTED + TESTED
AUDIT LOGGING:           IMPLEMENTED + TESTED
PLAN PRE-VALIDATION:     IMPLEMENTED + TESTED (deterministic + reasoner paths)
SECURITY SCAN:           CLEAN (0 violations)
PHASE 8 GATE (17/17):    ALL PASS
REAL EXECUTION:          DISABLED (dry_run: true, allow_real_execution: false)
DEFAULT CONFIG:          SAFE
```
