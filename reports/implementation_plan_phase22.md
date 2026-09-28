# Implementation Plan — Phase 22: Personal Assistant Workflow Intelligence

Phase 22 transforms F.R.I.D.A.Y. from a turn-by-turn command listener into an intelligent, context-aware personal assistant. It adds entity & reference resolution ("it", "that", "second result"), active memory integration, goal-state re-planning on failure, and conversational correction handling.

## Proposed Changes

### Component 1: Context & Entity Resolution Engine
#### [MODIFY] [context_resolver.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/planning/context_resolver.py)
- Replace rigid string comparison for `"open the first result"` with a general `EntityResolver`.
- Index entities in `ShortTermContext`:
  - `search_results`: List of indexed items (`#1`, `#2`, `#3`, ...).
  - `recent_files`: Last found/opened file path (`it`, `that`, `file`).
  - `recent_apps`: Last opened/closed app (`it`, `app`).
  - `recent_urls`: Last read/opened website URL (`it`, `website`, `url`).
- Support ordinal references (`first`, `second`, `third`, `last`, `1st`, `2nd`, `3rd`).
- Support generic pronoun resolution (`"read it"`, `"open that"`, `"save it"`).

### Component 2: Active Memory & Personalization System
#### [MODIFY] [memory.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/memory.py)
- Upgrade SQLite schema in `.data/memory.db`:
  - Add `category` (e.g., `preference`, `credential`, `general`), `confidence` (REAL default 1.0), `key_name` (NULLABLE), `updated_at` (TIMESTAMP).
- Add `resolve_preference(key: str) -> Optional[str]` helper.
- Update `remember()` to support key-value updating (e.g. updating "my favorite browser is Chrome" updates existing key instead of creating duplicate).
#### [MODIFY] [router.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py)
- Intercept preference requests during parameter resolution (e.g., "open my favorite browser" resolves target using memory preference).

### Component 3: Goal Re-Planning & Failure Recovery
#### [MODIFY] [plan_models.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/planning/plan_models.py)
- Add `fallbacks: dict[int, list[Intent]]` to `ActionPlan` to store candidate recovery steps if primary step fails.
#### [MODIFY] [executor.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/planning/executor.py)
- On step failure, check if fallback candidate exists before setting `PlanState.FAILED`.
- Return `requires_user_guidance: True` with spoken message: `"Step X failed. Would you like me to try Y instead?"`.

### Component 4: Conversational State & Correction Handler
#### [MODIFY] [conversation.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py)
- Add `CORRECTION` intent handler for transcripts like `"no, I meant Chrome"` or `"instead open Firefox"`.
- Undo/close previous turn target if applicable and re-route with corrected target.
- Bind `EntityResolver` and active memory queries into `_get_short_term_context()`.

---

## Verification Plan

### Automated Tests
- `tests/test_phase22_entity_resolution.py`: Unit tests for ordinal references (#1..#N), pronouns ("it", "that"), search result selection, and multi-turn reference tracking.
- `tests/test_phase22_active_memory.py`: Tests for category schema, key-value memory updates, conflict resolution, and preference resolution during routing.
- `tests/test_phase22_goal_recovery.py`: Tests for multi-step failure recovery, fallback candidates, and step re-planning.
- `tests/test_phase22_correction.py`: Tests for intent correction ("no, I meant X") and alias learning.
- `python -m pytest`: Full regression suite run (all 531 existing + new Phase 22 tests must pass).

### Security Gates & Safety Defaults
- Preserve `dry_run=True` as default for `ConversationManager` and all tool executions.
- Preserve `allow_real_execution=False` safety default.
- Re-run `scripts/security_scan.py` to confirm 0 danger patterns (`shell=True`, `eval`, `exec`, `os.system`).
- Verify SSRF checks, path traversal sanitization, and FORGET confirmation gates remain 100% active.

### Performance Targets
- Entity and reference resolution latency: `< 1.0 ms` (deterministic, zero Ollama calls).
- Preference lookup latency from local SQLite: `< 2.0 ms`.
- Overall transcript handling latency for known commands + entity references: `< 10.0 ms`.
