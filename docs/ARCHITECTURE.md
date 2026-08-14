# F.R.I.D.A.Y. System Architecture (v1.0.0)

F.R.I.D.A.Y. is a privacy-first, 100% offline desktop voice assistant built on a deterministic-first pipeline architecture.

---

## 1. End-to-End Execution Pipeline

```
Microphone Audio
       ↓
Silero VAD (ONNX)
       ↓
faster-whisper STT (small.en)
       ↓
Voice Session Manager
       ↓
Deterministic Router (< 0.25 ms regex & fuzzy phonetic matcher)
       ↓
Short-Term Anaphora & Context Resolver
       ↓
Reasoner Gating Filter (100% Ollama bypass for deterministic commands)
       ↓
Local Reasoner (Ollama llama3:latest - ONLY invoked for unstructured requests)
       ↓
JSON Schema Validator (Strict 5-key schema validation)
       ↓
Plan Validator (Upfront whole-plan validation)
       ↓
Centralized Permission Gate (dry_run & per-action permissions)
       ↓
Execution Engine & Post-Action Verifier (Typed ExecutionResult & VerificationResult)
       ↓
Spoken Response Formatting Engine
       ↓
Piper TTS Engine (with Hardware Async Barge-In)
```

---

## 2. Deterministic Gating Rationale

### Why Deterministic Gating Before LLM Reasoning?
1. **Performance**: Deterministic regex matching resolves known commands in `< 0.25 ms`, compared to 1,500 - 3,000 ms for LLM generation.
2. **Predictability**: Prevents LLM hallucinations on common desktop commands (`"Open Chrome"`, `"What time is it?"`).
3. **Security**: Bypasses prompt injection surfaces for structured desktop intents.
4. **Efficiency**: Saves GPU/CPU compute resources for complex open-ended user queries.
