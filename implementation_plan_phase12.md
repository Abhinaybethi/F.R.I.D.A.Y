# Phase 12 — Interaction Quality & Performance
## Implementation Plan

---

## 1. Executive Summary & Measured Bottleneck

### Current Architecture Pipeline
```
Microphone Stream -> Silero VAD -> faster-whisper STT -> ConversationManager ->
[Deterministic Router (~0.20ms) / Planner (~0.62ms)] -> (Fallback: Ollama reasoner ~9.4s) ->
Plan Validation -> Safety Policy & Confirmation -> Permission Gate -> Tool Execution ->
Post-Action Verification -> Structured Audit Log -> Piper TTS Synthesis -> User
```

### Empirical Latency Benchmark (Phase 11 Measurements)
- **Deterministic Router**: `0.20 ms`
- **Multi-Step Planner**: `0.62 ms`
- **Warm Single Utterance**: `0.30 ms`
- **Warm Multi-Step Plan**: `1.24 ms`
- **Ollama Fallback Reasoner**: `9453.26 ms (~9.4s)`

### Primary Objective
The bottleneck is **100% concentrated in the local reasoning fallback (~9.4s)**. Deterministic routing and plan execution complete in `< 1.5 ms`.
Phase 12 will:
1. Gate the reasoner so unnecessary transcripts NEVER trigger LLM reasoning.
2. Optimize Ollama generation latency (`"format": "json"`, `"num_predict": 128`, `"keep_alive": "30m"`).
3. Implement a deterministic `friday/response/` engine for natural spoken output without raw dicts or `[DRY RUN]` spoken text.
4. Refine conversation UX state handling (`yes`, `no`, `cancel`, `stop`, `repeat`, `help`).
5. Prove performance & security invariants via comprehensive regression suites.

---

## 2. Reasoner Gating Strategy (Increment 1)

Create `friday/reasoning/gating.py` (`should_call_reasoner(transcript, intent, context)`).

### Reasoner Gating Decision Matrix

| Transcript | Deterministic Intent | Reasoner Called? | Reason |
|---|---|---|---|
| `"open chrome"` | `OPEN_APP` | **NO** | Deterministic match |
| `"open youtube"` | `OPEN_WEBSITE` | **NO** | Deterministic match |
| `"what time is it"` | `GET_TIME` | **NO** | Deterministic match |
| `"search for python tutorials"` | `SEARCH_WEB` | **NO** | Deterministic match |
| `"open downloads"` | `OPEN_FOLDER` | **NO** | Deterministic match |
| `"close chrome"` | `CLOSE_APP` | **NO** | Deterministic match |
| `"help"` / `"repeat"` / `"cancel"` / `"stop"` | System Handler | **NO** | Intercepted deterministically |
| `"yes"` / `"no"` (outside confirmation) | `UNKNOWN` | **NO** | Intercepted deterministically |
| Bare noise / single character | `UNKNOWN` | **NO** | Length < 2 chars / noise |
| `"what is the capital of Japan"` | `UNKNOWN` | **YES** | General knowledge query |
| `"explain recursion"` | `UNKNOWN` | **YES** | Natural language explanation request |
| `"tell me a joke"` | `UNKNOWN` | **YES** | Conversational prompt |

---

## 3. Reasoner Latency Optimization (Increment 2)

Optimize `OllamaReasoner.request()` payload parameters in `friday/reasoning/local_reasoner.py`:
- `"format": "json"`: Enforces native Ollama constrained JSON decoding, causing generation to stop as soon as JSON completes.
- `"num_predict": 128`: Restricts max token generation to 128 tokens, eliminating runaway text generation.
- `"keep_alive": "30m"`: Prevents Ollama from unloading the model from VRAM between queries.
- Measure cold vs warm generation latency before and after optimization.

---

## 4. Deterministic Response Engine (Increment 3)

Create `friday/response/engine.py` (`format_spoken_response(action_outcome, is_dry_run)`):
- Converts structured `ActionOutcome` / `ExecutionResult` / `VerificationResult` / `Intent` into clean, human-like spoken text.
- **Spoken Text Rules**:
  - `OPEN_APP(chrome)` verified -> `"Opening Chrome."`
  - `OPEN_APP(chrome)` verification failed -> `"I couldn't confirm that Chrome opened."`
  - `OPEN_WEBSITE(youtube)` -> `"Opening YouTube."`
  - `SEARCH_WEB(python tutorials)` -> `"Searching for Python tutorials."`
  - `GET_TIME` -> `"It's 3:30 PM."`
  - `CLOSE_APP` prompt -> `"Are you sure you want to close Chrome?"`
  - Unknown / unhandled -> `"I didn't understand that."`
- **Forbidden in Spoken Output**:
  - NO `[DRY RUN]` spoken text
  - NO raw Python dictionaries `{...}`
  - NO internal policy/permission error codes
  - NO stack trace snippets

---

## 5. Voice Flow Optimization (Increment 4)

Inspect and refine audio session lifecycle in `friday/voice/`:
- Ensure VAD audio chunking operates with zero unnecessary buffer allocations.
- Ensure STT transcription calls operate on pre-allocated buffers.
- Ensure Piper TTS synthesis is non-blocking to conversation event loop.
- Preserve full user speech interruption support.

---

## 6. Conversation UX Refinement (Increment 5)

Refine state machine handling in `friday/core/conversation.py`:
- `"yes"` outside confirmation -> Returns `"I didn't understand that."` without calling Ollama.
- `"yes"` during confirmation -> Executes pending intent.
- `"no"` during confirmation -> Cancels pending intent & returns `"Cancelled."`.
- `"cancel"` -> Clears current plan/intent & returns `"Cancelled."`.
- `"stop"` -> Immediately halts execution & returns `"Goodbye."`.
- `"repeat"` -> Speaks exact previous response.

---

## 7. Incremental Implementation Plan

### Increment 1: Reasoner Gating Engine
- Create `friday/reasoning/gating.py` and integrate into `ConversationManager`.
- Create `tests/test_reasoner_gating.py`.
- Verification: `pytest tests/test_reasoner_gating.py`.

### Increment 2: Reasoner Latency Optimization
- Update `OllamaReasoner.request()` with `"format": "json"`, `"num_predict": 128`, `"keep_alive": "30m"`.
- Measure latency via `scripts/benchmark_e2e_performance.py`.
- Verification: Benchmark script shows reduced LLM generation latency.

### Increment 3: Deterministic Response Engine
- Create `friday/response/engine.py` and `friday/response/__init__.py`.
- Create `tests/test_response_engine.py`.
- Verification: `pytest tests/test_response_engine.py`.

### Increment 4: Voice Response Flow Optimization
- Audit & refine audio pipeline buffering in `friday/voice/`.
- Create `tests/test_voice_flow.py`.
- Verification: `pytest tests/test_voice_flow.py`.

### Increment 5: Conversation UX Refinement
- Update `ConversationManager` state handlers for `yes`, `no`, `cancel`, `stop`, `repeat`, `help`.
- Create `tests/test_conversation_ux.py`.
- Verification: `pytest tests/test_conversation_ux.py`.

### Increment 6: Performance Regression & Benchmark Suite
- Create `tests/test_phase12_performance.py` tracking zero Ollama calls for known commands and measuring latency.
- Verification: `pytest tests/test_phase12_performance.py`.

### Increment 7: Security & Safety Invariants Audit
- Create `tests/test_phase12_security.py` verifying safety gates, permissions, confirmation, verification, zero shell=True/os.system/eval/exec.
- Create `tests/test_phase12_gate.py` implementing 20-point Phase 12 Gate test.
- Verification: `pytest tests/test_phase12_gate.py` & full regression suite.

---

## 8. Proposed Files Created / Modified

### [NEW] `friday/reasoning/gating.py`
### [NEW] `friday/response/engine.py`
### [NEW] `friday/response/__init__.py`
### [MODIFY] `friday/reasoning/local_reasoner.py`
### [MODIFY] `friday/core/conversation.py`
### [NEW] `tests/test_reasoner_gating.py`
### [NEW] `tests/test_response_engine.py`
### [NEW] `tests/test_voice_flow.py`
### [NEW] `tests/test_conversation_ux.py`
### [NEW] `tests/test_phase12_performance.py`
### [NEW] `tests/test_phase12_security.py`
### [NEW] `tests/test_phase12_gate.py`
