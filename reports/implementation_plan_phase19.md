# Implementation Plan: Phase 19 (Evidence-Driven Foundation for v1.1)

## 1. Findings & Evidence
Following a comprehensive audit of F.R.I.D.A.Y. v1.0.0, the following critical architectural flaws were identified:

1. **Zero Observability (Hidden Failures)**: There is no correlation ID linking the voice pipeline. If a command fails, logs show interleaved STT and Reasoner lines, making debugging impossible.
2. **Hidden Coupling in UX**: The `_clean_for_speech` function in `text_to_speech.py` uses hardcoded `string.replace()` calls to strip `[DRY RUN]` and rewrite tool outputs (e.g., `"Would open"` -> `"Opening"`). This violates separation of concerns.
3. **Unnecessary Latency Spikes (Brittle Routing)**: `router.py` uses overly strict regex. Natural phrasing like "can you open chrome" falls through to Ollama, turning a 5ms deterministic route into a 2000ms+ inference delay.
4. **Stale Confirmation State**: `ConversationManager` waits indefinitely in `WAITING_FOR_CONFIRMATION`. A command given hours later will be misinterpreted as a confirmation response.

## 2. Recommended Fixes

### Fix A: Request Correlation (Observability)
- **Action**: Introduce a `ContextVar` or unique `request_id` generated at the VAD/STT boundary.
- **Changes**: Update `logger.py` to inject the `request_id` into all log lines via a custom `logging.Filter`.

### Fix B: Decouple TTS from Tool Output (Architecture)
- **Action**: Refactor tool execution to return structured responses containing both a `log_message` (for the console/UI) and a `spoken_message` (for TTS).
- **Changes**: Modify `ExecutionResult` (or the dict returned by `registry.execute`) and remove the `_clean_for_speech` hacks from `text_to_speech.py`.

### Fix C: Expand Deterministic Router (Latency)
- **Action**: Update `_PATTERNS` in `router.py` to strip conversational prefixes ("can you", "please", "could you") *before* matching, drastically reducing Ollama invocations for simple commands.
- **Changes**: Add a normalization step in `intent/normalizer.py` or `router.py`.

### Fix D: State Machine TTL (UX)
- **Action**: Implement a timestamp-based expiration for `WAITING_FOR_CONFIRMATION`.
- **Changes**: Update `handle_transcript` in `conversation.py` to check if `time.time() - context.last_interaction_time > 30` and reset to `LISTENING` if expired.

## 3. Files Affected
- `friday/utils/logger.py`
- `friday/voice/speech_to_text.py`
- `friday/voice/text_to_speech.py`
- `friday/intent/router.py`
- `friday/core/conversation.py`
- `friday/tools/registry.py`

## 4. Risk Assessment & Rollback
- **Risk**: Low/Medium. These are structural improvements to logging, routing, and text formatting. No new dangerous capabilities are introduced. `dry_run` remains enforced.
- **Test Strategy**: Run the full regression suite (`pytest`). Write targeted unit tests for the conversation TTL and router prefix normalization.
- **Rollback Strategy**: Git revert the Phase 19 branch. All changes are confined to stateless modules (except Conversation Context TTL, which resets safely on restart).

> [!IMPORTANT]
> **Approval Required**: Do not proceed with code modifications until this plan is reviewed and approved by the Lead Architect (USER).
