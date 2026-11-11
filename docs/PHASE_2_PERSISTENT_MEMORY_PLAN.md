# Phase 1 Audit + Phase 2 Plan — Persistent Conversation & Task Memory

Status: **Phase 1 complete (audit only). Phase 2 not started. No source files changed.**
Date: 2026-11-06
Repo: `C:\Users\abhin\Personal\F.R.I.D.A.Y v2` (branch `feat/live-dashboard`)

---

## 1. Phase 1 — Repository Audit

### 1.1 Runtime entry points

| Entry point | File | Role |
|---|---|---|
| Voice + text assistant | `main.py` → `friday/core/assistant.py` (`Friday`) | Owns reasoner, RAG, tools, voice loop |
| Dashboard backend | `python -m friday.web` → `friday/web/app.py` | FastAPI + WebSocket + static frontend |
| Dashboard runtime | `friday/web/runtime.py` (`DashboardRuntime`) | Lazily builds `Friday`; chat, image, research, voice |
| Core conversation | `friday/core/conversation.py` (`ConversationManager`) | Single turn pipeline: route → tools → reasoner → response |
| Hands-free listener | `friday/web/handsfree.py` | Wake word, sessions, barge-in, flush |

**Confirmed:** one shared conversation pipeline already exists. `submit_chat`, the
hands-free listener, and the CLI all call `ConversationManager.handle_transcript`.
This satisfies the "unified runtime" requirement architecturally; only the
session/context ownership needs centralising in later phases.

### 1.2 What is actually persistent today

| Store | Path | Contents | Limits |
|---|---|---|---|
| Explicit memories | `.data/memory.db` (SQLite) | `memories(id, content, category, confidence, key_name, created_at, updated_at)` | Manual `remember`/`recall`/`forget` only |
| RAG knowledge | `.data/rag/` (ChromaDB 1.3.5) | Document embeddings + `chroma.sqlite3` | Knowledge docs, **not** conversations |
| Activity/tasks | `data/dashboard/activity.json` | Last 500 dashboard events (chat, image, research, voice, tool) | JSON, capped, telemetry only |
| Audit log | `logs/` via `friday/utils/audit_logger.py` | Append-only action audit | Not searchable memory |

### 1.3 What is **not** persistent (the gap)

- `ConversationContext.history` is an in-memory rolling buffer capped at **5 turns**
  (`push_turn()` drops the oldest at `len > 5`).
- Session state (`ConversationSession`) is in-memory; a restart loses the session.
- `ActionPlan`, `GoalContext`, `current_goal`, `completed_steps`, and idempotency
  keys are in-memory only. There is **no** resumable task record.
- No conversation search by meaning, keyword, date, or topic.
- No episodic memory, no semantic fact store beyond free-text `memories`, no
  memory correction/retention/deletion lifecycle.
- No separation between raw conversation and generated summaries (neither exists).

### 1.4 Existing infrastructure evaluated

| Candidate | Present? | Verdict |
|---|---|---|
| PostgreSQL | No (no dependency, no service, no code) | **Do not add.** Local-first app; would add an external service. |
| pgvector | No | **Do not add.** No Postgres to attach it to. |
| Redis | No (only mentioned in a keyword list in `transcript_quality.py`) | **Do not add.** No need for a broker/cache service. |
| ChromaDB | **Yes**, 1.3.5, already used by `friday/rag/` | **Reuse** for semantic conversation vectors. |
| SQLite | **Yes**, stdlib, FTS5 available (verified sqlite 3.43.1) | **Reuse** for raw history, episodes, facts, tasks. |
| JSON activity store | Yes | Keep as dashboard telemetry; do not overload. |

**Storage decision:** two complementary stores, zero new dependencies:

1. **SQLite** `.data/memory.db` (same DB as explicit memories) — raw messages,
   sessions, episodes, semantic facts, tasks, task steps, summaries. Additive
   `CREATE TABLE IF NOT EXISTS` only; the existing `memories` table and its
   verifiers stay untouched.
2. **ChromaDB** `.data/rag/conversations/` — one vector per recorded turn using
   the existing `friday/rag/embedder.py` (`all-MiniLM-L6-v2`, already installed).
   Keyword/date/topic search stays in SQLite FTS5; vectors are optional and
   degrade gracefully.

Rationale: no new service, no new pip dependency, offline, restart-safe, and
the existing RAG index is not polluted with conversation data.

### 1.5 Duplicate / dead modules (leave untouched)

`friday/brain/`, `friday/skills/`, `friday/system_control/`,
`friday/legacy_deprecated/` are small and outside the live pipeline. Per the
preserve-working-code rule they are **not** modified or deleted in this plan.

### 1.6 Test baseline

`python -m pytest --collect-only -q` → **1687 tests collected**.
No test results are claimed beyond collection in this phase.

### 1.7 Integration points Phase 2 must use

- `ConversationManager.handle_transcript()` — the single place every user turn
  passes through (voice, chat, CLI).
- `ConversationManager.start_session()` / `stop_session()` — session boundaries.
- `DashboardRuntime.submit_chat()` — dashboard turn + activity record.
- `friday/web/handsfree.py` — `on_session_end` (already wired to
  `ConversationManager.stop_session()`).
- `friday/tools/registry.py` — real tool outcomes (`ActionOutcome`) for task memory.
- `friday/verification/` — verification status must be stored verbatim, never inferred.

---

## 2. Phase 2 — File-by-file implementation plan

### 2.1 New package `friday/memory/`

| File | Purpose | Key contents |
|---|---|---|
| `friday/memory/__init__.py` | Package export | `MemoryService`, `MemoryConfig` |
| `friday/memory/config.py` | Typed config from `config.yaml.memory` | `enabled`, `db_path`, `vector_enabled`, `retention_days`, `max_turns_per_session`, `summaries` |
| `friday/memory/schema.py` | Schema + migrations | `CREATE TABLE IF NOT EXISTS` for all tables, `PRAGMA user_version`, WAL |
| `friday/memory/store.py` | Low-level SQLite access | Thread-safe connection per call, transactions, insert/query helpers |
| `friday/memory/models.py` | Dataclasses | `SessionRecord`, `TurnRecord`, `EpisodeRecord`, `FactRecord`, `TaskRecord`, `TaskStepRecord`, `SummaryRecord` |
| `friday/memory/retrieval.py` | Search | FTS5 keyword/phrase search, date range, topic filter, vector search via Chroma, deterministic merge/rank |
| `friday/memory/vectors.py` | Chroma conversation index | `conversation_memory` collection, add/delete/update, availability probe |
| `friday/memory/summaries.py` | Separate generated summaries | Extractive summary by default; optional LLM summary marked `generated_by`; never overwrites raw rows |
| `friday/memory/tasks.py` | Task memory (storage only) | Create/update/cancel/resume task records + ordered steps; idempotency keys |
| `friday/memory/service.py` | Facade used by the app | `record_turn`, `start_session`, `end_session`, `search`, `recall`, `correct`, `forget`, `stats`, `prune` |

### 2.2 SQLite schema (in `.data/memory.db`)

```
sessions(id, started_at, ended_at, source, title, summary_id, meta_json)
messages(id, session_id, turn_index, role, raw_text, resolved_text, response_text,
         intent_action, intent_target, tool_status, verification_status,
         created_at, meta_json)
summaries(id, session_id, kind, text, generated_by, model, created_at,
          source_message_ids_json)              -- generated, separate from raw
episodes(id, session_id, kind, title, detail, importance, occurred_at,
         source_message_id, meta_json)
facts(id, subject, predicate, object, category, confidence, source_message_id,
      created_at, updated_at, deleted_at)       -- semantic memory
tasks(id, goal, state, created_at, updated_at, completed_at, source_session_id,
      meta_json)
task_steps(id, task_id, step_index, action, target, status, idempotency_key,
           result_json, verification_status, error, started_at, completed_at)
messages_fts (FTS5 external-content index on messages.raw_text/response_text)
```

Existing `memories` table is untouched. `facts` is the structured layer; the
free-text `memories` table remains the voice `remember`/`recall` surface, and
`MemoryService` can project explicit remember actions into both.

### 2.3 Modified files

| File | Change (minimal, additive) |
|---|---|
| `friday/core/conversation.py` | Create `MemoryService`; on `start_session`/`stop_session` record boundaries; at the end of `handle_transcript`, persist the raw user turn, resolved query, response, intent, tool/verification status. Wrap in try/except so memory failure never breaks a turn. |
| `friday/core/assistant.py` | Build `MemoryService` from config and inject into `ConversationManager`; record source (`voice`/`text`). |
| `friday/web/runtime.py` | Inject the same service (single instance per process); record `source="chat"` sessions. |
| `friday/web/routes.py` | New read/write memory endpoints (below). |
| `config.yaml` | New `memory:` section, disabled-by-default vector index documented. |
| `friday/utils/config_validator.py` | Validate `memory.*` keys (fail closed, clamp ranges). |
| `requirements.txt` | **No new dependencies.** ChromaDB already required by `friday/rag/`; note it explicitly. |
| `docs/ARCHITECTURE.md` | Append memory-layer section after implementation lands. |

### 2.4 New API routes (read-first, explicit delete)

```
GET  /api/memory/stats
GET  /api/memory/sessions?limit=&offset=&source=
GET  /api/memory/sessions/{id}            # raw turns, chronological
GET  /api/memory/search?q=&mode=hybrid&from=&to=&topic=&limit=
GET  /api/memory/facts?q=&category=
GET  /api/memory/tasks?state=
GET  /api/memory/tasks/{id}
POST /api/memory/tasks/{id}/cancel
POST /api/memory/facts/{id}/correct       # explicit correction, keeps audit
DELETE /api/memory/sessions/{id}          # explicit retention control
DELETE /api/memory/facts/{id}             # soft delete (deleted_at)
POST /api/memory/prune                    # retention job, dry_run default true
```

No endpoint invents content. Search returns stored rows with timestamps and
source session/turn ids.

### 2.5 Frontend (minimal for Phase 2)

| File | Change |
|---|---|
| `frontend/src/pages/MemoryPage.tsx` (new) | Search, recent sessions, facts, tasks, delete with confirmation |
| `frontend/src/lib/api.ts`, `types.ts` | Typed memory endpoints |
| `frontend/src/App.tsx`, `Sidebar.tsx` | `/memory` route + nav entry |
| `frontend/src/test/dashboard.test.tsx` | Render test for the new page |

### 2.6 Tests (new)

| File | Coverage |
|---|---|
| `tests/test_memory_store.py` | Schema creation/idempotency, WAL, turn ordering, FTS5 search, date/topic filters |
| `tests/test_memory_service.py` | Session lifecycle, raw vs summary separation, corrections, soft delete, retention/prune, restart persistence |
| `tests/test_memory_tasks.py` | Task create/update/cancel/resume, step ordering, idempotency keys |
| `tests/test_memory_retrieval.py` | Keyword, phrase, hybrid vector fallback when Chroma unavailable |
| `tests/test_memory_integration.py` | `ConversationManager` records real turns; memory failure cannot break a response; hands-free session end closes session |
| `tests/test_memory_routes.py` | All new endpoints, validation, 404s, dry-run prune |

Regression gate after implementation: the memory test pack plus the existing
`tests/test_handsfree.py`, `tests/test_audio_pipeline.py`, conversation, RAG,
tool, and web route suites.

### 2.7 Explicit non-goals for Phase 2

- No task orchestrator execution engine (Phase 3) — only persistent task records.
- No screen capture, messaging, email, or YouTube code (Phases 4–6).
- No new database service, no Redis, no Postgres, no cloud sync.
- No modification of `friday/brain`, `friday/skills`, `friday/system_control`.

---

## 3. Approval gate

Phase 2 will begin only after explicit approval. Implementation will be
incremental (storage → recording → retrieval → API → UI), with the relevant
tests run after each step and no commit/push until requested.
