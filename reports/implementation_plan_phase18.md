# Phase 18 — Release Engineering, Distribution & Long-Term Maintainability
## Implementation Plan & Verification Matrix

---

## 1. Goal & Product Vision

Certify F.R.I.D.A.Y. **v1.0.0 Release Candidate** with reproducible release engineering, automated dependency checks, exportable JSON diagnostics, log rotation, security threat modeling, architecture documentation, pytest markers (unit/integration/hardware/security/release), CI workflow, update/uninstall tooling, release smoke test, and 20-point Phase 18 Release Gate.

### Core Safety Invariants & Release Rules
- **Safety Defaults**: `dry_run: true` and `allow_real_execution: false` in `config.yaml` MUST remain active and locked.
- **Zero Cloud APIs**: 100% offline local processing (faster-whisper, Silero VAD, Piper TTS, local Ollama LLM).
- **Zero Unsafe Code Execution**: Zero `shell=True`, zero `os.system`, zero `eval` or `exec`.

---

## 2. 20 Increments of Release Engineering

### Increment 1: Versioning (`__version__ = "1.0.0"`)
- Single authoritative version `1.0.0` in `friday/__init__.py`.
- Expose `python main.py --version` and `python -m friday --version` (returning `"F.R.I.D.A.Y. v1.0.0"`).

### Increment 2: Release Manifest (`release_manifest.json`)
- Machine-readable release manifest containing version, platform, supported model names, safety defaults, test suite metrics, release status. Zero personal machine paths or secrets.

### Increment 3: Dependency Locking & Verification
- Audit `requirements.txt` and create dependency verification checks in `friday/utils/dependency_checker.py`.

### Increment 4: Model Verification Command (`python main.py --models`)
- Add CLI flag `--models` printing exact status for STT (`faster-whisper small.en`), VAD (`Silero VAD`), TTS (`Piper en_US-lessac-low`), and Reasoning (`Ollama llama3:latest`).

### Increment 5: Setup, Update, and Uninstall Scripts (`scripts/`)
- `scripts/setup_windows.ps1`
- `scripts/update_windows.ps1`
- `scripts/uninstall_windows.ps1`

### Increment 6: Bounded Log Rotation (`logs/friday.log`)
- Log rotation in `friday/utils/logger.py` using standard `RotatingFileHandler` (max 5 MB x 3 backups). Zero transcript audio dumping.

### Increment 7: Exportable Machine-Readable Diagnostics (`python main.py --diagnostics --json`)
- CLI flag `--diagnostics --json` outputting structured JSON diagnostic payload. Zero personal paths or tokens.

### Increment 8: Graceful User-Facing Error Boundaries
- Catch uncaught exceptions at outer main loop, outputting user-friendly error banners directing users to `--diagnostics` without dumping raw stack traces unless debug mode is active.

### Increment 9: Safe Update & Config Migration
- Safe configuration loading preventing overwrite of existing user configuration keys.

### Increment 10: Release Smoke Test (`scripts/release_smoke_test.py`)
- Non-destructive automated smoke test verifying version, config, models, diagnostics, tool registry, reasoner, TTS, STT, and shutdown.

### Increment 11: Clean-Environment Validation Procedure
- Document exact fresh Windows installation procedure in `docs/CLEAN_INSTALL.md`.

### Increment 12: GitHub Release Quality (`README.md`)
- Comprehensive `README.md` documentation covering features, architecture, requirements, installation, model setup, Ollama setup, running, diagnostics, configuration, safety model, testing. Zero absolute machine paths.

### Increment 13: System Architecture Documentation (`docs/ARCHITECTURE.md`)
- Complete pipeline documentation from Mic -> VAD -> STT -> Router -> Planner -> Reasoner -> Safety -> Permissions -> Confirmation -> Tool -> Verifier -> Response -> TTS.

### Increment 14: Security Threat Model (`docs/SECURITY.md`)
- Comprehensive security threat model documenting prompt injection, speech hallucination, URL validation, permission gating, confirmation enforcement, and plan validation.

### Increment 15: Pytest Marker Organization (`pytest.ini`)
- Organize pytest markers (`unit`, `integration`, `hardware`, `ollama`, `release`, `security`) so `pytest -m unit` runs fast without hardware or Ollama dependencies.

### Increment 16: Continuous Integration Workflow (`.github/workflows/ci.yml`)
- GitHub Actions CI workflow running Python setup, dependency check, unit tests, security tests, and configuration validation.

### Increment 17: Release Notes (`RELEASE_NOTES.md`)
- Full release notes for F.R.I.D.A.Y. v1.0.0 summarizing capabilities, architecture, safety model, performance benchmarks, known limitations.

### Increment 18: Active Codebase Final Security Scan
- Audit active codebase verifying 0 `shell=True`, 0 `os.system`, 0 `eval`, 0 `exec`, 0 `pickle.loads`, 0 unsafe `yaml.load`.

### Increment 19: Phase 18 Release Candidate Gate (`tests/test_phase18_gate.py`)
- 20-point Phase 18 Certification Gate covering versioning, startup, diagnostics, JSON output, models, config, dependencies, log policy, security, legacy isolation, registry, safety boundaries, cleanup, documentation, release manifest.

### Increment 20: Phase 18 Release Scorecard (`PHASE_18_RELEASE_SCORECARD.md`)
- 20-point release scorecard verifying all release standards.

---

## 3. Verification & Exit Criteria Matrix

| Exit Criteria Metric | Baseline | Target | Measurement Method |
|---|---|---|---|
| **Authoritative Version** | `0.1.0` | `1.0.0` | `python main.py --version` |
| **CLI JSON Diagnostics** | Working | `100%` | `python main.py --diagnostics --json` |
| **CLI Model Status** | Working | `100%` | `python main.py --models` |
| **Log Rotation** | Unbounded | Max 5 MB x 3 | `friday/utils/logger.py` |
| **Pytest Unit Markers** | Generic | `pytest -m unit` | `pytest.ini` & `pytest -m unit` |
| **Automated Smoke Test** | Working | `100% PASS` | `python scripts/release_smoke_test.py` |
| **Release Gate Test** | 20 checks | `20 / 20 PASS` | `pytest tests/test_phase18_gate.py` |
| **Full System Regression Suite** | `441 / 441 PASS` | `441+ / 441+ PASS` | `pytest tests/` |
