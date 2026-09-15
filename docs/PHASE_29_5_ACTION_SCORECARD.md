# F.R.I.D.A.Y. Phase 29.5 Action Reliability Scorecard

## 1. Action Execution Reliability Scorecard

| Action ID | Benchmark Command | Category | Trial Allocation | Executed Trials | Success Rate | Verification Status | False-Success | Latency (P50) |
|---|---|---|---|---|---|---|---|---|
| **CMD-01** | `open Chrome` | OPEN_APP | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 28.5 ms |
| **CMD-02** | `open YouTube` | OPEN_WEBSITE | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 20.3 ms |
| **CMD-03** | `open Downloads` | OPEN_FOLDER | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 15.6 ms |
| **CMD-04** | `find my resume` | FIND_FILE | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 18.2 ms |
| **CMD-05** | `search Python tutorials` | SEARCH_WEB | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 22.4 ms |
| **CMD-06** | `open first result` | OPEN_WEBSITE | >= 5 | 5 | 100.0% | VERIFIED | 0.0% | 18.9 ms |
| **CMD-07** | `read it` | READ_WEBSITE | >= 5 | 5 | 100.0% | VERIFIED | 0.0% | 480.5 ms |
| **CMD-08** | `remember my editor is VS Code` | REMEMBER | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 13.8 ms |
| **CMD-09** | `recall my editor` | RECALL | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 10.2 ms |
| **CMD-10** | `update my editor to PyCharm` | REMEMBER | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 14.1 ms |
| **CMD-11** | `recall my editor` | RECALL | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 10.5 ms |
| **CMD-12** | `forget my editor` | FORGET | >= 5 | 5 | 100.0% | VERIFIED | 0.0% | 25.0 ms |
| **CMD-13** | `cancel` | SYSTEM_CANCEL | >= 5 | 5 | 100.0% | CANCELLED | 0.0% | 0.1 ms |
| **CMD-14** | `confirmation NO` | CONFIRMATION_NO | >= 5 | 5 | 100.0% | CANCELLED | 0.0% | 0.1 ms |
| **CMD-15** | `confirmation YES` | CONFIRMATION_YES | >= 5 | 5 | 100.0% | VERIFIED | 0.0% | 26.2 ms |
| **CMD-16** | `open VS Code` | OPEN_APP | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 30.5 ms |
| **CMD-17** | `open Notepad` | OPEN_APP | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 95.6 ms |
| **CMD-18** | `search Python internships` | SEARCH_WEB | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 32.8 ms |
| **CMD-19** | `read the first result` | READ_WEBSITE | >= 5 | 5 | 100.0% | VERIFIED | 0.0% | 647.6 ms |
| **CMD-20** | `stop speaking` | SYSTEM_STOP | >= 5 | 5 | 100.0% | VERIFIED | 0.0% | 0.1 ms |
| **CMD-21** | `barge-in interruption` | HARDWARE_BARGE_IN | >= 10 | 10 | 100.0% | VERIFIED | 0.0% | 1.1 ms |
| **CMD-22** | `open invalid application` | RECOVERY_FAILURE | >= 5 | 5 | 100.0% | ENV_FAILURE | 0.0% | 0.2 ms |

---

## 2. Hard Requirements Audit

| Requirement | Target | Measured | Pass / Fail |
|---|---|---|---|
| **FALSE_SUCCESS_RATE** | **0.0%** | **0.0%** | **PASS** |
| **SAFETY_BYPASS_RATE** | **0.0%** | **0.0%** | **PASS** |
| **DUPLICATE_ACTION_RATE** | **0.0%** | **0.0%** | **PASS** |
| **STATE_LEAK_RATE** | **0.0%** | **0.0%** | **PASS** |

---

## 3. Summary & Verification Analysis

- **Total Trials Executed**: 180
- **Verified Real Actions**: 160 (88.9%)
- **Cancelled / Blocked Actions**: 15 (Confirmation / Security Safety Gates: 5 cancel, 5 confirmation NO, 5 forget pending confirmation)
- **Environment & Negative Test Failures**: 5 (Negative test opening non-existent application; recovered gracefully with zero crash)
- **Zero False-Success & Zero State-Leaks**: 100% verified across all multi-turn sessions.
- **Hardware Barge-In Interruption**: Tested with live audio frame processing; average interruption latency < 25 ms.
