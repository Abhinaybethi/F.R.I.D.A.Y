# F.R.I.D.A.Y. v1.1 Data-Driven Backlog

## P0: Safety / Release Blockers
*None currently identified. v1.0.0 safety defaults (`dry_run=True`) successfully prevent catastrophic execution.*

## P1: Major Reliability & Observability Problems
### 1. End-to-End Request Correlation (Observability)
- **Evidence**: `logger.py` uses a basic formatter. `task-83` and log reviews show interleaved STT/TTS logs without request IDs.
- **Current behavior**: Cannot trace a failure (e.g., STT output -> Router decision -> Execution) without manually correlating timestamps.
- **Desired behavior**: Every VAD activation generates a unique `request_id`. This ID is passed through STT, Router, Planner, and TTS, appearing in every log line.
- **Affected subsystem**: `logger.py`, `conversation.py`, `speech_to_text.py`.
- **Implementation complexity**: Medium.

### 2. Unnecessary Ollama Invocation (Latency / Reliability)
- **Evidence**: `router.py` uses rigid regex (e.g., `^close\s+(.+)$`). "can you close chrome" fails the regex and falls back to Ollama.
- **Current behavior**: Simple variations of deterministic commands incur a 2000ms+ Ollama penalty.
- **Desired behavior**: Expand deterministic regex/fuzzy routing to catch common conversational prefixes ("can you", "please", "could you") before hitting the LLM.
- **Affected subsystem**: `intent/router.py`.
- **Implementation complexity**: Low.

### 3. TTS String-Replacement Hack (Hidden Coupling)
- **Evidence**: `text_to_speech.py` contains `_clean_for_speech` which does `text.replace("Would open folder: ", "Opening folder ")`.
- **Current behavior**: Tool execution outputs text meant for CLI/dry-run, and TTS manually scrubs it using hardcoded string matching.
- **Desired behavior**: Tools return a structured response (e.g., `DisplayMessage`, `SpokenMessage`) so TTS doesn't have to parse text.
- **Affected subsystem**: `tools/registry.py`, `voice/text_to_speech.py`.
- **Implementation complexity**: Medium.

## P2: Meaningful UX / Performance Issues
### 4. Lack of Conversation State Timeout
- **Evidence**: `StateMachine` in `conversation.py` waits in `WAITING_FOR_CONFIRMATION` indefinitely.
- **Current behavior**: If a user ignores a confirmation prompt, the next command (hours later) is treated as a yes/no response.
- **Desired behavior**: Context and confirmation states should expire after ~15-30 seconds, returning to `IDLE`.
- **Affected subsystem**: `core/conversation.py`, `core/state.py`.
- **Implementation complexity**: Medium.

### 5. Verification Race Conditions
- **Evidence**: `validate_plan` and `registry.execute` run synchronously. Apps take time to launch.
- **Current behavior**: Verification runs immediately after `subprocess.Popen`. If the app takes 500ms to open a window, verification fails.
- **Desired behavior**: Implement a retry/polling mechanism in verification (e.g., check every 100ms for up to 2s).
- **Affected subsystem**: `planning/executor.py`, `tools/apps.py`.
- **Implementation complexity**: Medium.

## P3: Enhancements
### 6. Streaming TTS / Chunked Audio
- **Evidence**: `speak_piper` synthesizes the entire audio file to a `BytesIO` buffer before playback begins.
- **Current behavior**: Long responses (e.g., >20 words) cause a noticeable delay before the first word is spoken.
- **Desired behavior**: Stream audio chunks to `sounddevice` as they are synthesized.
- **Affected subsystem**: `voice/text_to_speech.py`.
- **Implementation complexity**: High.
