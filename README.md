# F.R.I.D.A.Y. — Personal Local AI Voice Assistant

**F.R.I.D.A.Y.** is a privacy-first, local AI voice assistant for Windows that combines speech recognition, voice activity detection, deterministic intent routing, local LLM reasoning, a deterministic natural-conversation layer, a local hybrid knowledge base, opt-in web research, tool execution, contextual memory, and text-to-speech into a single desktop assistant.

The system is designed around a **local-first architecture**: speech processing and LLM inference run directly on the user's machine without sending conversations to a cloud AI provider. Everything except the explicitly opt-in research subsystem works fully offline.

---

## 🚀 Current Architecture

```text
                    ┌──────────────────────┐
                    │      Microphone      │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │      Silero VAD      │
                    │ Voice Activity Detect│
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    faster-whisper    │
                    │   Local Speech → Text │
                    └──────────┬───────────┘
                               │
                               ▼
              ┌────────────────────────────────┐
              │     Command / Intent Router     │
              │ Deterministic + Fuzzy Matching  │
              └───────────────┬─────────────────┘
                              │
                              ▼
              ┌────────────────────────────────┐
              │  Deterministic Classification  │
              │     RequestClass (no LLM)      │
              └───────────────┬─────────────────┘
                              │
                              ▼
              ┌────────────────────────────────┐
              │   Natural Conversation Layer   │
              │  Greeting / wellbeing / thanks │
              │ feedback / farewell  (no LLM)  │
              └───────────────┬─────────────────┘
                              │  only when the whole
                              │  utterance is chatter
                              ▼
         ┌─────────────────┐   ┌──────────────────────┐
         │ Known Commands  │   │ Context Resolution   │
         │ Fast Tool Path  │   │   + RAG / Research   │
         └────────┬────────┘   └─────────┬────────────┘
                  │                       │
                  │              ┌────────▼─────────┐
                  │              │    Bonsai LLM    │
                  │              │      8B GGUF     │
                  │              └────────┬─────────┘
                  │                       │
                  └────────────┬──────────┘
                               ▼
                     ┌──────────────────────┐
                     │  Safety / Permission │
                     │       Gate           │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │     Tool Executor    │
                     │ Windows / Web / Files │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │   Response Formatter │
                     └──────────┬───────────┘
                                │
                                ▼
                     ┌──────────────────────┐
                     │      Kokoro TTS      │
                     │   Local Speech Output│
                     └──────────────────────┘
```

---

# ✨ Key Features

### 🧠 Local LLM Reasoning

F.R.I.D.A.Y. uses a locally hosted **Bonsai GGUF model** for reasoning.

The model is served through **llama.cpp**, exposing an OpenAI-compatible local HTTP API.

```text
F.R.I.D.A.Y.
     │
     ▼
LlamaCppReasoner
     │
     ▼
llama-server
     │
     ▼
Bonsai-8B-Q1_0.gguf
```

No external LLM API is required for the reasoning pipeline.

---

### 🎙️ Local Speech Recognition

Speech recognition is performed locally using:

* **faster-whisper**
* CPU-optimized inference
* `small.en` model
* Local audio processing

The microphone audio never needs to be uploaded to a cloud speech service.

---

### 🔊 Local Text-to-Speech

F.R.I.D.A.Y. uses local TTS processing for spoken responses.

Current components include:

* **Kokoro ONNX**
* Local inference
* Asynchronous playback
* Hardware/software barge-in support

The assistant can stop active speech when the user starts speaking.

---

### 🎯 Fast Command Routing

F.R.I.D.A.Y. does not send every request to the LLM.

Simple commands are handled directly by the deterministic command router.

For example:

```text
"Open Chrome"
        │
        ▼
Intent Router
        │
        ▼
open_app("chrome")
```

Instead of:

```text
User → STT → LLM → reasoning → tool selection → execution
```

This reduces unnecessary LLM inference and improves response latency.

---

### 💬 Natural Conversation Layer (no LLM)

Pure social chatter is answered locally by `friday/core/natural_conversation.py`, before context
resolution and before the reasoner, so `"how are you?"` never costs an inference call.

```text
"how are you?"
      │
      ▼
NaturalConversationRouter
      │
      ▼
"I'm doing great. How about you?"      (~0.9 ms, 0 LLM calls)
```

Recognised intents:

| Intent | Example |
| --- | --- |
| Greeting | `hi`, `hey Friday`, `good morning` |
| Wellbeing | `how are you?`, `how's it going?`, `you okay?` |
| Thanks | `thanks`, `thank you so much`, `that helped` |
| Acknowledgement | `okay`, `sure`, `got it`, `sounds good` |
| Positive feedback | `nice`, `great`, `that's great` |
| Negative feedback | `ugh`, `oh no`, `that's bad` |
| Farewell | `bye`, `see you later`, `catch you later` |

The layer is deliberately conservative and **only handles an utterance when every part of it is
conversational**:

```text
"hi, how are you?"                       → handled locally
"thanks, bye"                            → handled locally
"okay, what is Node.js?"                 → passed to the pipeline
"thanks, search for Python 3.14"         → passed to the pipeline
"can you tell me about it? … node man"   → passed to the pipeline
```

Questions, commands, tool requests, context references, follow-ups, and anything with an entity,
version, date, or quantity are never swallowed. The raw utterance is never rewritten — normalisation
happens on a copy used only for matching.

Configuration:

```yaml
natural_conversation:
  enabled: true          # FRIDAY_NATURAL_CONVERSATION_ENABLED overrides
```

Logging and counters:

```text
[NATURAL_CHAT] intent=WELLBEING handled=true -> local response (no LLM) raw='how are you?' ...
```

`natural_chat_count`, `natural_chat_llm_bypass_count`, `natural_chat_latency_ms_{total,avg,max}`,
`natural_chat_rejected_count`

---

### 📚 Local Knowledge Base (Hybrid RAG)

Document Q&A runs against a local knowledge base in `friday/rag/` with no external service:

```text
docs/*.md, project files
        ↓
   Chunker
        ↓
 Embeddings (all-MiniLM-L6-v2, ONNX, 384-dim, local)
 + BM25 lexical index
        ↓
 Hybrid retrieval → rerank → relevance floor → context compression
        ↓
      Prompt → Bonsai
```

Query analysis, relevance filtering, and the RAG evaluation set live in
`friday/rag/query_analyzer.py`, `friday/rag/relevance_filter.py`, and `friday/rag/eval_set.py`.

---

### 🌐 Opt-in Web Research

`friday/research/` provides a plan/answer pipeline for questions that genuinely need the web
(DuckDuckGo search + extraction). It is **disabled by default** and off-line behaviour is unchanged
when it is off.

```yaml
research:
  enabled: false
  provider: "duckduckgo"
  max_results: 5
  max_queries: 3
  timeout: 10
```

---

### 🧩 Context & Anaphora Resolution

F.R.I.D.A.Y. maintains short-term execution context so commands can refer to previously mentioned objects.

Example:

```text
User: Open Chrome

F.R.I.D.A.Y.: Chrome opened.

User: Close it

F.R.I.D.A.Y.: Close Chrome?
```

It can also resolve indexed search results:

```text
User: Search Python tutorials

User: Open the first result
```

The second command can reference the result generated by the previous operation.

---

### 🔐 Safety-First Tool Execution

System-level actions are protected by centralized permission controls.

Default configuration:

```yaml
security:
  dry_run: true
  allow_real_execution: false

tools:
  dry_run: true
  allow_real_execution: false
```

This prevents the assistant from freely executing potentially destructive operations without explicit authorization.

Supported tool categories include:

```text
Open application
Close application
Open folder
Open website
Search web
Get time
Find files
Open files
Minimize application
Maximize application
Take screenshot
```

---

# 🏗️ System Components

## 1. Audio Pipeline

```text
Microphone
    ↓
Audio Capture
    ↓
Silero VAD
    ↓
Speech Segment
```

Silero VAD determines when the user is speaking and prevents unnecessary transcription of silence and background noise.

---

## 2. Speech-to-Text

```text
Speech Segment
      ↓
faster-whisper
      ↓
Transcript
```

The transcription model runs locally.

---

## 3. Intent Detection

The transcript is processed by the command-routing layer.

```text
Transcript
    ↓
Normalization
    ↓
Deterministic Matching
    ↓
Fuzzy / Phonetic Matching
    ↓
Intent Detection
```

This allows commands such as:

```text
"Open Chrome"
"Open grove"
"Open chorme"
```

to potentially resolve to the intended application when the fuzzy matching layer identifies the target.

---

## 4. Natural Conversation Layer

After deterministic classification, pure chatter is answered locally.

```text
Transcript
    ↓
classify()  →  RequestClass        (free, no LLM)
    ↓
NaturalConversationRouter.route()   (free, no LLM)
    │
    ├── pure chatter  → local response, done
    │
    └── anything else → context resolution → RAG / research → reasoner
```

`RequestClass.EXIT`, `COMMAND`, `TOOL_REQUEST`, `CONTEXT_REFERENCE`, `FOLLOW_UP`, and
`SCREEN_QUESTION` never enter this layer, and session-exit / confirmation handling still runs first.

---

## 5. Context Resolution

`friday/planning/context_resolver.py` and the context handling in `friday/core/conversation.py`
resolve pronouns, role ellipsis, and demonstratives deterministically before any model call.

```text
User: Who is the president of Russia?

User: Tell me more about him
      → "tell me more about the president of russia"

User: Who is king charles iii
      → passes through unchanged (not a role question)

User: can you tell me about it? ... freddened like node man. what is node man?
      what's the purpose of using it?
      → trailing "it" binds to the phrase named twice in the same turn
```

---

## 6. LLM Reasoning

Requests that require natural-language reasoning can be routed to the local LLM.

```text
User Request
     ↓
Reasoner Gate
     ↓
LlamaCppReasoner
     ↓
llama-server
     ↓
Bonsai GGUF
     ↓
Generated Response / Plan
```

The local server is automatically started when required if it is not already running.

Example server:

```text
http://127.0.0.1:8080
```

Health check:

```text
GET /health
```

Expected response:

```json
{
  "status": "ok"
}
```

---

# 🤖 Why llama.cpp?

F.R.I.D.A.Y. uses **llama.cpp** as the inference server rather than depending on Ollama.

The architecture is:

```text
Bonsai GGUF
     ↓
llama-server
     ↓
OpenAI-compatible HTTP API
     ↓
F.R.I.D.A.Y.
```

This provides a lightweight local inference layer and allows F.R.I.D.A.Y. to communicate with the model through a standard HTTP interface.

---

# 📦 GGUF Model Support

F.R.I.D.A.Y. is designed to work with locally stored GGUF models.

Example:

```text
Bonsai-8B-Q1_0.gguf
```

The model is loaded by `llama-server`.

Example:

```powershell
llama-server `
  -m C:\AI\models\Bonsai-8B-Q1_0.gguf `
  -c 2048 `
  --host 127.0.0.1 `
  --port 8080
```

F.R.I.D.A.Y. can then communicate with the local server through its HTTP API.

---

# ⚡ Performance-Oriented Architecture

One of the main design principles of F.R.I.D.A.Y. is:

> **Do not use an LLM when deterministic software can solve the problem.**

For example:

```text
"Open Chrome"
```

should not require an LLM.

Instead:

```text
Audio
 ↓
VAD
 ↓
Whisper
 ↓
Intent Router
 ↓
Tool Executor
```

For a more complex request:

```text
Audio
 ↓
VAD
 ↓
Whisper
 ↓
Intent Detection
 ↓
Reasoner Gate
 ↓
Bonsai
 ↓
Tool / Response
```

This hybrid architecture reduces unnecessary inference overhead.

---

# 🧠 Local Memory

F.R.I.D.A.Y. supports local persistent memory for storing useful information such as preferences and facts.

Example:

```text
User:
Remember that I prefer VS Code.

F.R.I.D.A.Y.:
I'll remember that.
```

Later:

```text
User:
What is my editor preference?

F.R.I.D.A.Y.:
You prefer VS Code.
```

Memory is stored locally rather than being dependent on a cloud memory service.

---

# 📟 Status, Overlay & System Tray Indicator

F.R.I.D.A.Y. ships a lightweight status layer plus an optional desktop overlay:

* `friday/ui/status.py` — state text formatting (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, …).
* `friday/ui/tray.py` — a system tray status indicator: formatted tooltips, icon
  identifiers, and menu-action hooks for system integration.
* `friday/ui/notify.py` — a thread-safe image/status event bus. Publishers (the
  image tool, the assistant progress phrase) never touch the UI directly.
* `friday/ui/overlay.py` — a frameless, always-on-top status chip (bottom-right)
  that expands to show the just-generated image plus the confirmation phrase.

The overlay is standard-library only (tkinter). It is opt-in: set
`FRIDAY_OVERLAY=1` and generated images are displayed automatically (verified on
this machine at 420×420 thumbnails). Prefer a plain tk.PhotoImage path when
Pillow is absent. Optional extras, best effort: `pywin32` enables click-through,
Pillow sharpens thumbnail scaling.

```powershell
# Opt-in inside F.R.I.D.A.Y.
$env:FRIDAY_OVERLAY = "1"

# Standalone demo with an existing image
python -m friday.ui.overlay --image output\generated_images\2026-10-12\image_001.png
```

> Note: earlier README drafts described a click-through desktop overlay with a
> WebSocket connection to a FastAPI backend. That architectured overlay does
> **not** exist here — the shipped overlay is fully in-process (no server). The
> optional **web dashboard** described later is a separate interface served by
> the local FastAPI adapter; it does not control the desktop overlay.


---

# 🔄 Real-Time Pipeline

The current voice pipeline follows this flow:

```text
Microphone
    ↓
Audio WebSocket
    ↓
VAD
    ↓
faster-whisper
    ↓
Transcript Buffer
    ↓
Question / Command Detector
    ↓
Natural Conversation Layer      ← chatter answered here, no LLM
    ↓
Context Resolver
    ↓
Fast Router
    │
    ├── Known command → Tool
    │
    └── Complex request → RAG / research → Bonsai
                            ↓
                       llama.cpp
    ↓
Response
    ↓
Kokoro TTS
    ↓
Speaker
```

---

# 🛠️ Tech Stack

| Component     | Technology       |
| ------------- | ---------------- |
| Language      | Python           |
| Interface     | Voice (wake word) + terminal text mode + local web dashboard |
| LLM           | Bonsai           |
| LLM Format    | GGUF             |
| Inference     | llama.cpp        |
| Image Generation | Qwen-Image-2.1 GGUF via stable-diffusion.cpp (`sd-cli`) |
| STT           | faster-whisper   |
| VAD           | Silero VAD       |
| TTS           | Kokoro ONNX / Piper |
| Embeddings    | all-MiniLM-L6-v2 (ONNX, local) |
| Retrieval     | hybrid vector + BM25 (self-contained) |
| Memory        | SQLite           |
| Communication | In-process event bus; optional FastAPI + WebSocket dashboard |
| Dashboard API | FastAPI + uvicorn (`friday/web/`)       |
| Dashboard UI  | React + TypeScript + Vite (`frontend/`) |
| ML Runtime    | ONNX Runtime     |
| Logging       | loguru           |
| OS            | Windows          |
| Configuration | YAML + env       |

---

# 📁 High-Level Project Structure

```text
F.R.I.D.A.Y/
│
├── friday/
│   ├── audio/               # audio capture helpers
│   ├── core/                # assistant, conversation, session, state,
│   │                        # wake word, natural_conversation.py
│   ├── intent/              # classifier, normalizer, router, fuzzy router
│   ├── planning/            # planner, plan models/validator/executor,
│   │                        # context_resolver.py
│   ├── rag/                 # chunker, embedder, lexical/BM25, retriever,
│   │                        # reranker, relevance filter, compressor
│   ├── reasoning/           # llamacpp_reasoner.py, llamacpp_server.py
│   ├── research/            # opt-in web research agent
│   ├── memory/              # local persistent memory
│   ├── tools/               # apps, browser, files, memory, registry
│   ├── safety/              # permissions, confirmation, validator
│   ├── response/            # response engine
│   ├── system_control/      # app/file/system control
│   ├── ui/                  # tray, status, notify (event bus), overlay (Tk chip)
│   ├── utils/               # logger, audit log, config validation, diagnostics
│   ├── verification/        # verifiers, formatters
│   ├── voice/               # VAD, STT, TTS, session manager, state machine
│   └── web/                 # optional local dashboard API (FastAPI + WebSocket)
│
├── frontend/                # optional React + TypeScript + Vite dashboard
│   └── src/                 # pages, components, state, styles
│
├── models/
│
├── scripts/
│
├── tests/                   # 139 test modules
│
├── config.yaml
├── main.py
├── requirements.txt
└── README.md
```

---

# ⚙️ Configuration

`config.yaml` holds the runtime configuration; environment variables take precedence where noted.

```yaml
wake_word: "friday"

security:            # fail-closed execution
  dry_run: true
  allow_real_execution: false

voice:               # VAD / STT / TTS device and model settings
listening:           # wake-word and auto-listen behaviour
brain:               # routing thresholds
reasoning:           # provider (llamacpp / ollama), model, endpoint, timeout

rag:                 # local knowledge base
  enabled: true
  retrieval_k: 15
  final_k: 5
  rerank: true
  hybrid: true

research:            # opt-in web research
  enabled: false

natural_conversation:
  enabled: true      # FRIDAY_NATURAL_CONVERSATION_ENABLED overrides

logging:
  level: "INFO"
  file: "logs/friday.log"
```

Common environment overrides (see `.env.example`):

```text
FRIDAY_REASONING_PROVIDER=llamacpp
LLAMACPP_BASE_URL=http://127.0.0.1:8080
FRIDAY_NATURAL_CONVERSATION_ENABLED=true
WEB_RESEARCH_ENABLED=false
```

---

# 🚀 Installation

## 1. Clone the repository

```powershell
git clone https://github.com/Abhinaybethi/F.R.I.D.A.Y.git

cd F.R.I.D.A.Y
```

## 2. Create a virtual environment

```powershell
python -m venv venv
```

Activate it:

```powershell
.\venv\Scripts\activate
```

## 3. Install dependencies

```powershell
pip install -r requirements.txt
```

---

# 🧠 Configure the Local Model

Place your GGUF model in your configured model directory.

Example:

```text
C:\AI\models\Bonsai-8B-Q1_0.gguf
```

Configure the model/server settings in the project configuration.

F.R.I.D.A.Y. can automatically detect an existing llama.cpp server and can start the server when required.

---

# 🔍 Run Diagnostics

Before starting the assistant:

```powershell
python main.py --diagnostics
```

This checks the local environment and important runtime components.

---

# ▶️ Start F.R.I.D.A.Y.

Voice mode:

```powershell
python main.py
```

Text mode:

```powershell
python main.py --text
```

Text mode is useful for testing the reasoning and command pipeline without using the microphone.

---

# 🖥️ Live Dashboard (Optional Web UI)

F.R.I.D.A.Y. ships with a local-first web dashboard that reads the **real** runtime: CPU/RAM/GPU
telemetry, service health, the active model, agents, tools, tasks, activity, voice state, and Qwen
image generation. It is an adapter over the existing assistant modules — starting it does not load
models or spawn extra inference servers until you actually send a chat, research, or image request.

## Start the dashboard

Build the frontend once (or use the Vite dev server), then run the API:

```powershell
cd frontend
npm install
npm run build
cd ..

python -m friday.web --host 127.0.0.1 --port 8420
```

Open <http://127.0.0.1:8420>. The backend serves `frontend/dist` when it exists.

For frontend development with hot reload:

```powershell
cd frontend
npm run dev
```

Vite runs on <http://127.0.0.1:5173> and proxies `/api` and `/ws` to port `8420`.

## How it stays honest

- Every number is measured on this machine (`psutil`, `nvidia-smi`); unavailable values render as
  `N/A` instead of zero-filled placeholders.
- When the backend is unreachable, the metrics rail says **Stale** and keeps the last known samples.
- Voice capture is owned by the desktop runtime. In the browser the pipeline shows **Awaiting
  input** and the orb stays inactive unless `capture_active` is genuinely `true`.
- Research and image results come from the real providers; failures are shown with the provider's
  actual error. No progress percentages or sources are invented.
- Destructive tool execution requires an explicit `confirm` flag; non-owned inference servers are
  never stopped.

## API surface

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/api/health` | process liveness and runtime state |
| `GET` | `/api/system/metrics` | CPU, RAM, GPU, disk samples |
| `GET` | `/api/system/health` | per-component health |
| `GET` | `/api/dashboard/overview` | initial dashboard state |
| `GET` | `/api/models`, `/api/models/active` | model inventory and active model |
| `GET` | `/api/agents`, `/api/agents/{id}` | agent registry |
| `GET` | `/api/tasks`, `/api/tasks/{id}` | task history |
| `GET` | `/api/activity` | persisted activity feed |
| `GET` | `/api/tools` | registered tools |
| `POST` | `/api/tools/{action}/execute` | controlled tool execution |
| `POST` | `/api/chat` | one conversation turn |
| `POST` | `/api/image/generate` | Qwen image generation |
| `GET` | `/api/image/history`, `/api/image/file` | generated images (path-traversal guarded) |
| `POST` | `/api/research` | opt-in web research |
| `GET` | `/api/voice/state` | real voice pipeline state |
| `GET` | `/api/knowledge/documents` | indexed documents |
| `GET` | `/api/workspace` | project and workspace summary |
| `WS` | `/ws/dashboard` | versioned live events (`v: 1`, monotonic `seq`) |

Metrics poll over REST; events arrive over a single shared WebSocket with exponential-backoff
reconnection. Activity is persisted to `data/dashboard/activity.json` (bounded to 500 entries).

## Dashboard tests

```powershell
python -m pytest tests/test_web_dashboard.py -q

cd frontend
npx tsc --noEmit
npx vitest run
npm run build
```

---

# 🧪 Example Commands

### Application Control

```text
Open Chrome
Open Notepad
Close Chrome
Minimize Chrome
Maximize Chrome
```

### Web

```text
Search Python tutorials
Search machine learning courses
```

### Context

```text
Search Python tutorials
Open the first result
```

### Memory

```text
Remember that I prefer VS Code
What is my editor preference?
```

### System

```text
What time is it?
Take screenshot
```

### Session

```text
Cancel
Stop
Goodbye
```

### Conversation (answered locally, no LLM)

```text
Hi
How are you?
Thanks
Okay
See you later
```

Compound requests that carry real work still go to the normal pipeline:

```text
Hi, how are you?                  → local
Okay, what is Node.js?            → LLM / knowledge base
Thanks, search for Python 3.14    → research + LLM
```

---

# 🔒 Security Model

F.R.I.D.A.Y. follows a **fail-closed execution model**.

Default:

```yaml
security:
  dry_run: true
  allow_real_execution: false
```

The execution layer is protected by a centralized permission gate.

Conceptually:

```text
LLM / User Intent
       ↓
Plan Validation
       ↓
Permission Gate
       ↓
Execution Policy
       ↓
Tool Executor
       ↓
Post-Action Verification
```

The LLM does **not** receive unrestricted operating-system access.

---

# 🧪 Testing

The project includes 133 test modules covering multiple layers:

```text
Unit Tests
Integration Tests
Routing Tests
Reasoning Tests
Natural Conversation Tests
Context / Anaphora Tests
RAG Tests
Audio Pipeline Tests
Tool Execution Tests
Security Gate Tests
```

Run the full suite:

```powershell
python -m pytest tests -q
```

Or the helper script:

```powershell
.\run_tests.ps1
```

Useful subsets:

```powershell
python -m pytest tests/test_natural_conversation.py -q
python -m pytest tests/test_context_integrity.py -q
python -m pytest tests/test_voice_architecture.py -q
```

Markers are declared in `pytest.ini` (`unit`, `integration`, `hardware`, `ollama`, `security`,
`release`). No test needs a cloud API; tests that require the microphone, live network, or a running
llama.cpp server are separated so the rest of the suite stays runnable offline.

Current state: `1220 passed / 38 failed`, where every remaining failure is a pre-existing
config-default/secret gate, live-network workflow, external-timeout, or environment-fixture issue —
not a conversation, routing, context, or voice regression.

Before describing the project as production-ready, performance and reliability numbers should be generated from reproducible test runs rather than manually claimed.

---

# ⚡ Measured Performance

Deterministic paths (no model involved), measured on the development machine:

| Path | Median latency | LLM calls |
| --- | --- | --- |
| `hi` | 0.70 ms | 0 |
| `how are you?` | 0.92 ms | 0 |
| `thanks` | 0.46 ms | 0 |
| `okay` | 0.42 ms | 0 |
| `see you later` | 1.15 ms | 0 |
| `open chrome` (command path) | sub-ms | 0 |
| Model-backed question | seconds (llama.cpp round trip) | 1 |

---

# 🎯 Design Goals

F.R.I.D.A.Y. is built around five principles:

### 1. Local First

Keep speech, reasoning, memory, and assistant processing on the user's machine whenever possible.

### 2. Fast Path First

Use deterministic software for deterministic tasks.

### 3. LLM Only When Needed

Use local LLM reasoning for requests that actually require language understanding or planning.

### 4. Fail Closed

Potentially dangerous system operations should require explicit permission.

### 5. Modular Architecture

Speech recognition, reasoning, routing, memory, tools, and TTS should remain replaceable components.

---

# 🛣️ Roadmap

* [x] Local speech recognition
* [x] Local VAD
* [x] Local LLM inference
* [x] GGUF model support
* [x] llama.cpp integration
* [x] Automatic llama.cpp server startup
* [x] Fast command routing
* [x] Deterministic natural conversation layer
* [x] Context & anaphora resolution
* [x] Local hybrid RAG knowledge base
* [x] Opt-in web research agent
* [x] Plan / goal execution with recovery
* [x] Local memory
* [x] Tool registry
* [x] Permission gate
* [x] Desktop overlay (tkinter status chip + generated-image viewer; opt-in `FRIDAY_OVERLAY=1`, optional pywin32 click-through)
* [x] Local image generation (Qwen-Image-2.1 via stable-diffusion.cpp — `python -m friday.image setup` installs a verified runtime + models; real 512×512 PNG verified on this machine)
* [x] Real-time audio pipeline
* [x] Text mode
* [ ] More Windows automation tools
* [ ] Better long-term memory retrieval
* [ ] More robust multi-step agent planning
* [ ] Improved GPU acceleration
* [ ] Expanded local model support

---

# 📜 License

MIT License.

---

# 👨‍💻 Author

**Abhinay Bethi**

Computer Science Engineer focused on:

* AI/ML
* Local LLM systems
* AI agents
* Backend engineering
* Full-stack development
* Computer vision
* Automation

GitHub: `https://github.com/Abhinaybethi`

---

## ⭐ Project Philosophy

F.R.I.D.A.Y. is not intended to be another chatbot with a microphone.

The goal is to build a **local AI agent that can perceive, reason, remember, and interact with the desktop while keeping the core intelligence on the user's own machine.**
