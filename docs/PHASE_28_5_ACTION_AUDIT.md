# F.R.I.D.A.Y. Phase 28.5 Action Execution & Verification Audit

## 1. System Overview

This document presents a comprehensive, end-to-end audit of the F.R.I.D.A.Y. Action Execution & Verification Pipeline across the complete turn lifecycle:
```
VOICE → STT → ROUTER/CONTEXT → SAFETY → PLANNER/EXECUTOR → TOOL REGISTRY → ACTION VERIFIER → ACTION OUTCOME → TTS
```

---

## 2. Codebase Pipeline Inspection

The audit inspected the following core modules and subsystems:
- **Canonical Orchestrator**: `friday/core/assistant.py` (`Friday` class, `_handle()`, `run()`)
- **Conversation Manager & Context**: `friday/core/conversation.py` (`ConversationManager`, `handle_transcript()`, `_continue_plan()`, `ConversationContext`, `ShortTermContext`)
- **Intent Router & Resolvers**: `friday/intent/router.py` (`route()`), `friday/intent/resolver.py` (`resolve_app()`, `resolve_website()`), `friday/planning/context_resolver.py` (`resolve_context()`)
- **Safety & Permissions Policy**: `friday/safety/permissions.py` (`check_permission()`), `friday/safety/validator.py` (`validate()`), `friday/safety/confirmation.py` (`parse_confirmation_response()`)
- **Multi-Step Planner & Executor**: `friday/planning/planner.py` (`parse_plan()`), `friday/planning/plan_validator.py` (`validate_plan()`), `friday/planning/executor.py` (`execute_plan_step()`)
- **Tool Registry & Execution Dispatch**: `friday/tools/registry.py` (`execute()`, `_dispatch()`), `apps.py`, `browser.py`, `files.py`, `memory.py`, `system.py`, `desktop.py`
- **Verification Subsystem**: `friday/verification/verifier.py` (`verify_execution()`), `friday/verification/action_verifiers.py` (`verify_open_app()`, `verify_close_app()`, `verify_open_folder()`, `verify_open_website()`, `verify_search_web()`, `verify_find_file()`, `verify_open_file()`, `verify_get_time()`), `friday/verification/models.py` (`ExecutionResult`, `VerificationResult`, `ActionOutcome`)
- **Response Engine & TTS**: `friday/response/engine.py` (`format_spoken_response()`), `friday/voice/text_to_speech.py` (`TextToSpeech`, `speak()`)

---

## 3. End-to-End Command Traces (10 Benchmark Commands)

### Command 1: `open Chrome`
- **STT Entry Point**: `Friday._handle("open Chrome")` → `ConversationManager.handle_transcript("open Chrome")`
- **Intent Produced**: `Intent(action=Action.OPEN_APP, target="chrome", confidence=0.90, requires_confirmation=False)`
- **Entities/Targets Resolved**: Target `"chrome"` resolved to canonical app `"chrome"` via `resolve_app("chrome")`.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE` (`conf=0.90 >= 0.85`). `check_permission()` → `PermissionResult.ALLOWED` (`perms["open_app"] = True`).
- **Planner Behavior**: Single-turn execution. Gating bypasses reasoner (`should_call_reasoner` → `False`).
- **Executor/Tool Called**: `registry.execute()` → `_dispatch(Action.OPEN_APP, "chrome", is_dry_run)` → `apps.open_app("chrome", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True` / `allow_real=False`: Returns `"[DRY RUN] Would open Chrome."`. NO subprocess launched.
  - `dry_run=False` & `allow_real=True`: Locates executable (`C:\Program Files\Google\Chrome\Application\chrome.exe` or `chrome`) and executes `subprocess.Popen([exe])`. Real OS process launched!
- **Independent Verification**:
  - `verify_open_app("chrome", is_dry_run)`:
    - `is_dry_run=True`: Returns `VerificationStatus.DRY_RUN`.
    - `is_dry_run=False`: Queries active system processes using `psutil.process_iter(["name"])` for `chrome.exe`. Returns `VerificationStatus.VERIFIED_SUCCESS` if process active, or `FAILED` if not found.
- **ActionResult / ActionOutcome Structure**:
  - `ExecutionResult`: `status=SUCCESS`, `message="Opening Chrome."`
  - `VerificationResult`: `status=VERIFIED_SUCCESS` (real) or `DRY_RUN` (simulated)
  - `ActionOutcome`: `final_status=SUCCESS` / `DRY_RUN`, `spoken_message="Opening Chrome."`
- **Final Conversational Response / TTS**: `"Opening Chrome."` spoken via `TextToSpeech.speak()`.
- **Failure Behavior**: If executable missing in real mode: `ExecutionStatus.FAILED`. Verification skipped (`SKIPPED`). Final status `FAILED`. Spoken response: `"I couldn't confirm that Chrome completed successfully."`
- **Dry-Run Effect**: Dry-run bypasses `subprocess.Popen` and returns simulated verification.
- **Classification**:
  - `dry_run=True`: **SIMULATED**
  - `real execution`: **REAL + VERIFIED**

---

### Command 2: `open YouTube`
- **STT Entry Point**: `ConversationManager.handle_transcript("open YouTube")`
- **Intent Produced**: `Intent(action=Action.OPEN_WEBSITE, target="youtube", confidence=0.90, requires_confirmation=False)`
- **Entities/Targets Resolved**: Target `"youtube"` resolved to `_WEBSITE_URLS["youtube"]` = `"https://www.youtube.com"`.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE`. `check_permission()` → `ALLOWED`. `_validate_url_security("https://www.youtube.com")` → Safe (scheme `https`, domain `youtube.com` whitelisted).
- **Planner Behavior**: Single-turn execution. Reasoner bypassed.
- **Executor/Tool Called**: `registry.execute()` → `browser.open_website("youtube", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True`: Returns `"[DRY RUN] Would open https://www.youtube.com"`. NO browser window opened.
  - `dry_run=False` & `allow_real=True`: Calls `webbrowser.open("https://www.youtube.com")`. Real OS browser window launched!
- **Independent Verification**:
  - `verify_open_website("youtube", is_dry_run)`:
    - `is_dry_run=True`: Returns `VerificationStatus.DRY_RUN`.
    - `is_dry_run=False`: **AUDIT FINDING**: `verify_open_website` ONLY checks dictionary presence (`_WEBSITE_URLS.get("youtube")`) or URL domain whitelist string! It does **NOT** inspect browser process or page load!
- **ActionResult / ActionOutcome Structure**: `ActionOutcome` containing `ExecutionResult` and `VerificationResult`.
- **Final Conversational Response / TTS**: `"Opening Youtube."` spoken via TTS.
- **Failure Behavior**: If URL fails SSRF or domain check: `ExecutionStatus.FAILED`.
- **Dry-Run Effect**: Dry-run skips `webbrowser.open()`.
- **Classification**:
  - `dry_run=True`: **SIMULATED**
  - `real execution`: **REAL + UNVERIFIED** (Verifier checks dictionary string, not active browser window/tab)

---

### Command 3: `open Downloads`
- **STT Entry Point**: `ConversationManager.handle_transcript("open Downloads")`
- **Intent Produced**: `Intent(action=Action.OPEN_FOLDER, target="download", confidence=0.98, requires_confirmation=False)`
- **Entities/Targets Resolved**: Target `"download"` mapped via `_FOLDER_ALIASES` → `"downloads"` → Path `C:\Users\<user>\Downloads`.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE`. `check_permission()` → `ALLOWED`.
- **Planner Behavior**: Single-turn execution. Reasoner bypassed.
- **Executor/Tool Called**: `registry.execute()` → `files.open_folder("download", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True`: Returns `"[DRY RUN] Would open folder..."`. NO Explorer window launched.
  - `dry_run=False` & `allow_real=True`: Calls `os.startfile(r"C:\Users\<user>\Downloads")`. Real File Explorer launched!
- **Independent Verification**:
  - `verify_open_folder("download", is_dry_run)`:
    - `is_dry_run=True`: Returns `VerificationStatus.DRY_RUN`.
    - `is_dry_run=False`: **AUDIT FINDING**: `verify_open_folder` checks whether `C:\Users\<user>\Downloads` exists on disk! It does **NOT** check whether File Explorer (`explorer.exe`) opened or displayed the window!
- **ActionResult / ActionOutcome Structure**: `ActionOutcome`.
- **Final Conversational Response / TTS**: `"Opening Download folder."` spoken via TTS.
- **Failure Behavior**: Returns error if target folder missing from disk.
- **Dry-Run Effect**: Dry-run skips `os.startfile()`.
- **Classification**:
  - `dry_run=True`: **SIMULATED**
  - `real execution`: **REAL + UNVERIFIED** (Verifier checks disk directory existence, not Explorer window)

---

### Command 4: `find my resume`
- **STT Entry Point**: `ConversationManager.handle_transcript("find my resume")`
- **Intent Produced**: `Intent(action=Action.FIND_FILE, target="resume", confidence=0.90, requires_confirmation=False)`
- **Entities/Targets Resolved**: Target `"resume"`. Cleaned in `files.find_file` to `"resume"`.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE`. `check_permission()` → `ALLOWED`. Traversal check `_contains_traversal()` → `False`.
- **Planner Behavior**: Single-turn execution. Bypasses reasoner.
- **Executor/Tool Called**: `registry.execute()` → `files.find_file("resume")`. Note: `find_file` is read-only file search. It does NOT take `dry_run` parameter! It ALWAYS scans safe directories (`Desktop`, `Documents`, `Downloads`) via `os.scandir()`.
- **Real OS/Browser Action**: Real filesystem scanning (`os.scandir()`) occurs on disk in safe directories (read-only OS operation).
- **Independent Verification**:
  - `verify_find_file("resume", is_dry_run)`: Returns `VerificationStatus.NOT_APPLICABLE` ("Verification not applicable for FIND_FILE.") because `FIND_FILE` is read-only file search.
- **ActionResult / ActionOutcome Structure**: `ActionOutcome` containing `candidates` list in `raw_tool_result`. Context updated with `last_search_results` / `last_target`.
- **Final Conversational Response / TTS**: `"I found 1 files matching resume. The latest one is resume.pdf."` spoken via TTS.
- **Failure Behavior**: Returns `success=False` with `"I couldn't find any files matching resume."` if no candidates match.
- **Dry-Run Effect**: None. Read-only search executes filesystem scan regardless of `dry_run`.
- **Classification**:
  - `dry_run=True` / `real execution`: **REAL + UNVERIFIED** (Read-only OS disk search; verifier returns `NOT_APPLICABLE`)

---

### Command 5: `search Python tutorials`
- **STT Entry Point**: `ConversationManager.handle_transcript("search Python tutorials")`
- **Intent Produced**: `Intent(action=Action.SEARCH_WEB, target="python tutorials", confidence=0.90, requires_confirmation=False)`
- **Entities/Targets Resolved**: Query string `"python tutorials"`, URL-encoded as `"python+tutorials"`.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE`. `check_permission()` → `ALLOWED`.
- **Planner Behavior**: Single-turn execution. Bypasses reasoner.
- **Executor/Tool Called**: `registry.execute()` → `browser.search_web("python tutorials", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True`: Returns 3 dummy result dicts. NO network request made.
  - `dry_run=False` & `allow_real=True`: Calls DuckDuckGo search API (`duckduckgo_search.DDGS().text(...)`). Real HTTPS web request executed!
- **Independent Verification**:
  - `verify_search_web("python tutorials", is_dry_run)`:
    - `is_dry_run=True`: Returns `VerificationStatus.DRY_RUN`.
    - `is_dry_run=False`: **AUDIT FINDING**: `verify_search_web` ONLY checks if query string is non-empty (`query and query.strip()`)! It does **NOT** verify HTTP response, status, or search results returned!
- **ActionResult / ActionOutcome Structure**: `ActionOutcome` containing `results` list (3 items). `last_search_results` populated in `ConversationContext`.
- **Final Conversational Response / TTS**: `"Searching Google for python tutorials."` spoken via TTS.
- **Failure Behavior**: If network fails, returns empty `results: []` with fallback message.
- **Dry-Run Effect**: Dry-run returns simulated dummy results.
- **Classification**:
  - `dry_run=True`: **SIMULATED**
  - `real execution`: **REAL + UNVERIFIED** (Verifier checks query string non-emptiness, not search payload)

---

### Command 6: `open first result`
- **STT Entry Point**: `ConversationManager.handle_transcript("open first result")`
- **Intent Produced**:
  - `resolve_context("open first result", st_context)`: Matches `_RESULT_REF_PAT`. Maps `"first"` → index `0`.
  - **With context search results**: Extracts URL `first_url` (e.g. `https://example.com/1?q=python+tutorials`). Returns `("go to https://example.com/1...", "")`. `route()` returns `Intent(action=Action.OPEN_WEBSITE, target="https://example.com/1...", confidence=0.90)`.
  - **Without context search results**: `resolve_context` returns `("", "I don't have a result list to open.")`.
- **Entities/Targets Resolved**: Ordinal index `0` resolved to URL from `ConversationContext.last_search_results`.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE`. `check_permission()` → `ALLOWED`. `_validate_url_security` checks scheme/host.
- **Planner Behavior**: Single-turn context resolution + routing.
- **Executor/Tool Called**: `registry.execute()` → `browser.open_website("https://example.com/1...", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True`: Returns `"[DRY RUN] Would open..."`. NO browser window opened.
  - `dry_run=False` & `allow_real=True`: Calls `webbrowser.open("https://example.com/1...")`. Real OS browser launched!
- **Independent Verification**: `verify_open_website` checks domain whitelist string (`example.com`). Does **NOT** check browser window process or page load!
- **ActionResult / ActionOutcome Structure**: `ActionOutcome`.
- **Final Conversational Response / TTS**: `"Opening https://example.com/1."` spoken via TTS.
- **Failure Behavior**: If no search results in context: returns error response `"I don't have a result list to open."` immediately.
- **Dry-Run Effect**: Dry-run skips `webbrowser.open()`.
- **Classification**:
  - Without context search results: **FAILS** (context missing)
  - `dry_run=True` (with context): **SIMULATED**
  - `real execution` (with context): **REAL + UNVERIFIED**

---

### Command 7: `read it`
- **STT Entry Point**: `ConversationManager.handle_transcript("read it")`
- **Intent Produced**:
  - `resolve_context("read it", st_context)`: Evaluates `"read it"` pronoun rule. Checks `get_recent_target()`.
  - **If recent target is URL/website** (`https://example.com/1`): Returns `("read website https://example.com/1", "")`. `route()` returns `Intent(action=Action.READ_WEBSITE, target="https://example.com/1", confidence=0.90)`.
  - **If NO recent target exists**: Returns `("", "I don't know what to read.")`.
- **Entities/Targets Resolved**: Pronoun `"it"` resolved to `last_target` from short-term context.
- **Safety Policy Applied**: `validate()` → `Policy.SAFE`. `check_permission()` → `perms["read_website"] = True` → `ALLOWED`.
- **Planner Behavior**: Single-turn context resolution + routing.
- **Executor/Tool Called**: `registry.execute()` → `browser.read_website("https://example.com/1", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True`: Returns `"[DRY RUN] Would read..."`. NO HTTP request made.
  - `dry_run=False` & `allow_real=True`: Performs real HTTP GET request using `requests.get(...)` (10s timeout, 2MB limit, BeautifulSoup text extraction). Real network HTTP fetch performed!
- **Independent Verification**:
  - **AUDIT FINDING**: `Action.READ_WEBSITE` is **MISSING** from `_VERIFIER_TABLE` in `friday/verification/verifier.py`!
  - `verify_execution()` returns `VerificationResult(status=VerificationStatus.NOT_APPLICABLE, message="No verifier registered for action READ_WEBSITE.")`.
- **ActionResult / ActionOutcome Structure**: `ActionOutcome` containing extracted text snippet in `spoken_message`.
- **Final Conversational Response / TTS**: `"Here is the page content: ..."` spoken via TTS.
- **Failure Behavior**: If no target in context: `"I don't know what to read."`. If HTTP fails/times out: `"I could not read the website."`.
- **Dry-Run Effect**: Dry-run skips HTTP request.
- **Classification**:
  - Without target context: **FAILS** (missing context)
  - `dry_run=True` (with context): **SIMULATED**
  - `real execution` (with context): **REAL + UNVERIFIED** (No verifier function registered)

---

### Command 8: `stop`
- **STT Entry Point**: `ConversationManager.handle_transcript("stop")`
- **Intent Produced**:
  - Matches Priority 1 Global System Command in `handle_transcript`: `norm_trans in ("stop", "shut down", "exit", "quit", "goodbye")`.
  - Handled immediately before routing, validation, or registry dispatch!
- **Entities/Targets Resolved**: None (Global lifecycle command).
- **Safety Policy Applied**: Bypasses safety policy & permission gate. Always allowed.
- **Planner Behavior**: Clears `pending_intent`, cancels `current_plan`, transitions state machine `LISTENING` → `STOPPING`.
- **Executor/Tool Called**: None (Internal state machine lifecycle transition).
- **Real OS/Browser Action**: No external OS process launched. Assistant event loop terminates.
- **Independent Verification**: N/A (Internal lifecycle event).
- **ActionResult / ActionOutcome Structure**: Returns tuple `("Goodbye.", False)` directly to `Friday._handle()`.
- **Final Conversational Response / TTS**: `"Goodbye."` spoken via TTS. `Friday.run()` breaks main loop and shuts down.
- **Failure Behavior**: Always succeeds cleanly.
- **Dry-Run Effect**: None. Lifecycle control behaves identically regardless of `dry_run`.
- **Classification**: **REAL + VERIFIED** (System Control Event — internal state transition and loop termination confirmed)

---

### Command 9: `cancel`
- **STT Entry Point**: `ConversationManager.handle_transcript("cancel")`
- **Intent Produced**:
  - Matches Priority 2 Global System Command in `handle_transcript`: `norm_trans in ("cancel", "never mind", "nevermind", "abort")`.
  - Handled immediately as Global System Command.
- **Entities/Targets Resolved**: None.
- **Safety Policy Applied**: Bypasses safety policy & permission gate. Always allowed.
- **Planner Behavior**: Clears `pending_intent`, cancels `current_plan` (`state = PlanState.CANCELLED`), resets state machine to `LISTENING`.
- **Executor/Tool Called**: None.
- **Real OS/Browser Action**: No external OS process launched. Internal state machine reset.
- **Independent Verification**: N/A (Internal lifecycle event).
- **ActionResult / ActionOutcome Structure**: Returns tuple `("Cancelled.", True)`.
- **Final Conversational Response / TTS**: `"Cancelled."` spoken via TTS. Assistant remains in `LISTENING` state.
- **Failure Behavior**: Always succeeds cleanly.
- **Dry-Run Effect**: None.
- **Classification**: **REAL + VERIFIED** (System Control Event — state reset confirmed)

---

### Command 10: `forget a memory`
- **STT Entry Point**: `ConversationManager.handle_transcript("forget a memory")`
- **Intent Produced**: `Intent(action=Action.FORGET, target="a memory", confidence=0.98, requires_confirmation=True)`
- **Entities/Targets Resolved**: Search query `"a memory"`.
- **Safety Policy Applied**:
  - `validate()` → `Policy.CONFIRM` (`Action.FORGET` always requires confirmation).
  - `check_permission()` → `PermissionResult.CONFIRM_REQUIRED`.
  - `handle_transcript` sees `Policy.CONFIRM`. Transitions state machine to `WAITING_FOR_CONFIRMATION`, sets `confirmation_start_time`, returns prompt: `"Do you want me to forget 'a memory'?"`.
  - **Turn 2 (User says "yes")**: `parse_confirmation_response("yes")` → `True`. Pending intent retrieved. State transitions to `EXECUTING`. Calls `registry.execute(pending, ...)`.
- **Planner Behavior**: Multi-turn confirmation gate. Halts tool execution until explicit user confirmation.
- **Executor/Tool Called**: `registry.execute()` → `memory.forget("a memory", dry_run=is_dry_run)`.
- **Real OS/Browser Action**:
  - `dry_run=True`: Searches SQLite DB for best match, logs `[DRY RUN]`, but does NOT execute `DELETE FROM memories`. DB unchanged.
  - `dry_run=False` & `allow_real=True`: Searches SQLite DB, executes `DELETE FROM memories WHERE id = ?`, commits SQL transaction. Real SQLite database deletion performed!
- **Independent Verification**:
  - **AUDIT FINDING**: `Action.FORGET` (and `Action.REMEMBER`, `Action.RECALL`) are **MISSING** from `_VERIFIER_TABLE` in `friday/verification/verifier.py`!
  - `verify_execution()` returns `VerificationResult(status=VerificationStatus.NOT_APPLICABLE, message="No verifier registered for action FORGET.")`.
- **ActionResult / ActionOutcome Structure**: `ActionOutcome` containing `user_message` = `"Forgot: <content>"` or `"No memory found..."`.
- **Final Conversational Response / TTS**: `"I have forgotten that."` spoken via TTS.
- **Failure Behavior**: If no matching memory in DB: returns `success=False` with `"I couldn't find anything matching that to forget."`.
- **Dry-Run Effect**: Dry-run skips SQL `DELETE` query.
- **Classification**:
  - Before confirmation: **BLOCKED** (Pending user confirmation)
  - After user confirms ("yes"):
    - `dry_run=True`: **SIMULATED**
    - `real execution`: **REAL + UNVERIFIED** (No verifier function registered)

---

## 4. Benchmark Command Classification Matrix

| # | Command | Target Action | Real OS/Browser Execution Target | Verifier Implementation Status | Classification (`dry_run=True`) | Classification (`real execution`) |
|---|---|---|---|---|---|---|
| **1** | `open Chrome` | `OPEN_APP` | `subprocess.Popen("chrome.exe")` | `verify_open_app` checks `psutil` active process list | **SIMULATED** | **REAL + VERIFIED** |
| **2** | `open YouTube` | `OPEN_WEBSITE` | `webbrowser.open("https://youtube.com")` | `verify_open_website` checks dictionary string lookup | **SIMULATED** | **REAL + UNVERIFIED** *(Fake verifier)* |
| **3** | `open Downloads` | `OPEN_FOLDER` | `os.startfile(".../Downloads")` | `verify_open_folder` checks folder existence on disk | **SIMULATED** | **REAL + UNVERIFIED** *(Fake verifier)* |
| **4** | `find my resume` | `FIND_FILE` | `os.scandir(...)` read-only disk scan | `verify_find_file` returns `NOT_APPLICABLE` | **REAL + UNVERIFIED** | **REAL + UNVERIFIED** |
| **5** | `search Python tutorials` | `SEARCH_WEB` | `DDGS().text(...)` DuckDuckGo API | `verify_search_web` checks query string non-emptiness | **SIMULATED** | **REAL + UNVERIFIED** *(Fake verifier)* |
| **6** | `open first result` | `OPEN_WEBSITE` | `webbrowser.open(first_url)` | `verify_open_website` checks domain whitelist string | **SIMULATED** / **FAILS** | **REAL + UNVERIFIED** / **FAILS** |
| **7** | `read it` | `READ_WEBSITE` | `requests.get(url)` HTTP GET fetch | No verifier in `_VERIFIER_TABLE` (`NOT_APPLICABLE`) | **SIMULATED** / **FAILS** | **REAL + UNVERIFIED** / **FAILS** |
| **8** | `stop` | `SYSTEM_STOP` | Internal state machine transition (`STOPPING`) | N/A (Global system command) | **REAL + VERIFIED** *(Control event)* | **REAL + VERIFIED** *(Control event)* |
| **9** | `cancel` | `SYSTEM_CANCEL` | Internal context & plan state reset (`CANCELLED`) | N/A (Global system command) | **REAL + VERIFIED** *(Control event)* | **REAL + VERIFIED** *(Control event)* |
| **10**| `forget a memory` | `FORGET` | `sqlite3 DELETE FROM memories` (requires 'yes') | No verifier in `_VERIFIER_TABLE` (`NOT_APPLICABLE`) | **BLOCKED** → **SIMULATED** | **BLOCKED** → **REAL + UNVERIFIED** |

---

## 5. Architectural Gaps & Recommendations for Phase 28.5

To achieve a true **VOICE → INTENT → SAFETY → EXECUTE → VERIFY → RESULT → TTS** guarantee across all actions, the following architectural gaps must be addressed:

### Gap 1: Fake & Missing Verifiers in `friday/verification/`
1. **`OPEN_WEBSITE`**: Replace registry dict check with process / window title inspection (checking if browser process is active) or lightweight HTTP HEAD/GET connectivity verification.
2. **`OPEN_FOLDER`**: Replace static `Path.exists()` check with Windows Explorer window handle / `psutil` process check (`explorer.exe`).
3. **`SEARCH_WEB`**: Upgrade string non-empty check to verify that `results` list returned non-empty payload containing valid titles & URLs.
4. **`READ_WEBSITE`**: Add `verify_read_website` to `_VERIFIER_TABLE` to verify non-empty readable text payload.
5. **`REMEMBER` / `RECALL` / `FORGET`**: Add memory verifiers to `_VERIFIER_TABLE` that perform post-execution SQLite queries (e.g. verifying `SELECT` after `DELETE` returns 0 rows).
6. **System Control Tools (`SET_VOLUME`, `MUTE_AUDIO`, `UNMUTE_AUDIO`, `PAUSE_MEDIA`)**: Add audio state verifiers to `_VERIFIER_TABLE`.

### Gap 2: Verification Failure Handling in Multi-Step Plans & Spoken Responses
- Currently, if verification returns `VerificationStatus.FAILED`, `execute_plan_step()` aborts the entire plan.
- The verification layer must distinguish between **hard execution failures** and **observational uncertainty** (e.g., browser tab opened but title check timed out) so valid user plans do not fail prematurely.

### Gap 3: Context Disambiguation Prompts
- When anaphoric resolutions (`"open first result"`, `"read it"`) fail due to missing context, the system currently returns a static error string. Adding a conversational clarification fallback (e.g., `"Which website would you like me to read?"`) will significantly improve daily usefulness.
