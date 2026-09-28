# Phase 17 — Personal Assistant Productization & Daily-Use Validation
## Implementation Plan & Verification Matrix

---

## 1. Goal & Product Vision

Transform F.R.I.D.A.Y. from a well-tested voice engine into a polished, reliable **Personal Local AI Voice Assistant** for Windows daily use.

### Core Principles & Safety Invariants
- **Safety Defaults**: `dry_run: true` and `allow_real_execution: false` in `config.yaml` MUST remain active.
- **Zero Cloud APIs**: 100% offline local voice processing (faster-whisper, Silero VAD, Piper TTS, local Ollama LLM).
- **Zero Dangerous Shell Access**: Zero `shell=True`, zero `os.system`, zero `eval` or `exec`.

---

## 2. Productization Increments

### Increment 1: Canonical Application Entrypoint (`main.py` / `friday/__main__.py`)
- Standardize canonical startup path (`python main.py` or `python -m friday`).
- Fail-closed startup sequence: Validate config -> diagnostics -> audio -> STT -> TTS -> reasoner -> tools -> session -> READY status.

### Increment 2: Clean User-Facing Startup Experience
- Display concise user-facing startup status:
  ```
  ----------------------------------------
  F.R.I.D.A.Y.
  Personal Local AI Voice Assistant
  ----------------------------------------
  [OK] Microphone
  [OK] VAD
  [OK] Speech recognition
  [OK] Voice synthesis
  [OK] Local reasoning

  F.R.I.D.A.Y. is ready.
  Listening...
  ```
- Keep detailed debug logs in `logs/friday.log`.

### Increment 3: Structured Configuration System (`config.yaml`)
- Organize `config.yaml` into explicit sections (`security`, `runtime`, `voice`, `reasoning`, `ui`).
- Maintain strict fail-closed config validation (`validate_config()`).

### Increment 4: User-Friendly Voice Listening Loop
- Debounce background noise & short silence fragments.
- Prevent repetitive `"I didn't understand that."` audio responses for background noise or empty STT fragments.

### Increment 5: Conversational UX & Natural Spoken Responses
- Ensure all spoken responses are natural, concise, and understandable.
- Never expose internal dry-run tags, confidence floats, raw JSON, or stack traces in speech.

### Increment 6: Robust Session Lifecycle & Start/Stop/Restart Safety
- Enforce clean transitions across `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `WAITING_FOR_CONFIRMATION`, `PAUSED`, `STOPPING`.
- Support multiple start -> stop -> restart cycles without leaking audio streams or background threads.

### Increment 7: System Tray Productization (`friday/ui/tray.py`)
- Support tray tooltips (`"F.R.I.D.A.Y. - [LISTENING]"`) and tray state icon filenames (`icon_listening.ico`, `icon_busy.ico`, `icon_idle.ico`, `icon_paused.ico`).

### Increment 8: Listening Pause / Resume Mechanism
- Implement `pause_listening()` and `resume_listening()` without destroying active audio engine objects.

### Increment 9: Windows Environment & Setup Script (`scripts/setup_windows.ps1`)
- PowerShell setup script verifying Python, setting up virtualenv, installing dependencies, checking local models, and verifying Ollama.

### Increment 10: CLI Diagnostics Command (`python main.py --diagnostics`)
- Provide `--diagnostics` CLI flag printing system component health and locked security policy status.

### Increment 11: Real Daily-Use Validation (`PHASE_17_DAILY_USE_REPORT.md`)
- Record physical daily-use session transcripts across basic control, fuzzy speech, confirmation, context, barge-in, and recovery.

### Increment 12: True Voice Latency Audit
- Audit physical latency: `speech_end -> STT_final -> response_ready -> TTS_start`.

### Increment 13: Resource Lifecycle Restart Test (`scripts/test_restart_cycles.py`)
- Run 10 consecutive start -> stop -> restart cycles; verify zero accumulating memory or orphan threads.

### Increment 14: Clean Release Repository Structure
- Audit `.gitignore`, `.env.example`, and `README.md` to ensure zero machine-specific absolute paths or secrets.

### Increment 15: Security & Policy Final Audit
- Perform security scan verifying zero dangerous execution tokens in active codebase.

### Increment 16: Phase 17 Certification Gate (`tests/test_phase17_gate.py`) & Product Scorecard (`PHASE_17_PRODUCT_SCORECARD.md`)
- Implement 20-point Phase 17 Release Certification Gate.
- Run full repository regression suite (`pytest tests/`).

---

## 3. Verification & Exit Criteria Matrix

| Exit Criteria Metric | Baseline | Target | Measurement Method |
|---|---|---|---|
| **Canonical Startup Success** | Operational | `100%` | `python main.py` |
| **CLI Diagnostics Output** | Working | `100%` | `python main.py --diagnostics` |
| **Barge-In Interruption Latency** | `50.0 ms` | `< 200 ms` | `scripts/benchmark_barge_in.py` |
| **Deterministic Voice Latency** | `0.65 ms` | `< 800 ms` | `scripts/benchmark_voice_pipeline.py` |
| **10-Cycle Restart Cleanup** | Clean | `0 leaks` | `scripts/test_restart_cycles.py` |
| **Zero Dangerous Execution Tokens** | `0` | `0` | `tests/test_phase17_gate.py` |
| **Full System Regression Suite** | `421 / 421 PASS` | `421 / 421 PASS` | `pytest tests/` |
