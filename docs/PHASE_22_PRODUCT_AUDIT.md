# F.R.I.D.A.Y. Phase 22 Product Audit — Personal Assistant Workflow Intelligence

## 1. Executive Summary
Phase 21 achieved 100% security hardening (SSRF boundaries, gated FORGET memory deletion, path traversal blocks, and verifier alignment) and 100% test pass rate across all 531 repository tests. However, an architecture and product audit of daily-use scenarios reveals that F.R.I.D.A.Y. currently operates as a turn-by-turn command listener rather than an intelligent personal assistant.

While atomic commands (e.g., "open chrome", "find file report.docx", "what time is it") execute reliably, multi-turn human workflows break down due to rigid context resolution, passive memory silos, fragile multi-step plan execution, and lack of conversational goal tracking.

Phase 22 focuses on **Workflow Intelligence**: enabling coherent multi-turn goal tracking, rich entity reference resolution ("it", "that", "the second one"), active structured memory, resilient step recovery, and clear intent classification (command vs. question vs. task vs. correction).

---

## 2. Current Capability Map
| Subsystem | Current Implementation | Architectural Limits |
| :--- | :--- | :--- |
| **Routing** | Deterministic Regex -> Fuzzy Router -> Local Ollama Fallback | Static pattern matching misses natural variations; falls back to LLM for basic reference resolution. |
| **Context** | 5-turn `history` list of dicts + `ShortTermContext` dataclass | Hardcoded for `"open the first result"`. Fails on generic pronouns ("it", "that", "the second one"). |
| **Memory** | SQLite `.data/memory.db` (`memories` table: `id`, `content`, `created_at`) | Passive storage. Router/normalizer never queries memory to fill parameters or resolve user preferences. |
| **Web Research** | `SEARCH_WEB` (duckduckgo API / HTML scrape) -> `READ_WEBSITE` (BeautifulSoup) | Search results stored in short-term context but lack entity indexing (Result #1..#N) for interactive selection. |
| **Planner & Execution** | `ActionPlan` (static list of steps) -> `executor.py` step-by-step runner | Fails closed on any step error; no alternative candidate recovery, no goal re-planning. |
| **State Machine** | `IDLE`, `LISTENING`, `THINKING`, `EXECUTING`, `WAITING_FOR_CONFIRMATION`, `RESPONDING` | Synchronous execution blocks main loop; corrections during execution drop plan context. |
| **Safety & Verification** | Policy Validator + Action Verifiers + Dry Run default | Strict and safe, but lacks user-assisted correction mechanisms. |

---

## 3. Workflow Limitations & Architectural Gaps

### 3.1 Questions Answered

1. **Can F.R.I.D.A.Y. maintain a coherent goal across multiple turns?**
   - **No.** Multi-step plans exist only within a single transcript or immediate confirmation loop (`ActionPlan`). Once completed or failed, `current_plan` is set to `None`. Long-term or multi-turn goals split across conversation turns are forgotten.

2. **Can it resolve references ("open it", "read that", "use the second result", "now save it", "do the same thing for the other one")?**
   - **No.** `context_resolver.py` contains hardcoded string comparisons exclusively for `"open the first result"`. It cannot resolve index offsets (#2, #3), pronouns ("it", "that"), or past targets ("save it", "the other one").

3. **Can it perform a complete workflow (search → inspect → select → act → verify → report)?**
   - **No.** Step 1 (`search`) and Step 4 (`act`) work individually. However, Step 2 (`inspect` results summary) and Step 3 (`select` candidate by reference) are missing due to lack of entity indexing in short-term context.

4. **Can web search results become actionable context rather than merely text?**
   - **Partially.** Phase 21 populates `context.last_tool_result["results"]`, but items are raw un-indexed dicts without positional keys (e.g., `#1`, `#2`), domain trust scores, or selection helpers.

5. **Can memory influence future commands safely?**
   - **No.** Memory is a passive silo. `remember()` saves text and `recall()` reads it upon explicit request. The intent router and parameter resolver never consult memory to fill missing parameters (e.g., "my usual browser", "my home address").

6. **Does memory support categories, timestamps, confidence, updates, conflicts, explicit forgetting, and stale memories?**
   - **Timestamps**: YES (`created_at`).
   - **Explicit Forgetting**: YES (Phase 21 gated `FORGET` intent).
   - **Categories / Confidence / Updates / Conflicts / Stale TTL**: NO. Memory is flat text without metadata, versioning, or conflict resolution.

7. **Can a multi-step goal survive intermediate failures?**
   - **No.** If step 1 fails, `executor.py` marks the plan as `PlanState.FAILED` and clears `current_plan`. There is no retry logic, candidate fallback, or user intervention loop.

8. **Does the assistant understand the difference between command, question, task, goal, confirmation, and correction?**
   - **Commands, Questions, Confirmations**: YES.
   - **Task, Goal, Correction**: NO. A user correction ("No, open Chrome instead") breaks the state machine or starts a brand new intent resolution without linking to the previous turn's mistake.

9. **Where does Ollama add actual value?**
   - Answering general knowledge queries.
   - Summarizing long web page text retrieved by `READ_WEBSITE`.
   - Disambiguating complex natural language queries that cannot be matched deterministically.

10. **Where is Ollama unnecessarily being used?**
    - Cold-start fallback when regex matching fails on minor phrasing variations.
    - Attempting to answer follow-up queries ("the second one") that fail deterministic context resolution, leading to hallucinations.

---

## 4. Top 5 Daily-Use Workflows

1. **Interactive Multi-Turn Web Research & Action**
   - *Scenario*: User asks "Search for Python 3.12 release notes" → "Summarize the second result" → "Open its website".
   - *Value*: Eliminates manual browser navigation for routine information gathering.

2. **Context-Aware Document & File Operations**
   - *Scenario*: User says "Find my quarterly report" → "Read it" → "What were the sales figures?" → "Open its folder".
   - *Value*: Hands-free local file inspection and deep context retention.

3. **Active Personal Preference & Memory Retrieval**
   - *Scenario*: User says "Remember my Wi-Fi network is HomeNet" → (later) "What is my Wi-Fi network?" OR user says "Open my favorite browser" → resolves to Chrome based on stored memory.
   - *Value*: Personalized assistant behavior without cloud configuration.

4. **Resilient Multi-Step Workflows with Failure Recovery**
   - *Scenario*: User asks "Download project template and open downloads" → Step 1 (download) fails → system prompts: "Primary download failed. Try backup source?" → user confirms "Yes" → workflow completes.
   - *Value*: High completion rate without total workflow abandonment on minor errors.

5. **Conversational Correction & Disambiguation**
   - *Scenario*: User says "Open Word" → system opens WordPad → User says "No, I meant Microsoft Word" → system closes WordPad, opens MS Word, and records the alias correction.
   - *Value*: Natural voice interaction that learns and adapts to user terminology.

---

## 5. Prioritized Phase 22 Roadmap

### P0 (Core Intelligence & Reference Resolution)
- **Entity & Anaphora Resolution Engine**: Implement `EntityContext` indexer for search results, files, apps, and URLs. Support "it", "that", "first/second/last", "the other one".
- **Active Memory Integration**: Enhance `memories` table schema (category, confidence, key-value tags, updated_at). Connect `recall()` to parameter resolution for personalized defaults.

### P1 (Workflow Resilience & Conversational State)
- **Goal & Re-Planning State Machine**: Extend `ActionPlan` to support step retries, fallback candidates, and user re-planning on intermediate failure.
- **Conversational Correction Handler**: Detect correction intents ("no, I meant X", "instead do Y") and link them to the preceding turn's intent/target.

### P2 (UX & Performance Optimization)
- **Structured Search Result Summarizer**: Automatic 3-bullet summary generator for `SEARCH_WEB` results before user selection.
- **Memory TTL & Stale Cleaner**: Automatic confidence decay and conflict resolution for outdated memories.

---

## 6. Explicit Non-Goals
- **NO Cloud LLM integrations** (Keep 100% local Ollama / deterministic rules).
- **NO arbitrary shell agents or raw code execution** (Keep safety sandbox intact).
- **NO unrestricted GUI / mouse automation** (Keep clean OS tool wrappers).
- **NO massive UI framework rewrites** (Keep lightweight HTML/CSS/JS).
- **NO heavy external database engines** (Extend existing local SQLite `.data/memory.db`).
- **NO speculative "AGI" or autonomous internet browsing agents**.
