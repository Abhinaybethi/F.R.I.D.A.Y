# F.R.I.D.A.Y. Phase 21 Product Audit

## 1. Executive Summary
Phase 20 successfully expanded F.R.I.D.A.Y. from a pure local pipeline into a more capable assistant with memory, file retrieval, barge-in, and web reading. However, this deep audit reveals that these new capabilities suffer from severe integration and continuity gaps. The primary conclusion is that while individual tools work perfectly in isolation, multi-turn "research" workflows break down across contextual boundaries. Phase 21 must address these P0 and P1 integration gaps to make the assistant reliable for real-world tasks without compromising the strict local-only security boundaries.

## 2. Current Architecture
- **Voice I/O**: VAD (Silero) -> STT (faster-whisper) -> TTS (Piper/Kokoro)
- **Routing**: Deterministic intent matcher (Regex) with a local Ollama reasoning fallback.
- **Tools**: Sandboxed tool registry strictly requiring `allow_real_execution: true` and `dry_run: false`.
- **Memory**: SQLite-based persistent storage (`memory.db`), purely explicit via natural language intents.
- **Context**: 5-turn rolling list of intents and transcripts.

## 3. Phase 20 Capability Audit
The Phase 20 features were successfully merged and tested, but the audit reveals they were built as independent silos. 
- Memory operations are explicit but lack deletion confirmation.
- Context is tracked but fails to bind external states (like browser tabs) to the conversation.
- Web reading is bounded but prone to SSRF and hallucination loops.

## 4. Memory Audit
- **SQLite Persistence**: Working, stored in `.data/memory.db`. Thread safety is handled naively via short-lived connections.
- **REMEMBER / RECALL**: Functional, but `REMEMBER` allows infinite exact duplicates.
- **FORGET**: **DANGEROUS.** A naive regex match deletes the first memory containing the keyword without asking for explicit confirmation.
- **Stale Memories**: No expiration or TTL exists.
- **Security**: Basic regex prevents storing static API keys, but is brittle.

## 5. Context Audit
- **5-Turn Limit**: Works as designed.
- **Anaphora Resolution**: Works for local files because `FIND_FILE` injects the resolved path into the context. However, it completely breaks for web searches.
- **Context Bleed**: Context is maintained globally per session, meaning rapid topic changes might cause accidental cross-contamination.

## 6. Web Research Audit
- **SEARCH_WEB**: Simply invokes `os.startfile` to open Google in the user's GUI browser. F.R.I.D.A.Y. has zero knowledge of the search results. 
- **OPEN_WEBSITE**: Works for known registry sites.
- **READ_WEBSITE**: 10s timeout, 2MB streaming limit, BeautifulSoup text extraction, 2000 character truncation.
- **Critical Flaw**: The workflow "Search X" -> "Read the first result" is physically impossible because F.R.I.D.A.Y. does not intercept search result DOMs.
- **Security Flaw (SSRF)**: `requests.get` allows reading `http://localhost:11434` or internal router IPs if the user injects an internal IP as a URL.

## 7. File Retrieval Audit
- **Constraints**: Safely bounded to `Downloads`, `Documents`, and `Desktop` with a max depth of 3.
- **Ranking**: Effectively grabs the most recently modified matching file.
- **Security**: `os.startfile` is used, which is generally safe when constrained to validated paths, but directory traversal payloads like `../../../Windows/System32` must be aggressively sanitized before the file search begins.

## 8. Barge-In Audit
- **TTS Interruption**: VAD triggers `abort_event`, halting Piper playback cleanly.
- **State Recovery**: The state machine recovers smoothly back to `LISTENING`.
- **Race Conditions**: If VAD triggers the abort event mere milliseconds before `speak()` clears it during initialization, the TTS will fail to abort.

## 9. Reasoning Gate Audit
- **Deterministic vs LLM**: The router correctly catches most standard intents.
- **Unnecessary Invocations**: Because the web search lacks structured output, users asking follow-up questions about browser tabs will unnecessarily force Ollama to hallucinate an answer.

## 10. Structured Response Audit
- **String Replacements**: While Phase 19 removed most string hacks, an audit of `text_to_speech.py` reveals that `re.sub(r"https?://[^\s]+", "the website", text)` is STILL present, modifying executor outputs right before playback.

## 11. State Machine Audit
- **Synchronous Execution**: The `EXECUTING` state blocks the main thread. If a tool hangs (e.g., SQLite lock), the entire system freezes.
- **Stale Confirmations**: If a user is prompted for confirmation, and says something unrelated, the confirmation state drops without resetting the context properly.

## 12. Failure Recovery Audit
- **Closed-Failing**: `read_website` catches `requests.Timeout` but catches other connection errors via a generic `Exception`.
- **Hardware Failures**: Missing microphone crashes the loop instead of entering a graceful degraded state.

## 13. Security Audit
- `shell=True`, `eval()`, `exec()`: **NOT FOUND.** (PASS)
- **SQLite**: No SQL injection (parameterized queries used). (PASS)
- **Arbitrary URL Access (SSRF)**: `requests.get` does not block local/private IP ranges. (FAIL)
- **Path Traversal**: File search does not explicitly strip `../` before joining paths. (FAIL)

## 14. Real-World Workflow Traces

### WORKFLOW 1: "Search Python tutorials" -> "Open the first result"
1. Transcript: "Search Python tutorials"
2. Router: `SEARCH_WEB` -> target "Python tutorials"
3. Execution: `webbrowser.open("https://google.com/search?q=Python+tutorials")`
4. Context: Records `SEARCH_WEB`
5. Transcript: "Open the first result"
6. Router: Falls through to Ollama.
7. Reasoner: Hallucinates a URL or fails because it cannot see the user's screen.
8. **Result**: BROKEN BOUNDARY.

### WORKFLOW 2: "Forget my name"
1. Transcript: "Forget my name"
2. Router: `FORGET` -> target "my name"
3. Execution: `memory.py` finds the first memory containing "my", "name" and DELETEs it instantly.
4. **Result**: DANGEROUS DELETION WITHOUT CONFIRMATION.

### WORKFLOW 3: Assistant speaking -> "Stop"
1. State: `RESPONDING` (Piper generating audio).
2. VAD: Detects speech.
3. Abort: `abort_event.set()` called.
4. TTS: Breaks playback loop.
5. State: Returns to `LISTENING`.
6. **Result**: SUCCESS.

## 15. Findings Ranked
**P0 (Correctness / Security Blockers)**
1. **SSRF Vulnerability**: `read_website` allows requesting internal LAN IPs and localhost.
2. **Destructive FORGET**: `FORGET` intent deletes memory without requiring WAITING_FOR_CONFIRMATION state.

**P1 (Major UX / Workflow Problems)**
1. **Blind Search Workflow**: `SEARCH_WEB` provides no context back to F.R.I.D.A.Y., making follow-up questions impossible.
2. **Path Traversal Risk**: `FIND_FILE` target string must aggressively strip directory traversal characters before scanning.
3. **Infinite Memory Duplicates**: `REMEMBER` allows the exact same string to be saved hundreds of times.

**P2 (Quality Improvements)**
1. **TTS String Hack**: Remove the URL regex hack in `text_to_speech.py` and move it to `formatter.py`.
2. **VAD Race Condition**: Ensure `abort_event` clears safely before VAD starts listening again.
3. **Database Locks**: SQLite needs proper timeout handling for high-concurrency environments.

## 16. Recommended Phase 21 Scope
Phase 21 should strictly fix the identified P0 and P1 gaps to make the Phase 20 capabilities actually usable and secure.
1. Patch SSRF and Path Traversal vulnerabilities (Security).
2. Enforce explicit confirmation for the `FORGET` action.
3. Prevent duplicate memories in the SQLite database.
4. Refactor `SEARCH_WEB` to use a headless search API (like DuckDuckGo via the existing `duckduckgo-search` requirement) to inject top result URLs into context so "Read the first result" actually works.

## 17. Explicit Non-Goals
- Do NOT add a vector database.
- Do NOT add cloud LLMs.
- Do NOT implement autonomous browser controlling agents (Selenium/Playwright).
