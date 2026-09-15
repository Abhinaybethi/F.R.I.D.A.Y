# F.R.I.D.A.Y. v2 — Phase Next Real-World Test Plan
**Document Status**: APPROVED TEST PLAN  
**Target Environment**: Windows 10/11 Host, Physical Process Table, SQLite, Live Network, Sounddevice Audio  
**Safety Invariants**: `dry_run=False`, `allow_real_execution=True` explicitly enabled for stress harness; release tag immutable.

---

## 1. Overview & Verification Philosophy

This test plan validates F.R.I.D.A.Y. v2 across real Windows OS, physical audio hardware, live network endpoints, and local SQLite storage.

### Core Testing Mandate
Every executed action is validated via **Independent External Observation**:
- **Process Actions (`OPEN_APP`, `CLOSE_APP`)**: Verified by querying the Windows OS process table (`psutil.process_iter`) for exact process names and PID transitions.
- **Web Actions (`OPEN_WEBSITE`, `SEARCH_WEB`, `READ_WEBSITE`)**: Verified by observing active browser processes, live DuckDuckGo API/HTML responses, and HTTP GET status codes with parsed body content.
- **Filesystem Actions (`OPEN_FOLDER`, `FIND_FILE`, `OPEN_FILE`)**: Verified by filesystem existence checks (`Path.exists()`), safe directory boundaries, and read permissions.
- **Memory Actions (`REMEMBER`, `RECALL`, `FORGET`)**: Verified by independent fresh SQLite database read queries against `memories` table on disk.
- **Hardware & Voice Actions (`SYSTEM_STOP`, `BARGE_IN`)**: Verified by monitoring audio stream playback abortion and VAD signal transitions.

---

## 2. Critical Workflows Matrix (Workflows A through J)

| Workflow | Scenario Description | Interaction Sequence | Expected External State & Side Effect |
|---|---|---|---|
| **Workflow A** | Basic App Control & Idempotency | 1. `open Chrome`<br>2. `open Chrome`<br>3. `close Chrome` | 1. Chrome process appears in process table.<br>2. No duplicate Chrome instance spawned.<br>3. Chrome process terminated cleanly. |
| **Workflow B** | Website Navigation & Back | 1. `open YouTube`<br>2. `open Google`<br>3. `go back` | 1. Browser launches with YouTube URL.<br>2. Navigation occurs to Google.<br>3. Back navigation handled where supported. |
| **Workflow C** | Search $\to$ Result $\to$ Read $\to$ Alternate $\to$ Correction | 1. `search Python tutorials`<br>2. `open the first result`<br>3. `read it`<br>4. `open the second result`<br>5. `no, the third one` | 1. Real DDG search with stable result IDs (`result_1`..`3`).<br>2. Browser opens exact first URL.<br>3. HTTP GET parses $< 2000$ chars.<br>4. Second URL opened via ordinal.<br>5. Corrected target resolves to 3rd result. |
| **Workflow D** | Memory Lifecycle | 1. `remember my editor is VS Code`<br>2. `what's my editor?`<br>3. `update my editor to PyCharm`<br>4. `what's my editor?`<br>5. `forget my editor` $\to$ `No`<br>6. `forget my editor` $\to$ `Yes`<br>7. `what's my editor?` | 1. SQLite row inserted.<br>2. Fresh DB read returns VS Code.<br>3. Row updated (0 duplicate rows).<br>4. Fresh DB read returns PyCharm.<br>5. NO: 0 side effects (row persists).<br>6. YES: row deleted from disk.<br>7. Returns not found (0 stale cache). |
| **Workflow E** | Confirmation Gate Safety | Destructive actions (`FORGET`, etc.) with repeated NO/YES | NO: Zero side effects, zero DB changes.<br>YES: Exactly 1 side effect verified by fresh DB query. |
| **Workflow F** | Hardware Interruption / Barge-In | Live Piper TTS playback interrupted by VAD signal | Active sounddevice stream aborts instantly; `abort_event` clears; next command processed with 0 state leak. |
| **Workflow G** | Failure Recovery | 10 Failure Scenarios:<br>1. Invalid app<br>2. Missing file<br>3. Unavailable browser<br>4. Invalid URL<br>5. Empty search<br>6. Network timeout<br>7. STT failure<br>8. TTS failure<br>9. Cancelled confirmation<br>10. Interrupted goal | Conversational notice returned; zero crash; state cleanly resets to `LISTENING`; immediate next command accepted. |
| **Workflow H** | Context Retention & Multi-Turn | `search Python tutorials` $\to$ `open first result` $\to$ `read it` $\to$ `find another one` $\to$ `open the second result` $\to$ `no, the third one` | Search cache retained across turns; ordinal indexing maps accurately; corrections update target cleanly. |
| **Workflow I** | Multi-Command Input | `open Chrome and search Python tutorials` | Sequential execution: Step 1 verified $\to$ Step 2 executes with context from Step 1. If Step 1 fails, Step 2 halts. |
| **Workflow J** | Stop & Global Session Reset | Active goal $\to$ `stop` $\to$ immediate `open Notepad` | Ephemeral goal context, pending intents, and history purged; Notepad opens with zero state leak. |

---

## 3. Allocation of Deterministic Real-World Trials

Total Target: **180+ Real Trials**

| Command / Test Category | Target Action | Minimum Trials | Verification Method |
|---|---|---|---|
| `open Chrome` | `OPEN_APP` | 10 | `psutil` process table inspect |
| `open YouTube` | `OPEN_WEBSITE` | 10 | Process inspect + URL validation |
| `open Downloads` | `OPEN_FOLDER` | 10 | Directory existence + explorer process |
| `find my resume` | `FIND_FILE` | 10 | Disk traversal & path validation |
| `search Python tutorials` | `SEARCH_WEB` | 10 | Live DDG query + non-empty payload |
| `open first result` | `OPEN_WEBSITE` | 5 | Ordinal resolution from search context |
| `read it` | `READ_WEBSITE` | 5 | Live HTTP GET & BeautifulSoup parse |
| `remember my editor is VS Code` | `REMEMBER` | 10 | Fresh SQLite `SELECT` query |
| `recall my editor` | `RECALL` | 10 | Fresh SQLite independent read |
| `update my editor to PyCharm` | `REMEMBER` | 10 | Fresh SQLite `SELECT` query |
| `recall my editor` | `RECALL` | 10 | Fresh SQLite independent read |
| `forget my editor` (Pending) | `FORGET` | 5 | Confirmation gate state verification |
| `cancel` | `SYSTEM_CANCEL` | 5 | Context purge & zero side effect |
| `confirmation NO` | `CONFIRMATION_NO` | 5 | Verification of 0 side effects |
| `confirmation YES` | `CONFIRMATION_YES` | 5 | Verification of physical row deletion |
| `open VS Code` | `OPEN_APP` | 10 | Process table inspect (`Code.exe`) |
| `open Notepad` | `OPEN_APP` | 10 | Process table inspect (`notepad.exe`) |
| `search Python internships` | `SEARCH_WEB` | 10 | Live DDG query + non-empty payload |
| `read the first result` | `READ_WEBSITE` | 5 | Live HTTP GET & BeautifulSoup parse |
| `stop speaking` | `SYSTEM_STOP` | 5 | Sounddevice stream termination |
| `barge-in interruption` | `BARGE_IN` | 10 | Audio playback abort benchmark |
| `open invalid application` | `RECOVERY` | 5 | Graceful failure notice & recovery |

---

## 4. Telemetry Schema Specification (24 Fields)

Every trial record appended to `.data/real_world_telemetry.json` must record:
1. `trial_id`: Integer
2. `timestamp`: ISO-8601 UTC
3. `session_id`: UUID
4. `command`: User input string
5. `transcript`: STT transcript
6. `intent`: Action enum string
7. `intent_confidence`: Float [0.0 - 1.0]
8. `target`: Entity target string
9. `target_confidence`: Float [0.0 - 1.0]
10. `plan`: Structured plan or null
11. `goal_id`: UUID
12. `tool`: Tool registry function path
13. `execution_started`: Timestamp float
14. `execution_completed`: Timestamp float
15. `execution_result`: Dict (status, message, raw payload)
16. `verification_result`: Dict (status, evidence)
17. `verification_evidence`: Descriptive evidence string
18. `spoken_response`: User-facing TTS message
19. `latency_ms`: Total execution & verification latency
20. `error`: Error message or null
21. `failure_classification`: Enum string or null
22. `recovery_result`: `SUCCESS` / `FAILED`
23. `external_state_before`: Observational state pre-action
24. `external_state_after`: Observational state post-action
