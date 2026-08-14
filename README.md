# F.R.I.D.A.Y. — Personal AI Voice Assistant

A 100% offline, privacy-first desktop voice assistant for Windows. Grounded in local speech-to-text (faster-whisper), local voice activity detection (Silero VAD), local speech synthesis (Piper TTS), and local reasoning (Ollama `llama3`).

---

## Key Features

- **100% Offline & Private**: Zero cloud API dependencies, zero external data tracking.
- **Fail-Closed Security Architecture**:
  - `dry_run: true` (default dry-run simulation mode)
  - `allow_real_execution: false` (requires explicit dual-gate opt-in for real OS execution)
- **Sub-Millisecond Core Processing**: Regex router, fuzzy phonetic matcher, and context resolver run in `< 0.25 ms`.
- **Sub-100ms Hardware Barge-In**: User speech interrupts TTS audio output in `~50 ms`.
- **Anaphora & Search Result Context**: Resolves pronouns ("close it") and search result indexing ("open the first result").

---

## Quick Start

### 1. Setup Environment (Windows PowerShell)

```powershell
.\scripts\setup_windows.ps1
```

Or manually:

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py --download-models
```

### 2. Run Diagnostics

Verify system readiness and security policy locks:

```powershell
python main.py --diagnostics
```

### 3. Run F.R.I.D.A.Y.

```powershell
python main.py
```

---

## Canonical Usage & Voice Commands

| Voice Command | Action Taken |
|---|---|
| `"Open Chrome"` / `"Open Notepad"` | Launches application |
| `"Close Chrome"` | Requests confirmation, then closes app |
| `"Open grove"` | Fuzzy phonetic recovery -> resolves to `chrome` |
| `"Search Python tutorials"` | Searches web for topic |
| `"Open the first result"` | Contextually opens indexed search URL |
| `"What time is it?"` | Speaks current time |
| `"Minimize Chrome"` / `"Maximize Chrome"` | Native Windows window control |
| `"Take screenshot"` | Desktop screenshot capture |
| `"Cancel"` | Clears pending intent/confirmation |
| `"Stop"` / `"Goodbye"` | Clean session shutdown |

---

## Security Policy Defaults (`config.yaml`)

```yaml
security:
  dry_run: true
  allow_real_execution: false

tools:
  dry_run: true
  allow_real_execution: false
  permissions:
    open_app: true
    close_app: true
    open_folder: true
    open_website: true
    search_web: true
    get_time: true
    find_file: true
    open_file: true
    minimize_app: true
    maximize_app: true
    take_screenshot: true
```

---

## Architecture Overview

```
Microphone Audio -> Silero VAD -> faster-whisper STT
  -> Deterministic & Fuzzy Phonetic Router (< 0.25 ms)
  -> Context & Anaphora Resolver
  -> Reasoner Gating (100% Ollama bypass for known commands)
  -> Safety & Plan Validator
  -> Centralized Permission Gate
  -> Executer & Post-Action Verifier
  -> Spoken Response Formatting Engine
  -> Piper TTS Synthesis (with Async Hardware Barge-In)
```

---

## License

MIT License. Grounded in open-source local models.
