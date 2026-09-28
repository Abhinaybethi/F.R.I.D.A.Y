# Implementation Plan - Phase 28 Architecture Hardening & Voice UX Polish

This plan addresses the technical debt, reliability gaps, voice UX limitations, and security boundaries identified in [PHASE_28_PRODUCT_AUDIT.md](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/docs/PHASE_28_PRODUCT_AUDIT.md).

All work is strictly scoped to hardening, reliability, and UX polish without introducing feature creep or altering safety defaults (`dry_run=True` and `allow_real_execution=False`).

---

## User Review Required

> [!IMPORTANT]
> - **Zero Production Code Changes**: No production code has been modified during the audit phase. Implementation will begin only after explicit approval of this plan.
> - **Preserved Safety Defaults**: All existing security constraints, permission checking, and dry-run locks will remain strictly active.

---

## Open Questions

- None. All proposed work items are grounded in direct code analysis of the v1.1.0 codebase.

---

## Proposed Changes

### P0: Architecture & Safety Core (Fix First)

#### [MODIFY] [conversation.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py)
- Pass `permissions=self.permissions` to `registry.execute(...)` on line 538 to ensure custom permission rules are honored across all execution paths.
- Add passive background state timeout check to `StateMachine` to auto-revert `WAITING_FOR_CONFIRMATION` to `IDLE`/`LISTENING` after 30 seconds of user inactivity.

#### [MODIFY] [browser.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/browser.py)
- Restrict `open_website` URL target validation to allow only `http://` and `https://` schemes, blocking local file (`file:///`) or custom URI protocol injection.

---

### P1: Major Reliability & Voice UX Polish

#### [MODIFY] [router.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py)
- Broaden deterministic intent regex rules to automatically strip conversational prefixes ("can you please", "could you", "i want to", "hey Friday"), resolving standard intents in `< 1 ms` and eliminating 2s+ Ollama fallbacks.

#### [MODIFY] [registry.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/registry.py) & [text_to_speech.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/voice/text_to_speech.py)
- Establish structured outcome message fields (`spoken_message` vs `display_message`) in tool results, removing brittle string replacement hacks (`_clean_for_speech`) from TTS.

#### [MODIFY] [local_reasoner.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/reasoning/local_reasoner.py)
- Add a strict 3.0s socket timeout to `OllamaReasoner.request()` to prevent main thread blocking when the local LLM is slow or unreachable.

#### [MODIFY] [apps.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/apps.py)
- Update `close_app` to attempt a graceful Win32 `WM_CLOSE` window signal before falling back to forced process termination (`Stop-Process`).

---

### P2: Usability & System Control Enhancements

#### [MODIFY] [system.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/system.py) & [router.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py)
- Add deterministic intents and tool handlers for `SET_VOLUME`, `MUTE_AUDIO`, `UNMUTE_AUDIO`, and `PAUSE_MEDIA`.

#### [MODIFY] [memory.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/memory.py)
- Expand secret scrubbing regex to filter SSNs, credit card patterns, and authorization headers before persistent SQLite storage.

---

## Verification Plan

### Automated Tests
- Run full regression suite:
  ```bash
  python -m pytest -q
  ```
- Run targeted new unit tests for:
  - Permission parameter propagation in single-turn execution.
  - Confirmation timeout auto-reset.
  - Conversational prefix stripping in router.
  - URL scheme whitelist validation.
  - Reasoner socket timeout handling.
- Run release smoke test:
  ```bash
  python scripts/release_smoke_test.py
  ```
- Run security scan:
  ```bash
  python scripts/security_scan.py
  ```

### Manual Verification
- Test natural phrasing ("can you please open Chrome") on real hardware to verify instant `< 1 ms` intent routing.
- Verify confirmation state auto-resets to `LISTENING` after 30 seconds of silence.
- Verify `open_website` rejects `file:///` URLs gracefully.
