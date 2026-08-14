# F.R.I.D.A.Y. v1.0.0 Release Notes

**Release Date**: August 14, 2026  
**Status**: Release Candidate (RC1)

---

## 🌟 What is F.R.I.D.A.Y.?

F.R.I.D.A.Y. is a **100% offline, privacy-first desktop voice assistant** for Windows. It provides fast deterministic command handling, natural offline speech synthesis, local voice activity detection, and local LLM reasoning.

---

## 🚀 Key Capabilities

- **100% Offline & Private Voice Pipeline**:
  - Speech Recognition via `faster-whisper` (`small.en`).
  - Voice Activity Detection via `Silero VAD` (ONNX).
  - Speech Synthesis via `Piper TTS` (`en_US-lessac-low`).
  - Local LLM Reasoning via `Ollama` (`llama3:latest`).
- **Sub-Millisecond Command Processing**:
  - Deterministic router resolves commands in `< 0.25 ms`.
  - 100% Ollama bypass for known commands.
- **Hardware Async Barge-In**:
  - Halts TTS output in `~50 ms` when user speech is detected.
- **Anaphora & Search Result Context**:
  - Contextually resolves pronouns ("close it") and search result URLs ("open the first result").
- **Native Desktop Controls**:
  - Minimizing/maximizing app windows, screenshots, time lookup, application launch/close.
- **Fail-Closed Security Architecture**:
  - `dry_run: true` and `allow_real_execution: false` locked safety defaults.
  - Zero `shell=True`, zero `os.system`, zero `eval` or `exec`.

---

## 🔧 Installation & Verification

```powershell
# Setup environment
.\scripts\setup_windows.ps1

# Run diagnostics
python main.py --diagnostics

# Run release smoke test
python scripts/release_smoke_test.py

# Launch Friday
python main.py
```

---

## 📋 System Requirements

- Windows 10 / 11 (64-bit)
- Python 3.10+
- Ollama service running at `http://localhost:11434`
