# PHASE 28 — F.R.I.D.A.Y. v1.1 DEEP PRODUCT & ARCHITECTURE AUDIT

## Executive Summary

Following the successful certification of F.R.I.D.A.Y. v1.1.0 (`612/612` test suite pass rate, zero memory leaks, and verified CI green status), this Phase 28 audit conducts a comprehensive evaluation of the v1.1.0 codebase across product capabilities, daily-driver workflow weaknesses, architectural debt, testing gaps, security boundaries, voice UX limitations, and performance bottlenecks.

This audit establishes a data-driven, evidence-backed roadmap for Phase 28. All recommendations are ranked by priority (**P0: Critical Architecture & Security**, **P1: Major Reliability & Voice UX**, **P2: Usability & Control Enhancements**) and strictly adhere to repository safety constraints (`dry_run=True` and `allow_real_execution=False` defaults preserved; zero production code modified during audit).

---

## 1. Baseline Capabilities (What F.R.I.D.A.Y. Reliably Does Today)

F.R.I.D.A.Y. v1.1.0 delivers a robust, 100% local, privacy-first desktop voice assistant baseline:

1. **Deterministic Fast-Path Routing (< 1 ms P50)**:
   - Regex and fuzzy phonetic matching for 13 core desktop actions: `OPEN_APP`, `CLOSE_APP`, `OPEN_WEBSITE`, `READ_WEBSITE`, `SEARCH_WEB`, `GET_TIME`, `FIND_FILE`, `OPEN_FILE`, `OPEN_FOLDER`, `MINIMIZE_APP`, `MAXIMIZE_APP`, `TAKE_SCREENSHOT`, `MEMORY_REMEMBER`, `MEMORY_RECALL`, `MEMORY_FORGET`.
2. **Fail-Closed Dual-Gate Security Model**:
   - Locked safety defaults: `security.dry_run = True` and `security.allow_real_execution = False`.
   - Destructive actions (e.g. `CLOSE_APP`) enforce a `Policy.CONFIRM` gate requiring explicit user confirmation.
3. **Hands-Free Local Audio & Barge-In Pipeline**:
   - PyAudio 16kHz capture, Silero VAD ONNX speech boundary detection, `faster-whisper` (`small.en` CPU int8) STT, Piper ONNX (`en_US-lessac-low`) TTS, and `sounddevice` playback with hardware barge-in interruption (`< 50 ms` latency).
4. **Cold-Start Model Pre-Warming**:
   - Asynchronous background session initialization (`tts.warmup()`) reduces initial-turn synthesis delay from `~2.7s` to `~2.0s` and keeps warm-turn execution at `~300ms`.
5. **Cross-Session SQLite Persistence**:
   - Preference and memory store (`.data/memory.db`) with key-value resolution and secret filtering across process restarts.
6. **Multi-Step & Anaphora Context Resolution**:
   - Ordinal search indexing ("open the first result"), pronoun resolution ("read it"), and compound command splitting ("open Chrome and search Python").

---

## 2. Daily-User Workflow Weaknesses & Fake Behaviors

| Subsystem / Workflow | Current Implementation & Behavior | Usability & Functional Limitation | Evidence File Location |
| :--- | :--- | :--- | :--- |
| **Web Reading (`READ_WEBSITE`)** | Simple `requests.get()` and `BeautifulSoup` text extraction. | Fails on JavaScript Single-Page Applications (React/Next.js/Vue), paywalled content, or login-gated sites; returns empty or raw HTML boilerplate. | [browser.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/browser.py#L42-L80) |
| **App Closing (`CLOSE_APP`)** | Force kills process via PowerShell `Stop-Process -Name <target>`. | Ungraceful termination causes loss of unsaved document state, browser tab session loss, and crashing notifications. | [apps.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/apps.py#L85-L120) |
| **Window Management (`MINIMIZE_APP` / `MAXIMIZE_APP`)** | PowerShell Win32 `ShowWindow` matched by process name. | Fails on multi-window setups, tabbed windows, or Electron apps (VS Code, Discord, Slack) where window titles differ from executable names. | [desktop.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/desktop.py#L15-L60) |
| **Intervening Turn Context Loss** | Rolling context history (`history` list in `ConversationContext`). | Intervening queries ("what time is it") overwrite `last_search_results` or displace context, breaking subsequent ordinal commands ("open the second result"). | [conversation.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py#L56-L80) |
| **Audio & Media Controls** | Missing native intents. | Everyday voice controls ("mute audio", "set volume to 50%", "pause music") are absent from deterministic intent routing. | [router.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py#L15-L90) |

---

## 3. Architectural Debt Accumulated Across Phases 20–27

1. **Permission Parameter Propagation Bug in `ConversationManager`**:
   - **Code Evidence**: In [conversation.py:L538](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py#L538), the standard single-turn SAFE execution path calls:
     ```python
     result = registry.execute(intent, dry_run=self.dry_run, allow_real_execution=self.allow_real_execution)
     ```
     Notice `permissions=self.permissions` is **omitted**. While `permissions` is passed in confirmation resume (L281) and correction retry (L328), custom permission policies passed to `ConversationManager` are ignored during standard single-turn execution.
2. **Unstructured Tool Messaging & String Scrubbing Hack**:
   - **Code Evidence**: `text_to_speech.py` relies on `_clean_for_speech` with regex and string replacements (`text.replace("Would open folder: ", "Opening folder ")`). Tools return raw execution messages intended for CLI rather than a structured contract separating spoken speech from console text.
3. **Zombie Confirmation State Machine**:
   - **Code Evidence**: In [conversation.py:L259](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py#L259), a 30s timeout check exists, but it only evaluates when a *new* user transcript arrives. If the user stops speaking after a confirmation prompt, `StateMachine` remains stuck in `WAITING_FOR_CONFIRMATION` indefinitely.
4. **Splintered Intent Routing & Conversational Penalty**:
   - **Code Evidence**: Intent resolution is fragmented across `router.py`, `fuzzy_router.py`, `normalizer.py`, and `gating.py`. Natural framing ("can you please open Chrome", "hey Friday find my resume") fails regex matching and falls back to Ollama, causing an unnecessary 2000ms+ latency penalty.

---

## 4. Reliability Gaps Uncovered

1. **Audio Device Disconnection & Underflow**:
   - No unit/integration tests simulate PyAudio stream loss, microphone unplugging, or audio endpoint switching mid-session.
2. **Unbounded Ollama Reasoner Blocking**:
   - `OllamaReasoner.request()` in [local_reasoner.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/reasoning/local_reasoner.py#L40-L85) lacks an explicit HTTP socket timeout. If Ollama hangs or stalls during LLM fallback, the main thread blocks indefinitely.
3. **Barge-In Concurrent Thread Race Conditions**:
   - `AsyncSessionManager` handles audio playback and mic listening on separate threads. Simultaneous barge-in cancellation during TTS playback completion lacks mock thread-safety test coverage.

---

## 5. Security & Privacy Gaps

1. **Incomplete Personal Sensitive Data Scrubbing in Memory**:
   - `friday/tools/memory.py` filters common API keys (`sk-`, `ghp_`), but does not filter credit card numbers, SSNs, or auth tokens embedded in URLs before persistent SQLite storage.
2. **Unsanitized URL Scheme Whitelisting**:
   - `open_website` passes targets to `webbrowser.open(target)`. Targets are not strictly validated against an allowed protocol whitelist (`http://`, `https://`), risking execution of local file URIs (`file:///`) or custom URI handlers.

---

## 6. Voice UX Limitations

1. **Monolithic (Non-Streaming) TTS Synthesis**:
   - `speak_piper` synthesizes entire text blocks into a single WAV buffer before starting playback. For long responses (>30 words), synthesis latency creates a 1.5s–3.0s delay before audio starts.
2. **Lack of Audio Feedback Earcons (Chimes)**:
   - The system provides no audio cues for wake word detection, processing, or completion, forcing reliance on visual console output.
3. **Acoustic Noise / VAD False Triggers**:
   - Background noise or breath sounds trigger Silero VAD, feeding silent audio to Whisper, resulting in hallucinated STT text (e.g. "Thank you for watching.").

---

## 7. Performance Bottlenecks

1. **CPU-Bound Synchronous ONNX Synthesis**:
   - Piper ONNX inference is single-threaded and synchronous on CPU.
2. **Conversational Framing LLM Fallback Overhead**:
   - Phrasing like "can you please open Chrome" falls back to Ollama, jumping latency from `< 1 ms` to `1500–3000 ms`.
3. **Full Table Scans for Memory Queries**:
   - SQL queries in `friday/tools/memory.py` scan `memories` table without explicit topic/key indexes.

---

## 8. Prioritized Work Plan (P0 / P1 / P2)

### P0: Safety, Permission & Architecture Integrity (Must Fix First)
- **P0.1**: Fix Permission Parameter Propagation Bug in [conversation.py:L538](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py#L538) by passing `permissions=self.permissions` to `registry.execute()`.
- **P0.2**: Fix Zombie Confirmation State Machine by introducing a passive timeout reset in `StateMachine` to auto-revert to `IDLE`/`LISTENING` after 30s of inactivity.
- **P0.3**: Restrict `open_website` URL schemes to strictly `http://` and `https://` to prevent local file or custom URI injection.

### P1: Major Reliability & Voice UX Polish
- **P1.1**: Broaden deterministic intent regex in [router.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py#L20-L80) to strip conversational framing ("can you please", "could you", "i want to", "hey Friday"), eliminating unnecessary 2s+ Ollama fallbacks.
- **P1.2**: Implement structured response contract (`spoken_message` vs `display_message`) in tool outcomes, removing regex string scrubbing from `text_to_speech.py`.
- **P1.3**: Add a 3.0s request timeout to `OllamaReasoner.request()` to prevent main thread deadlocks when the local LLM is unresponsive.
- **P1.4**: Update `close_app` in `apps.py` to attempt Win32 `WM_CLOSE` before falling back to forced process termination.

### P2: Voice Usability & System Control Enhancements
- **P2.1**: Add native deterministic voice intents for `SET_VOLUME`, `MUTE_AUDIO`, `UNMUTE_AUDIO`, and `PAUSE_MEDIA`.
- **P2.2**: Integrate optional audio earcons (chimes) for speech listening and action completion.
- **P2.3**: Expand secret scrubbing regex in `memory.py` to filter SSNs, credit card numbers, and authorization headers before SQLite storage.

---

## 9. Conclusion & Next Steps

This audit provides a comprehensive, evidence-backed evaluation of F.R.I.D.A.Y. v1.1.0. All proposed work items address verified gaps without feature creep or safety default modifications. Implementation will commence upon user review and approval of `implementation_plan_phase28.md`.
