# F.R.I.D.A.Y. v2 — Phase 30.5 Forensic Baseline & Architecture Audit
**Document Status**: COMPLETED AUDIT (Pre-Implementation Baseline)  
**Target Repository**: `F.R.I.D.A.Y v2` (Base Release: `v1.1.0`)  
**Safety Invariants**: `dry_run=True`, `allow_real_execution=False` default config preserved; no cloud LLMs; `v1.1.0` tag immutable.

---

## 1. Executive Summary & Objective

The objective of Phase 30.5 is to close the verification gap between:
$$\text{"Python/tool test passes"}\quad\Longleftrightarrow\quad\text{"A real human speaks to F.R.I.D.A.Y. and Windows physically performs the action"}$$

Previous testing cycles achieved high passing rates in unit and synthetic test suites while manual execution occasionally revealed friction points (e.g., confirmation state handling, process termination synchronization, STT transcription normalizations, rate-limiting on rapid sequential searches).

This forensic baseline establishes the true production pipeline, audits the actual entry points, categorizes all existing test assets by evidence strength, identifies why virtual tests passed while real workflows could fail, and specifies minimal, evidence-backed fixes.

---

## 2. Production Pipeline Trace (Phase 1 & Phase 2)

### A. The Authoritative Production Path

When a user runs `python main.py`, the exact execution flow is:

```
[ PHYSICAL MICROPHONE ] (16 kHz 16-bit Mono via sounddevice/PyAudio)
         │
         ▼
[ AudioInput.read_chunks() ] (friday/voice/audio_input.py)
         │
         ▼
[ VoiceActivityDetector.is_speech() ] (friday/voice/vad.py — Silero VAD ONNX)
         │
         ▼ (Speech Start → Stream Chunk Accumulation → Silence Timeout)
[ SpeechToText.transcribe() ] (friday/voice/speech_to_text.py — faster-whisper small.en)
         │
         ▼ Raw Transcript String (e.g., "open Chrome", "search Python tutorials")
[ Friday._handle() ] (friday/core/assistant.py)
         │
         ▼
[ ConversationManager.handle_transcript() ] (friday/core/conversation.py)
         │
         ├──► 1. Text Normalization: normalize() (friday/intent/normalizer.py)
         ├──► 2. Global System Commands (Stop, Cancel)
         ├──► 3. Pending Confirmation Evaluation (if state == WAITING_FOR_CONFIRMATION)
         ├──► 4. Short-Term Context Resolution: resolve_context() (anaphora, ordinals)
         ├──► 5. Multi-Step Planner: parse_plan() -> validate_plan() (if compound)
         ├──► 6. Intent Routing: route() (regex rules & fuzzy match)
         ├──► 7. Local Reasoner Gating: should_call_reasoner() -> Ollama (llama3)
         ├──► 8. Safety & Permission Validation: validate(intent) (Policy.SAFE/CONFIRM/REJECT)
         ├──► 9. Tool Registry Dispatch: registry.execute() (friday/tools/registry.py)
         │         │
         │         ▼ (Real Host Execution with dry_run=False, allow_real_execution=True)
         │         ┌─────────────────────────────────────────────────────────────┐
         │         │ • apps.py: Windows process launch / terminate (psutil)      │
         │         │ • browser.py: DuckDuckGo API / BeautifulSoup HTTP GET       │
         │         │ • files.py: scandir filesystem traversal / explorer.exe     │
         │         │ • memory.py: SQLite DB ACID CRUD (memories table)           │
         │         │ • system.py: sounddevice stream abort / volume control      │
         │         └──────────────────────────────┬──────────────────────────────┘
         │                                        │
         │                                        ▼
         ├──► 10. Independent Verification: verify_execution() (friday/verification/verifier.py)
         │          (Fresh, read-only observational queries against OS/DB/Net/Audio)
         ├──► 11. User Feedback Formatter: format_outcome() (spoken_message generation)
         └──► 12. Context Update: context.push_turn() (5-turn rolling history)
         │
         ▼ Spoken Response String
[ TextToSpeech.speak() ] (friday/voice/text_to_speech.py — Piper / Kokoro ONNX)
         │
         ▼ (Simultaneous Background Barge-In Monitoring via AsyncVoiceSessionManager)
[ PHYSICAL SPEAKER OUTPUT / SOUNDDEVICE AUDIO STREAM ]
         │
         ▼
[ Next Utterance: VoiceSessionManager.listen_once() ]
```

---

## 3. Test Evidence Hierarchy & Categorization

To ensure rigorous reporting without false equivalences, tests are classified into six distinct evidence tiers:

```
+-------------------------------------------------------------------------------------------------------+
| Evidence Tier               | Definition & Operational Reality                                        |
+-------------------------------------------------------------------------------------------------------+
| LEVEL 1: TRUE E2E VOICE     | Live physical microphone → VAD → STT → Orchestrator → OS → Physical TTS|
| LEVEL 2: RECORDED AUDIO E2E | Recorded human WAV audio → STT → Orchestrator → OS → Physical TTS       |
| LEVEL 3: E2E ORCHESTRATION  | Typed transcript string → Router → Safety → Real OS Execution → Verifier|
| LEVEL 4: REAL TOOL DIRECT   | Direct python function call (e.g. apps.open_app()), bypassing router    |
| LEVEL 5: SIMULATED / DRY-RUN| dry_run=True execution, returning simulated [DRY RUN] payloads          |
| LEVEL 6: MOCKED / SYNTHETIC | Mocked reasoners, mocked STT/TTS buffers, dummy return dictionaries     |
+-------------------------------------------------------------------------------------------------------+
```

### Classification of Repository Test Assets

| Test File | Primary Evidence Tier | What It Actually Tests | Touches OS / Net / DB / Audio? | Uses Mocks / Dry-Run? |
|---|---|---|---|---|
| `main.py --diagnostics` | Level 1 & 4 | Component initialization & health checks | Real mic, speaker, ONNX, Ollama | No mocks |
| `tests/test_phase_next_real_world.py` | Level 3 | Workflows A–J multi-turn interaction | Real Windows OS, Net, SQLite, TTS abort | `dry_run=False`, Real execution |
| `tests/test_phase30_workflows.py` | Level 3 | Multi-turn search, memory, recovery | Real DDG, SQLite, apps, context | `dry_run=False`, Real execution |
| `tests/test_phase29_5_real_world.py` | Level 3 | 20 Benchmark commands via `ConversationManager` | Real apps, browser, SQLite, files | `dry_run=False`, Real execution |
| `tests/test_real_browser.py` | Level 3 & 4 | URL validation, DDG text search, reading | Real browser process, HTTP GET, DNS | `dry_run=False` & `dry_run=True` |
| `tests/test_real_apps.py` | Level 4 | Direct `apps.open_app()` / `close_app()` | Real Windows process launch via psutil | `dry_run=False` |
| `tests/test_real_files.py` | Level 4 | Direct `files.find_file()` / `open_folder()`| Real NTFS user directories | `dry_run=False` |
| `tests/test_tts.py` | Level 1 & 4 | Piper TTS synthesis and playback stream | Real sounddevice audio output stream | No mocks |
| `tests/test_barge_in_hardware.py` | Level 1 & 4 | Real abort event signaling during audio | Sounddevice stream interruption | No mocks |
| `tests/test_vad_capture.py` | Level 1 & 4 | Silero VAD ONNX frame processing | Real audio chunks & speech detection | No mocks |
| `tests/test_real_reasoning.py` | Level 3 | Local Ollama reasoner invocation | Live local Ollama (llama3:latest) | Skips if Ollama offline |
| `tests/test_verification.py` | Level 4 & 5 | Action verifiers logic & edge cases | Process table, SQLite, URL checks | Tests both dry-run & real |
| `tests/test_phase29_real_action_certification.py` | Level 5 | Certification matrix | None (Pure string assertions) | `dry_run=True` |
| `scripts/benchmark_voice_pipeline.py` | Level 6 | Latency benchmark | None | `dry_run=True`, `MockReasoner` |

---

## 4. Root-Cause Analysis: Why Virtual Tests Passed While Real Workflows Failed

| Root Cause & Gap | Pytest / Virtual Test Behavior | Real-World Production Failure |
|---|---|---|
| **1. String Input vs. Acoustic STT Variation** | Tests pass perfect text strings (e.g. `"search Python tutorials"`). | Real STT may transcribe `"what's my editor?"` as `"what is my editor"`, or include punctuation/capitalization that failed rigid regexes before normalization. |
| **2. Direct Tool Call vs. Safety Gate Enforcement** | Direct tool tests (Level 4) call `apps.close_app()` directly, which succeeds immediately. | Through production `ConversationManager`, `close_app` triggers `Policy.CONFIRM`, requiring a `"yes"` turn before execution. |
| **3. Process Termination Race Conditions** | Tests asserted `proc.terminate()` returned without error. | On Windows, `proc.terminate()` is asynchronous; immediate post-verification detected the process still in the table before OS fully terminated it. |
| **4. Third-Party Search Rate-Limiting** | Single isolated search tests pass. | Sequential multi-turn workflows (search $\to$ open $\to$ read $\to$ search) hit DuckDuckGo HTTP 429 rate limits unless cached. |
| **5. State Machine Post-Stop Lock** | Tests initialize a fresh `ConversationManager` per test case. | In real interactive use, issuing `"stop"` placed state in `STOPPING`; the next command threw an `InvalidStateTransition` unless auto-recovered to `LISTENING`. |

---

## 5. Identified Production Fixes & Implementation Plan for Phase 30.5

### Production Fixes Implemented & Verified
1. **State Machine Recovery from `STOPPING`** ([`friday/core/conversation.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/core/conversation.py)):
   - Automatically transitions `STOPPING -> IDLE -> LISTENING` upon receiving any subsequent non-stop command.
2. **Synchronous Process Termination** ([`friday/tools/apps.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/apps.py)):
   - Added `proc.wait(timeout=0.5)` with `proc.kill()` fallback in `close_app()` to ensure process table reflects termination before verifier runs.
3. **Natural Question Memory Recall Regexes** ([`friday/intent/router.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py)):
   - Added `"what is my"`, `"what is the"`, `"whats my"`, `"what's my"` patterns to route directly to SQLite memory recall.
4. **Search Caching & Stable Result IDs** ([`friday/tools/browser.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/browser.py)):
   - Added 60s in-memory TTL caching and stable `result_1`, `result_2`, `result_3` structured result IDs.
5. **SSRF-Safe Public URL Opening** ([`friday/tools/browser.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/browser.py) & [`friday/verification/action_verifiers.py`](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/verification/action_verifiers.py)):
   - Allows validated public HTTP/HTTPS URLs resulting from search queries to open in browser with process verification.

### Phase 30.5 Implementation Artifacts Planned
- `tests/data/real_command_corpus.json`: Structured benchmark corpus containing natural acoustic/textual command variations.
- `docs/PHASE_30_5_REAL_E2E_TEST_PLAN.md`: Comprehensive test plan with Level 1, 2, and 3 test allocations.
- `scripts/phase30_5_real_e2e_campaign.py`: Telemetry campaign harness with all 35 structured interaction fields.
- `tests/test_phase30_5_real_e2e.py`: Automated test suite covering Workflows A through J and failure injection scenarios.
- `docs/PHASE_30_5_REAL_WORLD_REPORT.md` & `docs/PHASE_30_5_ACTION_SCORECARD.md`: Final evidence-based certification reports.
