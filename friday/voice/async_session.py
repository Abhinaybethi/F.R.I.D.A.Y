"""
Asynchronous Voice Session & Real Hardware Barge-In Manager for F.R.I.D.A.Y. Phase 14 (P0).

Provides a background VAD listener thread during TTS audio playback.
If user speech is detected while TTS is speaking, it invokes tts.stop() immediately.
"""
import threading
import time
from typing import Optional

from friday.voice.session_manager import VoiceSessionManager
from friday.voice.text_to_speech import TextToSpeech
from friday.utils.logger import get_logger

logger = get_logger(__name__)


class AsyncVoiceSessionManager:
    """
    Wraps VoiceSessionManager with asynchronous VAD monitoring to support live hardware barge-in.
    """
    def __init__(self, session_manager: VoiceSessionManager, tts: TextToSpeech):
        self.session_manager = session_manager
        self.tts = tts
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._barge_in_triggered = False
        # Captured mic chunks from the moment the user interrupts TTS output.
        # Handed to the main loop so the interrupt utterance is NOT lost to
        # AudioInput.drain() on the next listen (barge-in continuity).
        self._barge_capture_max = 24  # ~0.75s @ 512/16k — bounds memory
        self._barge_in_chunks: list = []

    def take_barge_in_audio(self) -> list:
        """Return captured interrupt audio and reset the barge-in state."""
        chunks = list(self._barge_in_chunks)
        self._barge_in_chunks = []
        self._barge_in_triggered = False
        return chunks

    def start_barge_in_listener(self):
        """Start background VAD monitoring thread while TTS is outputting audio."""
        self._stop_event.clear()
        self._barge_in_triggered = False
        self._barge_in_chunks = []
        self._empty_reads = 0
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_barge_in_listener(self):
        """Stop background VAD monitoring thread."""
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=0.5)

    def is_barge_in_triggered(self) -> bool:
        return self._barge_in_triggered

    def _monitor_loop(self):
        """Background thread loop checking VAD while TTS is speaking."""
        import queue
        logger.debug("[ASYNC SESSION] Barge-in monitor started.")
        while not self._stop_event.is_set():
            # 1) ---------- capture phase (user already interrupted) ----------
            if self._barge_in_triggered:
                try:
                    audio_chunk = self.session_manager.audio.queue.get(timeout=0.05)
                except queue.Empty:
                    self._empty_reads += 1
                    if self._empty_reads >= 2:
                        break
                    continue
                self._barge_in_chunks.append(audio_chunk)
                self._empty_reads = 0
                if len(self._barge_in_chunks) >= self._barge_capture_max:
                    break
                continue

            # 2) ---------- detection phase (TTS still playing) ----------
            if not self.tts.is_speaking():
                break
            try:
                audio_chunk = self.session_manager.audio.queue.get(timeout=0.05)
            except queue.Empty:
                self._empty_reads += 1
                # No mic audio while TTS plays is abnormal (the stream keeps
                # producing chunks) and would otherwise spin forever.
                if self._empty_reads >= 50:
                    break
                continue
            self._empty_reads = 0
            try:
                is_speech = self.session_manager.vad.is_speech(audio_chunk)
            except Exception as e:
                logger.debug("[ASYNC SESSION] VAD error: %s", e)
                continue
            if is_speech:
                logger.info(
                    "[ASYNC SESSION] User speech detected mid-TTS output. "
                    "Triggering barge-in stop."
                )
                # Keep this first speech chunk: it is the (lost-in-the-old
                # design) head of the user's interrupt utterance.
                self._barge_in_chunks.append(audio_chunk)
                self._barge_in_triggered = True
                self._empty_reads = 0
                self.tts.stop()
            time.sleep(0.01)
