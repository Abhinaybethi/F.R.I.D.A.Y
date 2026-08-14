# F.R.I.D.A.Y. Post-Release Failure Model (v1.0.0 -> v1.1)

Based on a post-release audit of the v1.0.0 architecture, the following realistic failure modes have been classified. This model serves as the foundation for the Phase 19 reliability improvements.

## 1. VOICE PIPELINE FAILURES
- **Whisper Misrecognition**: Names of specific local apps (e.g., "open Obsidian") recognized as "open up city in".
- **Background Noise**: Continuous ambient noise keeping VAD open, resulting in long, timeout-driven STT attempts.
- **Short Utterances / Clipped Speech**: "yes" or "stop" getting clipped by VAD thresholding, leading to missed confirmations.
- **VAD False Positives**: Keyboard typing triggering VAD, sending empty/junk audio to STT (wastes CPU).
- **VAD False Negatives**: Quiet speech not breaking the energy threshold, ignoring the user.

## 2. REASONING FAILURES
- **Ollama Unavailable**: The local Ollama daemon is shut down or restarting, causing a 60-second timeout freeze during inference.
- **Malformed JSON**: Llama 3 fails to respect the `format: "json"` constraint or produces invalid keys, causing fallback to `UNKNOWN`.
- **Hallucinated Intent**: LLM maps a conversational phrase to a destructive action (e.g., mapping "close that" to closing the wrong app).
- **Unnecessary Reasoning Invocation**: Highly predictable commands (e.g., "can you close chrome") failing the strict regex in `router.py` and invoking the heavy Ollama model, causing a 2-4 second latency spike instead of a 5ms deterministic response.

## 3. TOOL & EXECUTION FAILURES
- **Execution Failure**: `subprocess.run` fails to find the path, or the app takes too long to launch.
- **Verification Failure**: The verification step (e.g., checking if window exists) runs before the app has fully initialized, resulting in a false-negative failure report.
- **Hidden Coupling**: Tool output text (e.g., `[DRY RUN] Would open...`) is hard-coupled to TTS string-replacement hacks (`_clean_for_speech` in `text_to_speech.py`), meaning any change to tool text breaks the spoken UX.

## 4. CONVERSATION & STATE FAILURES
- **Confirmation Timeout**: User walks away during a `WAITING_FOR_CONFIRMATION` state; the system remains stuck waiting for "yes/no", misinterpreting the next unrelated command as a failed confirmation.
- **Stale Context**: "close it" refers to an app opened 20 minutes ago because context TTL (Time-To-Live) does not exist.

## 5. SYSTEM & OBSERVABILITY FAILURES
- **Lack of Request Correlation**: Logs from VAD, STT, Router, and TTS are interleaved in `friday.log`. It is impossible to definitively trace a single request end-to-end to answer "Why did this fail?".
- **Resource Exhaustion**: Thread/memory leaks over long uptime due to unmanaged `sounddevice` streams or infinite retry loops.
