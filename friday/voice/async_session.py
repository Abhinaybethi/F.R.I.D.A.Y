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

    def start_barge_in_listener(self):
        """Start background VAD monitoring thread while TTS is outputting audio."""
        self._stop_event.clear()
        self._barge_in_triggered = False
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
        logger.debug("[ASYNC SESSION] Barge-in monitor started.")
        while not self._stop_event.is_set() and self.tts.is_speaking():
            try:
                # Check VAD status on incoming audio chunk
                if hasattr(self.session_manager, "vad") and self.session_manager.vad:
                    audio_chunk = self.session_manager.audio_input.read_chunk()
                    if audio_chunk is not None and len(audio_chunk) > 0:
                        is_speech, _ = self.session_manager.vad.process_chunk(audio_chunk)
                        if is_speech:
                            logger.info("[ASYNC SESSION] User speech detected mid-TTS output. Triggering barge-in stop.")
                            self.tts.stop()
                            self._barge_in_triggered = True
                            break
            except Exception as e:
                logger.debug("[ASYNC SESSION] Monitor exception: %s", e)
                break
            time.sleep(0.02)
