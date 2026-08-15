# Phase 20 Product Audit

## 1. Capability Map (Current State)
F.R.I.D.A.Y. v1.0 currently possesses the following functional primitives:

- **A (Reliable & Useful):**
  - **Deterministic Routing**: Extremely fast (<1ms), highly reliable for exact or normalized phrasing.
  - **Permission & Security Model**: Extremely robust validation, confirmation, and sandbox isolation.
  - **Desktop Controls**: System time, minimize, maximize.
- **B (Implemented but Rough):**
  - **Basic App & Website Launching**: Relies on naive OS execution (`os.startfile`, `webbrowser.open`). Cannot handle ambiguity gracefully.
  - **Multi-Step Planner**: Works for clean inputs ("do X then Y"), but brittle if steps fail midway.
- **C (Technically Implemented but Practically Weak):**
  - **File Retrieval**: `find_file` uses basic string matching/globbing. Fails at natural requests like "Find my latest resume".
  - **Local Reasoner (Ollama)**: Reliable as a fallback, but introduces multi-second latency for simple conversational misses.
  - **Barge-In / TTS Interruption**: Conceptually tested, but stopping a pipelined audio stream smoothly in real-time remains difficult and unnatural.
- **D (Dead/Legacy/Redundant):**
  - Legacy regex fallbacks inside TTS output streams (removed in Phase 19).
- **E (Missing but Important):**
  - **Contextual Memory**: Limited to *exactly one* previous turn.
  - **Persistent Storage**: Total amnesia between sessions.
  - **Browser Reading**: Can open URLs, but cannot read or summarize what's on the page.

## 2. Daily Assistant Gap Analysis
Evaluating against daily workflows reveals major practical gaps:
- **"Find my latest resume"**: *Fails.* System lacks recency filtering or semantic file types.
- **"Search for jobs and open the first useful result"**: *Fails.* System can execute a web search, but cannot read DOM/results to click the first link.
- **"Remember my wife's birthday is June 10th"**: *Fails.* No persistent memory architecture exists.
- **"What did I ask you earlier?"**: *Fails.* Short-term context only stores `last_transcript`, not the history of the session.
- **User interrupts F.R.I.D.A.Y.**: *Rough.* VAD captures the interruption, but TTS abort signaling lacks seamless integration, leading to overlapping audio.

## 3. Memory Architecture Assessment
**Current State:**
- **Short-Term**: 1-turn state (`last_transcript`, `last_tool_result`).
- **Session Memory**: None.
- **Persistent Memory**: None.

**Conclusion:** Persistent memory is genuinely required for a *personal* assistant, but it must be heavily constrained.
- **Rule**: It must NOT automatically log entire conversations (privacy hazard).
- **Rule**: It MUST be explicit (e.g., "Remember that...", "Save this note").
- **Rule**: It MUST be 100% local (SQLite) and user-deletable.

## 4. Tool Ecosystem & Reasoner Audit
- **Tools**: `open_app`, `open_website`, and `get_time` are safe and observable. `find_file` is the weakest link and needs an overhaul. We lack a "Read Webpage" read-only tool.
- **Reasoner**: Ollama is highly valuable for edge cases and multi-step planning, but its 2-5 second latency penalty makes it unsuitable for the critical path. It must remain strictly a fallback.

## 5. UX & Privacy Audit
- **UX Weakness**: The assistant lacks a conversational short-term memory (N-turns). If you say "Open Chrome" and then "Actually, close it", the anaphora resolution often struggles because the history is too shallow.
- **Privacy Strength**: Transcripts are not sent to the cloud. Ollama is local. `dry_run` defaults to true.
- **Privacy Hazard**: Adding memory or web reading requires strict local-only sandboxing to ensure parsed webpage data isn't inadvertently leaked.

## 6. What Should NOT Be Built
- **Cloud LLM Integration**: Breaks the local-first security invariant.
- **Unrestricted Agentic Computer Use (Click/Type)**: Highly dangerous. We will rely on OS-level hooks, not arbitrary screen coordinate clicking.
- **Vector DB for Memory**: Overkill. SQLite with standard text search/FTS is perfectly sufficient and massively lighter for personal notes.
