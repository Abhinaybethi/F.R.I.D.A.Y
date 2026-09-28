# F.R.I.D.A.Y. Phase 21 Implementation Plan

## Architecture Goal
Phase 21 focuses exclusively on integration quality, workflow continuity, and strict security boundaries. The architecture will not introduce new intent categories or agents, but will harden the boundaries of the Phase 20 capabilities to ensure they function reliably in multi-turn scenarios.

## Increments

### Increment 1: Security Hardening (P0 & P1)
- **SSRF Prevention**: Block local IPs, loopback, and private LAN ranges in `browser.py`'s `read_website` using IP address parsing and validation.
- **Path Traversal Prevention**: Sanitize target queries in `files.py` (`find_file`, `open_file`, `open_folder`) to strictly block `../`, `..\`, and absolute path injection.
- **FORGET Confirmation**: Update `friday/intent/router.py` to route `Action.FORGET` with `requires_confirmation=True`.

### Increment 2: Memory Deduplication (P1)
- **Duplicate Prevention**: Update `friday/tools/memory.py` to check for exact string matches before performing an `INSERT`. Return a specific response if the memory already exists.

### Increment 3: Context-Aware Web Search (P1)
- **Headless Search Integration**: Currently `SEARCH_WEB` opens a browser, blinding F.R.I.D.A.Y. to the results. We will implement headless search via the existing `duckduckgo-search` library to retrieve the top 3 results.
- **Contextual Injection**: The search results (Titles + URLs) will be appended to the output message so they are captured by the `ConversationContext`.
- **Anaphora Synergy**: This enables subsequent commands like "Open the first result" or "Read the second link" to successfully resolve via the deterministic or Ollama context resolvers.

## Exact Files to Modify
1. `friday/tools/browser.py`
   - Modify `read_website` to add an SSRF check before requesting.
   - Modify `search_web` to use `duckduckgo-search` and return structured URL lists instead of blindly calling `os.startfile`.
2. `friday/tools/files.py`
   - Add aggressive path traversal sanitization to target extraction.
3. `friday/intent/router.py`
   - Change `FORGET` intent confidence to force `requires_confirmation = True`.
4. `friday/tools/memory.py`
   - Add uniqueness constraints/checks in `remember()`.
5. `tests/test_phase21_security.py` [NEW]
   - Add SSRF and Path Traversal unit tests.
6. `tests/test_phase21_memory.py` [NEW]
   - Add tests for duplicate memory rejection and `FORGET` confirmation.
7. `tests/test_phase21_search.py` [NEW]
   - Add tests for the context-aware duckduckgo search output.

## Test Strategy
- **Unit Tests**: Mock `requests.get` to test SSRF filtering logic. Mock SQLite to test duplicate insertion blocks.
- **Integration Tests**: Simulate the router pipeline to verify `FORGET` yields `requires_confirmation=True`.
- **Workflow Simulation**: Manually trace "Search Python tutorials" -> "Read the first result" using test stubs.

## Security Gates
- **Gate 21.1 - Zero SSRF**: `read_website` must reliably block `localhost`, `127.0.0.1`, `10.x.x.x`, `192.168.x.x`, `172.16.x.x`.
- **Gate 21.2 - Zero Path Traversal**: `find_file` must safely drop inputs attempting `../../`.
- **Gate 21.3 - Safe Defaults Maintained**: `allow_real_execution` remains false; `dry_run` remains true.

## Regression Strategy
Run the full 484-test regression suite after each increment. Any failure blocks the increment. No string replacements or fragile test patching will be accepted without analyzing the architectural root cause.

## Acceptance Criteria
1. SSRF payloads on `read_website` return a blocked failure.
2. Path traversal payloads on `find_file` return a blocked failure.
3. "Forget my name" asks for confirmation before deleting SQLite rows.
4. "Remember the sky is blue" (called twice) results in only one DB row.
5. "Search for X" returns top links into the conversational context, allowing "Open the first result" to successfully target a real URL.
6. Local regression tests remain 100% green.
