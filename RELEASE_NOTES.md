# F.R.I.D.A.Y. v1.1.0 Release Notes

**Release Date**: August 15, 2026
**Status**: Release Candidate (v1.1.0 RC)

---

## 🌟 What's New in v1.1.0?

F.R.I.D.A.Y. v1.1.0 is a major reliability, latency, and usability release grounded in 100% offline, local-first execution for Windows.

---

## 🚀 Key Improvements & Benchmarks

### 1. Phase 25 Long-Run Reliability Certified
- **100/100 Voice Commands PASS**: Sustained multi-turn voice session validated on real Windows hardware.
- **Zero Resource Leaks**: `0` RAM leaks (stabilized at ~242 MB), `0` thread leaks (constant at 18 threads), `0` SQLite leaks, `0` audio handle leaks.
- **Latency Performance**: Core intent router P50 = `0.28 ms` | P95 = `7.35 ms`.

### 2. Phase 26 Background Model Pre-Warming
- **Cold-Start Latency Outlier Resolved**: Background model pre-warming (`tts.warmup()`) pre-loads Piper ONNX sessions during startup.
- Initial turn latency reduced by **`22.2%`**, completely eliminating first-turn speech stalls.

### 3. Memory UX & Preference Overwrite Polish
- Specific spoken feedback when overwriting existing preference memory keys (e.g. `"Updated your editor preference."`).

### 4. Multi-Step Compound Commands
- Native parsing and step-by-step execution of compound voice commands (e.g. `"open Chrome and search Python tutorials"`).

### 5. Fail-Closed Security & Safety Architecture
- **Security Scan**: `CLEAN` (0 `shell=True`, 0 `os.system`, 0 `eval`/`exec`, 0 hardcoded secrets).
- **Locked Safety Defaults**: `dry_run: true` and `allow_real_execution: false`.

### 6. 100% Test Regression Pass Rate
- **612 / 612 PASS** across all unit, integration, and physical voice pipeline tests.

---

## 🔧 Quick Start & Diagnostics

```powershell
# Setup environment
.\scripts\setup_windows.ps1

# Run system diagnostics
python main.py --diagnostics

# Run full regression suite
python -m pytest -q

# Launch Friday
python main.py
```

---

## 📋 System Requirements

- Windows 10 / 11 (64-bit)
- Python 3.10+
- Ollama service running at `http://localhost:11434`
