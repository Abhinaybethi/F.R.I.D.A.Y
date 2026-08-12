"""
VoiceSessionManager
===================
Manages the full lifecycle of a voice-input session:

    session = VoiceSessionManager(stt_config=..., listening_config=...)
    session.start_session()          # opens microphone ONCE

    while running:
        text = session.listen_once() # drain stale audio → wait for speech → transcribe

    session.stop_session()           # close microphone, release resources

Or as a context manager (recommended — guarantees clean shutdown on Ctrl+C):

    with VoiceSessionManager(...) as session:
        while True:
            text = session.listen_once()

State machine per utterance
---------------------------
    WAITING_FOR_SPEECH  →  LISTENING  →  TRANSCRIBING  →  TEXT_READY
           ↑_____________________________________________________|
"""

import numpy as np

from friday.voice.audio_input import AudioInput
from friday.voice.vad import VoiceActivityDetector
from friday.voice.speech_to_text import SpeechToText
from friday.voice.debug_audio import DebugAudioSaver
from friday.utils.logger import get_logger

logger = get_logger(__name__)

# Returned when VAD detected activity but Whisper produced no legible text.
_NO_SPEECH = "No clear speech detected."


class VoiceSessionManager:
    """
    Persistent voice session.

    The microphone stream is opened once in ``start_session()`` and closed
    once in ``stop_session()``.  ``listen_once()`` never opens or closes the
    hardware — it only drains stale audio, waits for speech, and transcribes.
    """

    def __init__(self, stt_config=None, listening_config=None, debug_config=None):
        self.stt_config = stt_config or {}
        self.listening_config = listening_config or {}
        debug_cfg = debug_config or {}

        self.audio = AudioInput()
        self.vad = VoiceActivityDetector()
        self.stt = SpeechToText(
            model_size=self.stt_config.get("model", "small.en"),
            device=self.stt_config.get("device", "cpu"),
            compute_type=self.stt_config.get("compute_type", "int8"),
            language=self.stt_config.get("language", "en"),
        )

        self.max_silence = self.listening_config.get("silence_timeout_seconds", 2.0)
        self.max_listen = self.listening_config.get("command_timeout_seconds", 10.0)
        self._session_active = False

        # Debug audio saving (disabled by default)
        self._debug_saver = DebugAudioSaver(
            directory=debug_cfg.get("directory", "debug_audio"),
            max_files=debug_cfg.get("max_files", 50),
            enabled=debug_cfg.get("save_audio", False),
            playback=debug_cfg.get("playback_audio", False),
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self) -> "VoiceSessionManager":
        """
        Open the microphone and prepare the VAD for continuous listening.
        Call this ONCE before entering your listen loop.
        Logs microphone diagnostics (device, sample rate, RMS, peak).
        """
        self.audio.start()
        self.vad.reset_states()
        self._session_active = True
        logger.info("[Session] Voice session started.")

        # --- Microphone diagnostics ---
        device_info = self.audio.get_device_info()
        logger.info(
            "[MIC] Input device : %s", device_info.get("device_name", "Unknown")
        )
        logger.info(
            "[MIC] Sample rate  : %d Hz | Channels: %d",
            device_info.get("sample_rate", 0),
            device_info.get("channels", 1),
        )

        levels = self.audio.sample_levels(duration=0.5)
        rms = levels["rms"]
        peak = levels["peak"]

        logger.info("[MIC] RMS: %.4f | Peak: %.4f", rms, peak)

        if rms < 0.001:
            logger.warning("[MIC] Very low RMS (%.4f) — microphone may be muted or silent.", rms)
        elif rms > 0.5:
            logger.warning("[MIC] High RMS (%.4f) — possible background noise or clipping.", rms)

        if peak > 0.95:
            logger.warning("[MIC] Peak near clipping (%.4f) — reduce input gain.", peak)

        return self

    def stop_session(self):
        """
        Close the microphone and release all audio resources.
        Call this once when the session is finished (Ctrl+C / shutdown).
        """
        self._session_active = False
        self.audio.stop()
        logger.info("[Session] Voice session stopped.")

    # ------------------------------------------------------------------
    # Context manager support (guarantees cleanup on Ctrl+C)
    # ------------------------------------------------------------------

    def __enter__(self) -> "VoiceSessionManager":
        return self.start_session()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_session()
        return False  # do not suppress exceptions

    # ------------------------------------------------------------------
    # Utterance capture
    # ------------------------------------------------------------------

    def listen_once(self) -> str:
        """
        Wait for a single utterance and return its transcription.

        The microphone stream must already be open (call ``start_session()`` first).

        Returns
        -------
        str
            Transcribed text (lower-cased), or:
            - ``""``          — silence / no speech detected within timeout.
            - ``_NO_SPEECH``  — VAD fired but Whisper returned no legible output.
        """
        if not self.audio.is_active():
            logger.warning(
                "[Session] listen_once called but microphone is not open. "
                "Call start_session() first."
            )
            return ""

        # Flush any audio that accumulated while we were busy transcribing.
        self.audio.drain()
        self.vad.reset_states()

        buffer = []
        is_speech = False
        silence_frames = 0
        speech_start_frame = None

        max_silence_frames = int(
            (self.max_silence * self.audio.sample_rate) / self.audio.chunk_size
        )
        max_wait_frames = int(
            (self.max_listen * self.audio.sample_rate) / self.audio.chunk_size
        )
        wait_frames = 0

        logger.info("WAITING_FOR_SPEECH")

        for chunk in self.audio.read_chunks():
            # -- pre-speech timeout (stop waiting if nobody speaks) --
            if not is_speech:
                wait_frames += 1
                if wait_frames > max_wait_frames:
                    break

            speech_detected = self.vad.is_speech(chunk)

            if speech_detected:
                if not is_speech:
                    logger.info("LISTENING")
                    is_speech = True
                    speech_start_frame = wait_frames
                silence_frames = 0
                buffer.append(chunk)
            else:
                if is_speech:
                    buffer.append(chunk)
                    silence_frames += 1
                    if silence_frames > max_silence_frames:
                        # End of utterance — trailing silence reached
                        break

        # No speech at all → silent / timeout
        if not buffer:
            return ""

        logger.info("TRANSCRIBING")
        audio_data = np.concatenate(buffer)
        audio_sec = len(audio_data) / self.audio.sample_rate

        # VAD segmentation diagnostics
        speech_start_sec = (
            (speech_start_frame or 0) * self.audio.chunk_size / self.audio.sample_rate
        )
        logger.debug(
            "[VAD] Speech started at ~%.2fs into listen window | captured %.2fs",
            speech_start_sec, audio_sec,
        )

        # Save debug WAV if enabled
        saved_path = self._debug_saver.save(audio_data, self.audio.sample_rate)
        self._debug_saver.maybe_playback(saved_path)

        text, rtf = self.stt.transcribe(audio_data)
        logger.info(
            "TEXT_READY | audio=%.1fs RTF=%.2f | %s",
            audio_sec, rtf, repr(text),
        )

        # VAD fired, but Whisper produced nothing legible
        if not text:
            return _NO_SPEECH

        return text
