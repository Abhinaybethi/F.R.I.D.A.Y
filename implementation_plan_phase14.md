# Phase 14 — Asynchronous Voice Loop, Hardware Barge-In & Native Windows Desktop Control
## Implementation Plan

---

## 1. Problem Statement & Current Limitations

### Problem 1: Audio Barge-In Is Not Hardware Operational (P0)
- **Current Limitation**: While `TextToSpeech.stop()` exists, the main voice loop in `assistant.run()` is synchronous and blocks while TTS audio plays. VAD is not actively reading audio during TTS output, so live voice barge-in is `NOT HARDWARE VALIDATED`.
- **Solution**: Implement an asynchronous audio session listener (`friday/voice/async_session.py`) that runs VAD on a background thread during TTS playback, calling `TextToSpeech.stop()` instantly when user speech is detected mid-utterance.

### Problem 2: Desktop Window Controls Lack Native Windows Execution (P0)
- **Current Limitation**: `MINIMIZE_APP` and `MAXIMIZE_APP` return dry-run strings without native Windows API integration (`ctypes.windll.user32`).
- **Solution**: Implement native Windows window control functions using safe `ctypes.windll.user32` calls in `friday/tools/desktop.py` under `RELEASE_TEST_MODE` with verification.

### Problem 3: Absence of Live Audio Hardware Latency Benchmark (P0)
- **Current Limitation**: Core processing latency is measured (< 2.5 ms), but live voice end-to-end latency (voice start -> TTS output start) is `NOT MEASURED`.
- **Solution**: Create `scripts/benchmark_hardware_latency.py` to record and output exact hardware timing metrics across STT, routing, context, execution, verification, and TTS.

### Problem 4: Hardcoded Fuzzy Target Aliases (P1)
- **Current Limitation**: `_TARGET_ALIASES` in `friday/intent/fuzzy_router.py` is static.
- **Solution**: Implement `_get_registered_targets()` to dynamically harvest target names from registered application executables, browser websites, and safe directories.

### Problem 5: CLI Assistant Lacks System Tray GUI Overlay (P1)
- **Current Limitation**: Assistant state is printed to terminal console only.
- **Solution**: Implement `friday/ui/tray.py` providing a lightweight system tray status icon.

---

## 2. Prioritized Capability Matrix

| Priority | Capability Module | Description | Target Files |
|---|---|---|---|
| **P0** | **Async Voice Session & Barge-In** | Asynchronous audio thread listening for VAD speech during TTS playback | `friday/voice/async_session.py`, `friday/core/assistant.py` |
| **P0** | **Native Windows Window Control** | Native `ctypes.windll.user32` minimize/maximize window calls | `friday/tools/desktop.py` |
| **P0** | **Live Hardware Benchmark Script** | Measures exact voice end-to-end latency on hardware | `scripts/benchmark_hardware_latency.py` |
| **P1** | **Dynamic Target Alias Registry** | Harvests aliases dynamically from registered tools | `friday/intent/fuzzy_router.py` |
| **P1** | **System Tray GUI Indicator** | Visual system tray status icon for assistant state | `friday/ui/tray.py` |
| **P2** | **Multi-Turn Search Result Buffer** | Retains up to 5 indexed search result URLs in context | `friday/planning/context_resolver.py` |

---

## 3. Exit Criteria & Baselines

| Exit Criterion Metric | Baseline Value | Target Metric | Measurement Method |
|---|---|---|---|
| **Deterministic Command Latency** | `< 0.40 ms` | `< 0.50 ms` | `tests/test_phase14_performance.py` |
| **Fuzzy STT Near-Miss Recovery Rate** | `100%` (on test set) | `100%` | `tests/test_fuzzy_router.py` |
| **Known Command Ollama Bypass Rate** | `100%` (0 LLM calls) | `100%` (0 LLM calls) | `tests/test_phase14_performance.py` |
| **Hardware Barge-In Interruption Latency** | `BASELINE REQUIRED` | `< 200 ms` | `scripts/benchmark_hardware_latency.py` |
| **Voice-to-Response Hardware Latency** | `BASELINE REQUIRED` | `< 800 ms` (deterministic) | `scripts/benchmark_hardware_latency.py` |
| **Zero Accidental Real Executions** | `0` | `0` | `tests/test_phase14_security.py` |
| **Full System Regression Pass** | `337 / 337 PASS` | `360+ / 360+ PASS` | `pytest tests/` |

---

## 4. Security & Safety Implications

- **No Shell Execution**: Zero `shell=True` and zero `os.system` across all new Phase 14 code.
- **Strict Target Whitelisting**: Native `ctypes.windll.user32` window operations are restricted to whitelisted window titles and executables.
- **Safety Policy & Permissions**: All actions remain 100% subject to permission policy (`config.yaml`), upfront plan validation, confirmation policy (`CLOSE_APP`), and post-action verification.
- **Fail-Closed Defaults**: `dry_run: true` and `allow_real_execution: false` in `config.yaml` remain untouched.

---

## 5. Incremental Implementation Plan

### Increment 1: Asynchronous Voice Session Thread & Real Hardware Barge-In (P0)
- Create `friday/voice/async_session.py` with background VAD thread during TTS playback.
- Integrate into `friday/core/assistant.py`.
- Create `tests/test_async_barge_in.py`.

### Increment 2: Native Windows Desktop Window Controls (P0)
- Add safe `ctypes.windll.user32` window minimization/maximization in `friday/tools/desktop.py` under `RELEASE_TEST_MODE`.
- Create `tests/test_native_desktop.py`.

### Increment 3: Live Hardware Performance Benchmark Script (P0)
- Create `scripts/benchmark_hardware_latency.py` for live audio latency timing.

### Increment 4: Dynamic Target Alias Registry (P1)
- Update `friday/intent/fuzzy_router.py` to harvest targets dynamically from registered tools.
- Create `tests/test_dynamic_fuzzy_router.py`.

### Increment 5: System Tray Status Icon Overlay (P1)
- Create `friday/ui/tray.py` providing system tray icon formatting.
- Create `tests/test_ui_tray.py`.

### Increment 6: Phase 14 Security & Performance Audit Suite
- Create `tests/test_phase14_security.py` and `tests/test_phase14_performance.py`.

### Increment 7: Phase 14 Gate & Full Repository Regression Suite
- Create `tests/test_phase14_gate.py` implementing 20-point Phase 14 Gate test.
- Run complete system regression suite across all 65+ test modules.

---

## 6. Proposed Files Created / Modified

### [NEW] `friday/voice/async_session.py`
### [NEW] `friday/ui/tray.py`
### [NEW] `scripts/benchmark_hardware_latency.py`
### [MODIFY] `friday/core/assistant.py`
### [MODIFY] `friday/tools/desktop.py`
### [MODIFY] `friday/intent/fuzzy_router.py`
### [NEW] `tests/test_async_barge_in.py`
### [NEW] `tests/test_native_desktop.py`
### [NEW] `tests/test_dynamic_fuzzy_router.py`
### [NEW] `tests/test_ui_tray.py`
### [NEW] `tests/test_phase14_security.py`
### [NEW] `tests/test_phase14_performance.py`
### [NEW] `tests/test_phase14_gate.py`
