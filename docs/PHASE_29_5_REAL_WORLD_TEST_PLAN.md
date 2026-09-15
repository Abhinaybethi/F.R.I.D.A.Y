# F.R.I.D.A.Y. Phase 29.5 Real-World Action Reliability Test Plan

## 1. Objective & Scope

The objective of Phase 29.5 is to rigorously evaluate and stress-test F.R.I.D.A.Y. as a real, daily-use Windows voice assistant operating directly against physical OS processes, real network endpoints, local SQLite storage, and hardware sound devices, rather than relying solely on isolated unit tests or simulated execution.

No mocks or stubs will be used for the final real-world measurement campaign.

---

## 2. Real vs. Simulated Test Audit

| Subsystem / Test File | Test Type | Real Windows OS | Real Network | Real SQLite | Real Audio Hardware | Simulated / Mocked |
|---|---|---|---|---|---|---|
| `test_phase18_gate.py` | Unit / Gate | No | No | Partial (temp DB) | No | Yes |
| `test_phase21_gate.py` | Integration / Gate | No | No | Yes | No | Yes |
| `test_phase23_gate.py` | Workflow Gate | No | No | Yes | No | Yes |
| `test_phase24_gate.py` | Hardening Gate | No | No | Yes | No | Yes |
| `test_phase28_5_verification.py` | Verifier Gate | Partial | No | Yes | No | Yes (`dry_run=True`) |
| `test_phase29_real_action_certification.py` | Intent Certification | Partial | No | Yes | No | Yes (`dry_run=True`) |
| **`scripts/real_world_action_stress.py`** | **Stress Campaign** | **YES** | **YES** | **YES** | **YES** | **NO** |
| **`tests/test_phase29_5_real_world.py`** | **Real-World Test Suite** | **YES** | **YES** | **YES** | **YES** | **NO** |

---

## 3. Campaign Structure & Trial Allocations

The campaign exercises 20 benchmark commands across physical Windows environment, network APIs, local database, and audio devices:

### Minimum Trial Matrix

1. **Deterministic App Commands** (>=10 trials each):
   - `open Chrome` (OPEN_APP)
   - `open VS Code` (OPEN_APP)
   - `open Notepad` (OPEN_APP)
   - `open Downloads` (OPEN_FOLDER)
   - `open YouTube` (OPEN_WEBSITE)

2. **Web Search & Content Retrieval** (>=10 trials each):
   - `search Python tutorials` (SEARCH_WEB)
   - `open first result` (OPEN_WEBSITE via ordinal search resolution)
   - `read it` (READ_WEBSITE via pronoun resolution)
   - `search Python internships` (SEARCH_WEB)
   - `read the first result` (READ_WEBSITE via ordinal search resolution)

3. **Memory Lifecycle & Preference State** (>=10 trials each):
   - `remember my editor is VS Code` (REMEMBER)
   - `recall my editor` (RECALL)
   - `update my editor to PyCharm` (REMEMBER update)
   - `recall my editor` (RECALL updated preference)
   - `forget my editor` (FORGET with confirmation)

4. **System Control & Confirmation Workflows** (>=5 trials each):
   - `cancel` (SYSTEM_CANCEL)
   - `confirmation NO` (CONFIRMATION_NO)
   - `confirmation YES` (CONFIRMATION_YES)
   - `stop speaking` / `stop F.R.I.D.A.Y. speaking` (SYSTEM_STOP_TTS)

5. **Read-Only Filesystem Search** (>=10 trials):
   - `find my resume` (FIND_FILE)

---

## 4. Telemetry Schema & Calculated Metrics

For every trial, structured JSON telemetry is recorded with the following fields:
```json
{
  "trial_id": 1,
  "timestamp": "2026-08-17T13:00:00Z",
  "command": "open Notepad",
  "transcript": "open Notepad",
  "intent": "OPEN_APP",
  "target": "notepad",
  "plan": null,
  "tool": "apps.open_app",
  "execution_started": 178954000.0,
  "execution_completed": 178954015.0,
  "execution_result": {"success": true, "message": "Opening Notepad."},
  "verification_result": {"status": "VERIFIED_SUCCESS", "details": {"pid": 1234}},
  "verification_evidence": "process_active: notepad.exe",
  "spoken_response": "Opening Notepad.",
  "latency_ms": 15.2,
  "error": null,
  "recovery_result": null,
  "classification": "REAL + VERIFIED"
}
```

### Measured Quality & Reliability Metrics
- **Intent Accuracy**: % of transcripts correctly mapped to target Action enum.
- **Target Accuracy**: % of transcripts correctly resolved to target entity/path/URL.
- **Execution Success Rate**: % of real tool calls returning `ExecutionStatus.SUCCESS`.
- **Verification Success Rate**: % of executed actions independently confirmed by observation.
- **False-Success Rate**: % where execution reported success but physical verification failed (Must be **0%**).
- **False-Failure Rate**: % where verification failed despite successful side effect.
- **Recovery Success Rate**: % of failed steps successfully recovered via fallback or retry.
- **Latency Distribution**: P50, P95, and P99 latency in milliseconds.
- **Duplicate-Action Rate**: % of actions executed multiple times erroneously (Must be **0%**).
- **State-Leak Rate**: % of goal or context variables leaking across isolated turns (Must be **0%**).
- **Safety-Bypass Rate**: % of dangerous actions executing without required confirmation (Must be **0%**).

---

## 5. Failure Classification Taxonomy

Every failed trial will be classified into exactly one of:
1. `EXECUTION_FAILURE`: Tool execution threw exception or failed OS call.
2. `VERIFICATION_FAILURE`: Action executed but observation verifier failed to confirm.
3. `UNDERSTANDING_FAILURE`: STT transcript misrecognized or routed to wrong intent.
4. `TARGET_RESOLUTION_FAILURE`: Entity resolver failed to map target to canonical resource.
5. `SAFETY_BLOCK`: Intent blocked by permission whitelist or security validator.
6. `ENVIRONMENT_FAILURE`: Target executable not installed or network offline.
7. `TIMEOUT`: Execution or observation exceeded strict deadline.
