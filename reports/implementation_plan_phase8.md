# Phase 8 — Controlled Real Tool Execution
## Implementation Plan

---

## Background & What I Found

### Current Architecture (Phase 7 baseline)

```
Transcript → normalize → Deterministic Router → Intent
                                                    ↓
                                             OllamaReasoner fallback
                                                    ↓
                                         JSON Parser + Reasoning Validator
                                                    ↓
                                         Safety Validator (confidence policy)
                                                    ↓
                                         Confirmation (if needed)
                                                    ↓
                                         tool registry.execute()
                                                    ↓
                                         apps / browser / files / system
```

### Existing Tool Layer (already partially correct)

| File | What it does | Quality |
|---|---|---|
| `friday/tools/registry.py` | Maps `Action` enum → tool function | ✅ Clean |
| `friday/tools/apps.py` | `open_app` / `close_app` via fixed whitelist → `subprocess.Popen([exe])` (NO `shell=True`) | ✅ Safe |
| `friday/tools/browser.py` | `open_website` / `search_web` via `webbrowser` + `urllib.parse.quote_plus` | ✅ Safe |
| `friday/tools/files.py` | `find_file` read-only search; `open_file` / `open_folder` via `os.startfile` | ✅ Safe |
| `friday/tools/system.py` | `get_time()` — pure stdlib | ✅ Safe |

### What is MISSING (Phase 8 must add)

1. **Per-action permission layer** — safety validator only checks confidence, not explicit permission config
2. **Per-action permission config** in `config.yaml`
3. **Audit logging** — no structured action log
4. **Upfront plan validation** — planner validates step-by-step, not whole-plan before starting (partial execution risk)
5. **Phase 8 test files** — none exist yet

### Security Findings

| Item | Status |
|---|---|
| `shell=True` in `friday/tools/` | ✅ ABSENT |
| `os.system` in `friday/tools/` | ✅ ABSENT |
| `subprocess` in `friday/tools/` | ⚠️ Present in `apps.py` only — `Popen([exe], close_fds=True)` — SAFE (list form, whitelisted exe only) |
| `subprocess` in `friday/system_control/` | ⚠️ LEGACY, not in active pipeline. `app_control.py` does `os.startfile(target)` where target is from spoken name — risk IF called |
| `eval` / `exec` in `friday/tools/` | ✅ ABSENT |
| LLM text → subprocess | ✅ ABSENT (multiple layers between) |

---

## Trust Boundaries

```
UNTRUSTED                          TRUSTED
────────────────────────────────────────────────────────────
Raw audio
Raw transcript
LLM output (JSON)
                                   Deterministic router (Intent)
                                   Reasoning validator (validated dict)
                                   Safety Validator (confidence policy)
                                   PermissionPolicy decision  ← NEW
                                   Confirmation gate (explicit user "yes")
                                   tool registry.execute(Intent)
                                   apps / browser / files / system (whitelisted)
```

---

## Allowed Actions (Explicit Allowlist)

| Action | Allowed Targets | Confirmation | Notes |
|---|---|---|---|
| `OPEN_APP` | chrome, edge, vscode, notepad, explorer | No | Fixed exe map |
| `CLOSE_APP` | chrome, edge, vscode, notepad | **ALWAYS YES** | psutil terminate |
| `OPEN_WEBSITE` | youtube, google, github | No | Fixed HTTPS URLs |
| `SEARCH_WEB` | any user text | No | URL-encoded, fixed engine |
| `GET_TIME` | — | No | stdlib only |
| `FIND_FILE` | any text | No | Read-only, safe dirs |
| `OPEN_FOLDER` | downloads, documents, desktop | No | Fixed paths |
| `OPEN_FILE` | files within safe dirs | No | os.startfile only |

**DENIED (absolute):**
- Any app not in `_APP_EXECUTABLES` whitelist
- Any website not in `_WEBSITE_URLS` whitelist
- `RUN_COMMAND`, `EXECUTE_CODE`, `DELETE_FILE` — do not exist in `Action` enum
- `shell=True` execution — structurally impossible (never in codebase)

---

## Configuration Model

### New `config.yaml` `tools:` section

```yaml
tools:
  dry_run: true
  allow_real_execution: false

  permissions:
    open_app: true
    close_app: true
    open_folder: true
    open_website: true
    search_web: true
    get_time: true
    find_file: true
    open_file: true
```

### Triple gate for real execution

```
real_execution = (dry_run == False)
             AND (allow_real_execution == True)
             AND (permissions[action] == True)
```

Any gate closed → dry-run. Default config has dry_run=true and allow_real_execution=false, so no real execution by default.

---

## Permission Layer Design

### New: `friday/safety/permissions.py`

```python
class PermissionResult(Enum):
    ALLOWED          = "allowed"
    CONFIRM_REQUIRED = "confirm_required"
    DENIED           = "denied"

def check_permission(intent: Intent, permissions: dict) -> PermissionResult:
    ...
```

**Rules (evaluated in order):**
1. `action == UNKNOWN` → `DENIED`
2. `action.name.lower()` not in `permissions` → `DENIED`
3. `permissions[action_key] == False` → `DENIED`
4. `action == CLOSE_APP` → `CONFIRM_REQUIRED` (always, regardless of confidence)
5. Otherwise → `ALLOWED`

Tool-level whitelist checks (unknown app name, unknown website) are handled inside each tool and return `success=False`. The permission layer handles action-level policy; the tool layer handles target-level policy.

**Centralized** — no scattered if-statements outside this module.

---

## Audit Logging

### New: `friday/utils/audit_logger.py`

Every `registry.execute()` call emits:

```
[ACTION] action=OPEN_APP target=chrome permission=ALLOWED confirmation=NOT_REQUIRED execution=REAL result=SUCCESS latency_ms=42
[ACTION] action=OPEN_APP target=bad.exe permission=DENIED execution=BLOCKED
[ACTION] action=CLOSE_APP target=chrome permission=CONFIRM_REQUIRED confirmation=PENDING execution=HELD
```

Written to `logs/friday_audit.log`. Separate from the main debug log. Never logs secrets or user personal data.

---

## Plan Pre-Validation

**Current:** Planner validates one step at a time during execution — steps 1-2 may execute before step 3 is found to be DENIED.

**Phase 8:** Before ANY step executes, the entire plan is validated upfront.

### New: `friday/planning/plan_validator.py`

```python
def validate_plan(plan: ActionPlan, permissions: dict) -> tuple[bool, str]:
    """Returns (ok, reason). If not ok, reason explains why."""
    for step in plan.steps:
        result = check_permission(step, permissions)
        if result == PermissionResult.DENIED:
            return False, f"Step {step.action.name}({step.target}) is not permitted."
    return True, ""
```

CONFIRM_REQUIRED steps are **valid** (they pause execution for user confirmation). Only DENIED steps abort the whole plan.

### Integration in `friday/core/conversation.py`

Before `_continue_plan()` is called, `validate_plan()` is called. If not ok, the plan is cancelled with an explanation.

---

## Incremental Implementation

### Increment 1 — Permission layer
- **[NEW]** `friday/safety/permissions.py`
- **[MODIFY]** `config.yaml` — add `permissions:` section
- **[NEW]** `tests/test_permission_policy.py`

### Increment 2 — Registry + audit log integration
- **[MODIFY]** `friday/tools/registry.py` — call `check_permission()`, emit audit
- **[NEW]** `friday/utils/audit_logger.py`
- **[NEW]** `tests/test_real_execution_gate.py`

### Increment 3 — Upfront plan validation
- **[NEW]** `friday/planning/plan_validator.py`
- **[MODIFY]** `friday/core/conversation.py` — call `validate_plan()` before `_continue_plan()`
- Security tests for malicious multi-step added to `tests/test_execution_security.py`

### Increment 4 — Real safe execution tests (dry-run by default)
- **[NEW]** `tests/test_real_apps.py`
- **[NEW]** `tests/test_real_browser.py`
- **[NEW]** `tests/test_real_files.py`

### Increment 5 — Security tests
- **[NEW]** `tests/test_execution_security.py`

### Increment 6 — Phase 8 gate
- **[NEW]** `tests/test_phase8_gate.py`

### Increment 7 — Full regression
All 22+ test modules.

---

## Non-Negotiable Security Checklist

- [x] LLM never directly executes a tool
- [x] Raw transcript never executes
- [x] Only validated Intent reaches registry
- [ ] **NEW** Per-action permission policy (Increment 1)
- [x] Unknown actions fail closed (registry default)
- [x] Unknown targets fail closed (tool whitelist)
- [x] shell=True — ABSENT
- [x] os.system — ABSENT
- [x] eval/exec — ABSENT
- [x] subprocess only with whitelisted, list-form exe
- [x] File deletion — not implemented
- [x] File modification — not implemented
- [x] Arbitrary URL navigation — blocked
- [x] Arbitrary app launching — blocked
- [ ] **NEW** Audit log (Increment 2)
- [ ] **NEW** Pre-validate whole plan (Increment 3)
