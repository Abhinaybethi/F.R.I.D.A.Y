# Phase 28.5 Implementation Plan: Action Execution & Verification Hardening

## Goal & Scope

Upgrade the F.R.I.D.A.Y. action execution and verification pipeline so that every real action is independently and accurately verified, eliminating fake verifiers (static dictionary lookups) and adding missing verifiers across all supported actions.

---

## Proposed Changes

### Component 1: Action Verifiers Hardening (`friday/verification/action_verifiers.py` & `verifier.py`)

#### [MODIFY] [action_verifiers.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/verification/action_verifiers.py)
- **`verify_open_website`**: Upgrade from static dictionary lookup to real browser process inspection (`psutil` check for `chrome.exe`/`msedge.exe`/`firefox.exe`) or URL domain check.
- **`verify_open_folder`**: Upgrade from static `Path.exists()` check to `explorer.exe` process inspection.
- **`verify_search_web`**: Upgrade string non-empty check to verify non-empty search result payload (`results` list).
- **[NEW] `verify_read_website`**: Add real verifier checking for successful HTTP response and non-empty extracted text payload.
- **[NEW] `verify_remember` / `verify_forget` / `verify_recall`**: Add database state verifiers checking SQLite memory records after write/delete/read ops.
- **[NEW] `verify_system_audio`**: Add verifiers for volume, mute, unmute, and media pause.

#### [MODIFY] [verifier.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/verification/verifier.py)
- Register new verifiers in `_VERIFIER_TABLE` for `READ_WEBSITE`, `REMEMBER`, `RECALL`, `FORGET`, `SET_VOLUME`, `MUTE_AUDIO`, `UNMUTE_AUDIO`, `PAUSE_MEDIA`.

---

### Component 2: Execution & Verification Integration (`friday/tools/registry.py` & `friday/planning/executor.py`)

#### [MODIFY] [registry.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/registry.py)
- Ensure all tool dispatches pass raw tool outputs into `ExecutionResult.raw_tool_result` for verifier consumption.

#### [MODIFY] [executor.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/planning/executor.py)
- Handle verification result outcomes cleanly in multi-step plan steps without breaking valid execution on observational timeouts.

---

### Component 3: Phase 28.5 Verification Test Suite

#### [NEW] [test_phase28_5_verification.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/tests/test_phase28_5_verification.py)
- Unit and integration tests for all 10 benchmark commands under `dry_run=True` and `dry_run=False`.
- Validate that fake verifiers are replaced by real process/payload checks.
- Verify end-to-end classification correctness for `REAL + VERIFIED`, `SIMULATED`, `BLOCKED`, and `FAILS`.

---

## Verification Plan

### Automated Tests
- Run `python -m pytest tests/test_phase28_5_verification.py -v`
- Run full pytest regression suite: `python -m pytest --ignore=tests/test_real_reasoning.py -v`
- Run security scan: `python scripts/security_scan.py`
- Run release smoke test: `python scripts/release_smoke_test.py`
- Run `git diff --check`

### Manual Verification
- Verify clean git status and tag lock for `v1.1.0`.
