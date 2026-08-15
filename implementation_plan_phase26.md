# Implementation Plan — Phase 26: F.R.I.D.A.Y. v1.1 Daily-Driver Usability Polish

Target: Materially improve F.R.I.D.A.Y.'s daily usability, eliminate cold-start latency spikes, polish memory preference spoken responses, enable basic compound command parsing, and update documentation while strictly preserving privacy, local-first architecture, and safety defaults (`dry_run=True`, `allow_real_execution=False`).

---

## User Review Required

> [!IMPORTANT]
> **Safety Defaults Preserved**: All operations will remain locked under `dry_run=True` and `allow_real_execution=False`. Zero cloud dependencies will be introduced.

> [!NOTE]
> **Cold-Start Latency Outlier Resolved**: To eliminate the `2.6s` Phase 25 MAX latency spike caused by cold ONNX model loading, background warm-loading will be triggered during application initialization.

---

## Proposed Changes

### Voice Pipeline (`friday/voice/text_to_speech.py` & `main.py`)
#### [MODIFY] [text_to_speech.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/voice/text_to_speech.py)
#### [MODIFY] [main.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/main.py)
- Add a lightweight `warmup()` method to `TextToSpeech` that pre-initializes ONNX sessions and engine handles during background startup.
- Call `warmup()` in `main.py` when running interactive voice sessions so initial user speech has zero cold-start latency.

---

### Memory UX (`friday/tools/memory.py`)
#### [MODIFY] [memory.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/tools/memory.py)
- Enhance `remember()` spoken response when overwriting an existing `key_name` preference so the spoken feedback clearly states: `"Updated your {key_name} preference to {value}."`

---

### Intent Routing & Normalizer (`friday/intent/normalizer.py` & `friday/intent/router.py`)
#### [MODIFY] [normalizer.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/normalizer.py)
#### [MODIFY] [router.py](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/friday/intent/router.py)
- Support basic compound voice commands joined by `" and "` (e.g., `"open Chrome and search Python"`) by enabling compound transcript splitting in the normalizer/router while maintaining sub-millisecond execution.

---

### Documentation (`README.md`)
#### [MODIFY] [README.md](file:///c:/Users/abhin/Personal/F.R.I.D.A.Y%20v2/README.md)
- Update `README.md` with Phase 25 long-run certification metrics (100/100 commands, 612/612 PASS, 0 resource leaks, P50 `< 0.3 ms`), daily voice interaction examples, and clear safety policy descriptions.

---

## Verification Plan

### Automated Tests
- Run `python -m pytest -q` to verify zero regression across all 612+ tests.
- Run `python scripts/security_scan.py` to confirm zero security pattern findings and locked safety defaults.

### Manual Verification
- Run `python main.py --diagnostics` to verify startup diagnostics and model pre-warming status.
- Verify cold-start latency of the first spoken interaction is `< 500 ms`.
