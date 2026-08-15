# Phase 20 Implementation Plan

## Overview
F.R.I.D.A.Y. v1.0 is technically robust but practically constrained. Phase 20 aims to transform the system into a genuinely useful daily assistant by addressing severe gaps in memory, context, file retrieval, web reading, and speech interruption.

## Initiatives

### 1. [P0] Explicit Local Memory (Remember & Recall)
- **Problem**: The assistant has total amnesia across sessions and cannot remember preferences, notes, or facts.
- **Evidence**: Users expect a personal assistant to store information. Currently, "Remember my wife's birthday" is forgotten immediately.
- **User Benefit**: Ability to store and retrieve personal knowledge locally.
- **Architecture**:
  - `friday/memory/persistent.py` using SQLite database (`memory.db`).
  - New Intents: `Action.REMEMBER` and `Action.RECALL`.
  - Strictly local, user-auditable, and deletable.
- **Files Affected**: `friday/intent/models.py`, `friday/intent/router.py`, `friday/tools/memory.py` [NEW].
- **Security Implications**: Database must be stored locally in app data. No sensitive transcripts logged automatically.
- **Performance Implications**: Negligible (local SQLite read/write is ~1ms).
- **Acceptance Criteria**: User can say "Remember X" and later ask "What is X?" across app restarts.

### 2. [P1] N-Turn Rolling Context (Conversational Memory)
- **Problem**: Context resolution fails after more than 1 turn, making follow-ups unnatural.
- **Evidence**: Saying "Open Chrome", followed by a web search, followed by "Close it" fails because "it" is too far back or overridden.
- **User Benefit**: Natural conversation flow without repeating subjects.
- **Architecture**:
  - `ConversationContext` expanded to store an N-turn ring buffer (e.g., last 5 intents and targets).
- **Files Affected**: `friday/core/conversation.py`, `friday/planning/context_resolver.py`.
- **Security Implications**: In-memory only. Drops when the app restarts.
- **Performance Implications**: Negligible.
- **Acceptance Criteria**: Anaphora ("it", "that") works across 3+ consecutive relevant interactions.

### 3. [P1] Intelligent File Retrieval (Recency & Type Filters)
- **Problem**: `find_file` uses raw globbing which is too slow or returns useless technical files instead of user documents.
- **Evidence**: "Find my latest resume" returns nothing useful or takes 10 seconds scanning `node_modules`.
- **User Benefit**: Instantly find personal files, documents, and downloads.
- **Architecture**:
  - Overhaul `files.py` to support `file_type` and `sort=recency`.
  - Restrict default search paths to Documents, Desktop, Downloads.
- **Files Affected**: `friday/tools/files.py`.
- **Security Implications**: Prevents accidental traversal of system directories (Windows/System32).
- **Performance Implications**: Massive speedup due to targeted directory scanning.
- **Acceptance Criteria**: "Find my latest PDF" opens the most recently downloaded PDF in <1s.

### 4. [P1] Robust TTS Barge-In (Interrupting Speech)
- **Problem**: Users cannot easily stop the assistant when it reads long text. VAD detects the interruption, but TTS pipelines keep playing.
- **Evidence**: "Stop" registers as a command, but audio continues overlapping for several seconds.
- **User Benefit**: Immediate silence on command, making the assistant feel responsive rather than robotic.
- **Architecture**:
  - Introduce an `abort_event` threading primitive passed into the `text_to_speech.py` audio playback loop.
  - VAD layer triggers `abort_event.set()` upon detecting valid human speech.
- **Files Affected**: `friday/voice/text_to_speech.py`, `friday/voice/vad.py`, `friday/core/conversation.py`.
- **Security Implications**: None.
- **Performance Implications**: Stops audio I/O earlier, saving CPU.
- **Acceptance Criteria**: Saying "Stop" during a 10-second response silences the audio within 500ms.

### 5. [P2] Web Page Reading (Read-only Extraction)
- **Problem**: The assistant can search the web but cannot read the answers.
- **Evidence**: "Search for jobs and open the first useful result" fails because it cannot read DOM.
- **User Benefit**: Assistant can actually answer questions from live web results.
- **Architecture**:
  - New `Action.READ_WEBSITE` using a basic HTTP GET request and HTML-to-text parser (e.g., BeautifulSoup).
  - No JS execution, purely read-only text extraction.
- **Files Affected**: `friday/tools/browser.py`, `friday/intent/models.py`.
- **Security Implications**: Prevents arbitrary JS execution. Data extracted must be sanitized before passing to reasoner.
- **Performance Implications**: Adds HTTP latency (1-3s).
- **Acceptance Criteria**: "Summarize wikipedia.org/wiki/Python" returns a 2-sentence spoken summary.

## Implementation Order
1. **P0** - Explicit Local Memory
2. **P1** - N-Turn Rolling Context
3. **P1** - Intelligent File Retrieval
4. **P1** - Robust TTS Barge-In
5. **P2** - Web Page Reading
