# F.R.I.D.A.Y. Clean Environment Installation Guide

This document describes the step-by-step procedure for installing and verifying F.R.I.D.A.Y. v1.0.0 on a fresh Windows 10/11 system.

---

## 1. System Requirements

- **Operating System**: Windows 10 / Windows 11 (64-bit)
- **Python**: Python 3.10, 3.11, or 3.12 (64-bit)
- **RAM**: Minimum 8 GB (16 GB recommended)
- **Disk Space**: ~4 GB for Python virtual environment and local model assets
- **Ollama**: Installed from [ollama.com](https://ollama.com)

---

## 2. Automated Installation

Open PowerShell as your normal user in the project root directory:

```powershell
.\scripts\setup_windows.ps1
```

The script will:
1. Verify Python version.
2. Create virtual environment `venv`.
3. Install Python dependencies from `requirements.txt`.
4. Verify/download local voice model files (`models/vad/silero_vad.onnx`, `models/tts/piper/`).
5. Verify Ollama server connectivity at `http://localhost:11434`.
6. Run health diagnostics (`python main.py --diagnostics`).

---

## 3. Post-Installation Verification

Run the automated release smoke test:

```powershell
python scripts/release_smoke_test.py
```

Expected output: `ALL RELEASE SMOKE TESTS PASSED (100% READY)`.

---

## 4. First Run

Start F.R.I.D.A.Y.:

```powershell
python main.py
```
