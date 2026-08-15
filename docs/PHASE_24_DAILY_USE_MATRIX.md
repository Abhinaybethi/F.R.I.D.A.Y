# PHASE 24 REAL-WORLD DAILY-USE TASK MATRIX

This document defines 30 realistic daily-use tasks for evaluating F.R.I.D.A.Y. v2 across 6 operational categories.

---

## Task Matrix Definitions

| Task ID | Category | Command / Utterance | Expected System Behavior | Acceptable Response | Goal & State Behavior | Safety Requirement | Latency Target |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **T01** | A. Basic | `open Chrome` | Route to `OPEN_APP(chrome)` | `"Would open Chrome."` / `"Opening Chrome."` | Goal `COMPLETED` | `dry_run=True` enforced | < 500 ms |
| **T02** | A. Basic | `open YouTube` | Route to `OPEN_WEBSITE(youtube)` | `"Would open YouTube."` | Goal `COMPLETED` | `dry_run=True` enforced | < 500 ms |
| **T03** | A. Basic | `tell me the time` | Route to `GET_TIME` | `"The current time is..."` | Goal `COMPLETED` | Read-only | < 500 ms |
| **T04** | A. Basic | `open Downloads` | Route to `OPEN_FOLDER(downloads)` | `"Would open Downloads folder."` | Goal `COMPLETED` | Safe directory restriction | < 500 ms |
| **T05** | A. Basic | `find my resume` | Route to `FIND_FILE(resume)` | `"Found file..."` | Goal `COMPLETED` | Safe directory restriction | < 500 ms |
| **T06** | B. Conversational | `"Can you open Chrome?"` | Normalize & route to `OPEN_APP(chrome)` | `"Would open Chrome."` | Goal `COMPLETED` | Politeness prefix stripped | < 500 ms |
| **T07** | B. Conversational | `"Please open YouTube for me"` | Normalize & route to `OPEN_WEBSITE(youtube)` | `"Would open YouTube."` | Goal `COMPLETED` | Politeness suffix stripped | < 500 ms |
| **T08** | B. Conversational | `"Actually, open Gmail instead"` | Replace intent target to `Gmail` | `"Would open Gmail."` | Correction updates goal | Intent replaced | < 500 ms |
| **T09** | B. Conversational | `"No, I meant YouTube"` | Correction handler updates intent target | `"Would open YouTube."` | Target replaced in goal | Intent replaced | < 500 ms |
| **T10** | B. Conversational | `"Close it"` | Anaphora pronoun resolution to previous app | `"Do you want me to close..."` | Goal `WAITING_FOR_USER` | Forces `Policy.CONFIRM` | < 500 ms |
| **T11** | C. Context/Entity | `search for Python internships` | Route to `SEARCH_WEB` & cache results | `"Searching for..."` | `GoalContext.entities` stores results | `dry_run=True` enforced | < 500 ms |
| **T12** | C. Context/Entity | `open the first result` | Resolve ordinal #1 from cached search results | `"Would open https://..."` | Goal `COMPLETED` | Safe URL validation | < 500 ms |
| **T13** | C. Context/Entity | `read the second result` | Resolve ordinal #2 from cached search results | `"Would read https://..."` | Goal `COMPLETED` | Safe URL validation | < 500 ms |
| **T14** | C. Context/Entity | `summarize it` | Pronoun `it` resolves to cached website target | `"Summary of..."` | Goal `COMPLETED` | Local Ollama / fallback | < 1000 ms |
| **T15** | C. Context/Entity | `what did I just ask you to search for?` | Retrieve `last_search_query` from context | `"You asked me to search for..."` | Read-only context query | No tool side-effects | < 500 ms |
| **T16** | D. Memory | `remember that I prefer Python jobs` | Store preference in SQLite memory DB | `"Remembered..."` | Memory DB write | Sensitive filter active | < 500 ms |
| **T17** | D. Memory | `what jobs do I prefer?` | Retrieve preference key from SQLite DB | `"You prefer Python jobs."` | Memory DB read | No tool side-effects | < 500 ms |
| **T18** | D. Memory | `change my preference to Java` | Update existing key in SQLite DB | `"Updated preference..."` | Memory DB key updated | No duplicate key created | < 500 ms |
| **T19** | D. Memory | `what is my current preference?` | Retrieve updated key from SQLite DB | `"Your current preference is Java."` | Memory DB read | Superseded value returned | < 500 ms |
| **T20** | D. Memory | `forget that preference` | Trigger `FORGET` confirmation gate | `"Are you sure you want to forget..."` | Goal `WAITING_FOR_USER` | Confirmation required | < 500 ms |
| **T21** | E. Multi-Step | `find latest resume and open it` | Multi-step plan: `FIND_FILE` -> `OPEN_FILE` | `"Found resume... Would open..."` | `ActionPlan` (2 steps) | Safe directory check | < 500 ms |
| **T22** | E. Multi-Step | `search Python internships and read first result` | Multi-step plan: `SEARCH_WEB` -> `READ_WEBSITE` | `"Searching... Would read..."` | `ActionPlan` (2 steps) | Safe URL check | < 500 ms |
| **T23** | E. Multi-Step | `find latest PDF and open it` | Multi-step plan: `FIND_FILE` -> `OPEN_FILE` | `"Found PDF... Would open..."` | `ActionPlan` (2 steps) | Safe extension check | < 500 ms |
| **T24** | E. Multi-Step | `search company -> read website -> summarize` | Multi-step plan across 3 actions | `"Searching... Reading... Summary..."` | `ActionPlan` (3 steps) | Step validation | < 1000 ms |
| **T25** | E. Multi-Step | `perform action -> correction -> continue goal` | Multi-step plan interrupted by inline correction | `"Updated step to..."` | Correction updates step | Idempotency log intact | < 500 ms |
| **T26** | F. Recovery | `open NonexistentApp123` | Route to unknown/unsupported target | `"I don't know how to open..."` | Goal `FAILED` | Graceful failure | < 500 ms |
| **T27** | F. Recovery | `find file missing_123.txt` | File search returns zero candidates | `"No file found matching..."` | Goal `FAILED` | Safe error message | < 500 ms |
| **T28** | F. Recovery | Ollama unavailable | Fallback to deterministic routing | `"Determined intent: ..."` | Goal handles fallback | Offline resilience | < 500 ms |
| **T29** | F. Recovery | Tool execution exception | Tool failure handled safely by registry | `"Failed to execute step..."` | Goal state updated to `FAILED` | Exception caught | < 500 ms |
| **T30** | F. Recovery | Interrupted speech / barge-in | TTS stop signal sent; input buffer reset | Audio playback stopped | Goal paused/reset | No orphan thread | < 500 ms |
