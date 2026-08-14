# F.R.I.D.A.Y. Security Threat Model (v1.0.0)

---

## 1. Security Principles

1. **Fail-Closed Safety**: System defaults to `dry_run: true` and `allow_real_execution: false`. Real action requires passing three explicit gates.
2. **Zero Arbitrary Code Execution**: Codebase audit enforces zero `shell=True`, zero `os.system`, zero `eval` or `exec`.
3. **Local Privacy**: 100% offline data flow. Zero cloud network calls or telemetry.

---

## 2. Threat & Mitigation Matrix

| Threat Surface | Vulnerability / Impact | Defense Mechanism | Verification Status |
|---|---|---|---|
| **Malicious Speech Commands** | User or audio playback trying to format C: or delete files | Centralized permission policy denies destructive verbs | 🟢 **MITIGATED** (`test_execution_security.py`) |
| **STT Hallucination** | Noise transcribed as dangerous action | Strict regex router & permission gate filter invalid intents | 🟢 **MITIGATED** (`test_fuzzy_router.py`) |
| **LLM Prompt Injection** | Web search content or prompt payload attempting tool escape | Strict JSON schema validator drops unknown fields | 🟢 **MITIGATED** (`test_reasoning_security.py`) |
| **LLM Tool Injection** | Reasoner returning unpermitted action type | Upfront plan validator & permission policy block execution | 🟢 **MITIGATED** (`test_reasoning_validator.py`) |
| **Arbitrary Shell Execution** | Invoking cmd.exe or PowerShell scripts | Absolute ban on shell execution tokens in codebase | 🟢 **MITIGATED** (`test_phase18_gate.py`) |
| **Malicious URLs** | Web action attempting `file://` or local script execution | URL protocol validator restricts schemes to `http://` and `https://` | 🟢 **MITIGATED** (`test_real_browser.py`) |
| **Confirmation Bypass** | Skipping user confirmation on stateful actions | State machine enforces explicit `WAITING_FOR_CONFIRMATION` | 🟢 **MITIGATED** (`test_confirmation.py`) |
| **Config Tampering** | Invalid or dangerous config structure | Fail-closed `validate_config()` rejects unsafe structures | 🟢 **MITIGATED** (`test_config_validation.py`) |
