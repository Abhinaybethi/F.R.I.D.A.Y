"""Always-on wake-word listening for the dashboard voice console.

The embedded dashboard browser refuses microphone access, so wake-word
detection runs on the backend: the machine microphone is segmented into
utterances by the shared :class:`~friday.voice.segmenter.SpeechSegmenter`
(Silero VAD with an energy safety net), each utterance is transcribed locally,
and the configured wake word (default "friday") opens a command window.
Commands are handed back to the conversation pipeline; the barge-in monitor
keeps listening while the reply is generated and spoken, with
:class:`~friday.voice.echo.EchoSuppressor` stopping FRIDAY's own voice from
being mistaken for the user.

Audio comes from the process-wide :class:`~friday.voice.audio_hub.AudioHub`,
so the dashboard never opens a second microphone stream. Wake/stop phrase
matching is shared with the CLI through :mod:`friday.voice.wake`. The
transcription callback is injected so the whole module can be tested without a
microphone or a model.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from friday.utils.logger import get_logger
from friday.voice.audio_hub import AudioHub, get_audio_hub
from friday.voice.echo import EchoSuppressor, get_playback_gate
from friday.voice.segmenter import SegmenterConfig, SpeechSegmenter
from friday.voice.wake import WakeMatcher, extract_wake_command as _extract_wake_command

logger = get_logger(__name__)

# Kept as a module-level re-export: callers/tests import it from here.
extract_wake_command = _extract_wake_command


def _is_stop_phrase(text: str) -> bool:
    return WakeMatcher().is_stop_phrase(text)


def _strip_wake_prefix(text: str, wake_word: str = "friday") -> str:
    return WakeMatcher(wake_word).strip_prefix(text)


@dataclass
class HandsFreeConfig:
    wake_word: str = "friday"
    sample_rate: int = 16000
    block_ms: int = 32
    silence_ms: int = 800
    min_speech_ms: int = 320
    max_utterance_ms: int = 12000
    pre_roll_ms: int = 192
    command_timeout_seconds: float = 12.0
    session_timeout_seconds: float = 300.0
    flush_timeout_seconds: float = 2.5
    rms_floor: float = 0.004
    speech_ratio: float = 2.5

    def __post_init__(self) -> None:
        self.block_ms = max(10, int(self.block_ms))
        self.sample_rate = max(8000, int(self.sample_rate))
        self.silence_ms = max(200, int(self.silence_ms))
        self.min_speech_ms = max(100, int(self.min_speech_ms))
        self.max_utterance_ms = max(self.min_speech_ms, int(self.max_utterance_ms))
        self.pre_roll_ms = max(0, int(self.pre_roll_ms))
        self.command_timeout_seconds = max(3.0, float(self.command_timeout_seconds))
        self.session_timeout_seconds = max(30.0, float(self.session_timeout_seconds))
        self.flush_timeout_seconds = max(1.5, float(self.flush_timeout_seconds))
        self.rms_floor = max(0.0005, float(self.rms_floor))
        self.speech_ratio = max(1.5, float(self.speech_ratio))


class HandsFreeListener:
    """Background wake-word listener with two-stage command capture."""

    def __init__(
        self,
        transcribe: Callable[[np.ndarray], str],
        on_command: Callable[[str], None],
        on_state: Optional[Callable[[str], None]] = None,
        on_wake: Optional[Callable[[str], None]] = None,
        on_acknowledge: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_session_end: Optional[Callable[[], None]] = None,
        interrupt: Optional[Callable[[], None]] = None,
        config: Optional[HandsFreeConfig] = None,
        vad=None,
        hub: Optional[AudioHub] = None,
        gate: Optional[EchoSuppressor] = None,
    ) -> None:
        self.cfg = config or HandsFreeConfig()
        self._transcribe = transcribe
        self._on_command = on_command
        self._on_state = on_state or (lambda _state: None)
        self._on_wake = on_wake or (lambda _text: None)
        self._on_acknowledge = on_acknowledge
        self._on_error = on_error or (lambda _message: None)
        self._on_session_end = on_session_end or (lambda: None)
        self._interrupt_tts = interrupt
        self._wake = WakeMatcher(self.cfg.wake_word)
        self._hub = hub or get_audio_hub()
        self._gate = gate or get_playback_gate()
        self._owner = "handsfree"
        self._subscriber_token: Optional[int] = None
        self._segmenter = SpeechSegmenter(self._segmenter_config(), vad=vad)

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream = None
        self._mode = "wake"  # "wake" | "command"
        self._state = "STOPPED"
        self._last_error = ""
        self._command_deadline = 0.0
        self._command_prompted = False
        self._session_active = False
        self._session_deadline = 0.0
        self._pending_commands: list[str] = []
        self._flush_deadline: float = 0.0
        self._pending_audio: Optional[np.ndarray] = None
        self._barge_stop = threading.Event()

        block = int(self.cfg.sample_rate * self.cfg.block_ms / 1000)
        self._block = max(128, block)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------
    def _segmenter_config(self) -> SegmenterConfig:
        return SegmenterConfig(
            sample_rate=self.cfg.sample_rate,
            silence_ms=self.cfg.silence_ms,
            min_speech_ms=self.cfg.min_speech_ms,
            max_utterance_ms=self.cfg.max_utterance_ms,
            pre_roll_ms=self.cfg.pre_roll_ms,
            rms_floor=self.cfg.rms_floor,
            speech_ratio=self.cfg.speech_ratio,
        )

    def _enqueue(self, frame: np.ndarray) -> None:
        self._queue.put(frame)

    def _base_threshold(self) -> float:
        noise = getattr(self._segmenter, "noise_floor", self.cfg.rms_floor)
        return max(self.cfg.rms_floor, noise * self.cfg.speech_ratio)

    def _gate_frame(self, chunk: np.ndarray) -> np.ndarray:
        """Blank a frame that is almost certainly FRIDAY's own playback."""
        if not self._gate.active():
            return chunk
        rms = float(np.sqrt(np.mean(np.square(chunk))) + 1e-9)
        if rms < self._gate.threshold(self._base_threshold(), rms):
            return np.zeros_like(chunk)
        return chunk

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def wake_word(self) -> str:
        return self.cfg.wake_word

    @property
    def session_active(self) -> bool:
        return self._session_active

    def start(self) -> bool:
        if self.active:
            return False
        self._stop.clear()
        self._paused.clear()
        self._mode = "wake"
        self._command_deadline = 0.0
        self._drain()
        self._segmenter.reset()
        self._thread = threading.Thread(target=self._run, name="friday-wake-word", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if not self.active:
            self._set_state("STOPPED")
            return False
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None
        self.end_session()
        self._set_state("STOPPED")
        return True

    def pause(self) -> None:
        self._paused.set()
        self._drain()

    def resume(self) -> None:
        self._drain()
        self._paused.clear()

    def start_session(self) -> None:
        self._session_active = True
        self._session_deadline = time.monotonic() + self.cfg.session_timeout_seconds

    def end_session(self) -> None:
        was_active = self._session_active
        self._session_active = False
        self._session_deadline = 0.0
        if was_active:
            # Give the owner a chance to reset its own copy of session context
            # so the listener and the conversation manager cannot drift apart.
            try:
                self._on_session_end()
            except Exception as exc:  # callback must never kill the audio loop
                logger.debug("[WAKE] session-end callback failed: %s", exc)

    def _flush_pending(self) -> None:
        if not self._pending_commands:
            return
        combined = " ".join(self._pending_commands)
        self._pending_commands = []
        self._flush_deadline = 0.0
        logger.info("[WAKE] Flushing accumulated questions: %r", combined[:200])
        self._dispatch(combined)

    def _acknowledge(self) -> None:
        """Reply out loud to a bare wake word ("Yes Abhi" / "Yes boss").

        Playback blocks the audio loop, so anything FRIDAY hears while it is
        talking is its own echo. Drop those frames and reset the segmenter
        before resuming normal listening.
        """
        if self._on_acknowledge is None:
            return
        try:
            self._on_acknowledge()
        except Exception as exc:  # callback must never kill the audio loop
            logger.debug("[WAKE] acknowledgment callback failed: %s", exc)
        finally:
            self._drain()
            self._segmenter.reset()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        try:
            self._on_state(state)
        except Exception as exc:  # pragma: no cover - callback must never kill the loop
            logger.debug("[WAKE] state callback failed: %s", exc)

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _run(self) -> None:
        try:
            import sounddevice  # noqa: F401  (fail early with a clear message)
        except Exception as exc:
            self._last_error = f"audio subsystem unavailable: {exc}"
            self._on_error(self._last_error)
            self._set_state("ERROR")
            return

        try:
            self._hub.acquire(self._owner, block_ms=self.cfg.block_ms)
            self._subscriber_token = self._hub.subscribe(self._enqueue)
        except Exception as exc:
            self._last_error = f"microphone unavailable: {exc}"
            self._on_error(self._last_error)
            self._set_state("ERROR")
            self._release_audio()
            return

        logger.info("[WAKE] Listening for '%s' on the machine microphone.", self.cfg.wake_word)
        self._set_state("WAKE_LISTENING")
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    self._drain()
                    time.sleep(0.05)
                    continue
                # Expire an idle active session so we return to wake-word gating.
                if self._session_active and time.monotonic() > self._session_deadline:
                    self._flush_pending()
                    self.end_session()
                    self._set_state("WAKE_LISTENING")
                    logger.info("[WAKE] Session expired; back to wake-word listening.")
                # Flush accumulated commands after a long pause (single combined answer).
                if self._pending_commands and time.monotonic() > self._flush_deadline:
                    self._flush_pending()
                if self._mode == "command" and time.monotonic() > self._command_deadline:
                    self._mode = "wake"
                    self._command_prompted = False
                    self._set_state("WAKE_LISTENING")
                    logger.info("[WAKE] Command window closed; back to wake-word listening.")
                if self._pending_audio is not None:
                    utterance = self._pending_audio
                    self._pending_audio = None
                else:
                    utterance = self._capture_utterance()
                if utterance is None:
                    continue
                try:
                    text = (self._transcribe(utterance) or "").strip()
                except Exception as exc:
                    logger.warning("[WAKE] transcription failed: %s", exc)
                    continue
                if not text:
                    continue
                self._handle_text(text)
        finally:
            self._release_audio()
            self._drain()
            logger.info("[WAKE] Listener stopped.")

    def _release_audio(self) -> None:
        token = self._subscriber_token
        self._subscriber_token = None
        if token is not None:
            try:
                self._hub.unsubscribe(token)
            except Exception:
                pass
        try:
            self._hub.release(self._owner)
        except Exception:
            pass

    def _capture_utterance(self, max_wait_seconds: float = 0.25) -> Optional[np.ndarray]:
        """Return one completed speech segment, or None while idle/paused.

        Segmentation (Silero VAD + energy safety net) lives in the shared
        segmenter; echo frames produced by FRIDAY's own TTS are blanked before
        they can open the gate.

        The wait is time-sliced: the microphone stream is continuous, so the
        queue is rarely empty. Returning None periodically lets ``_run`` check
        the flush, session, and command-window timers even when no utterance
        has finished yet. The segmenter keeps its partial utterance.
        """
        deadline = time.monotonic() + max(0.01, float(max_wait_seconds))
        while not self._stop.is_set():
            if self._paused.is_set():
                self._segmenter.reset()
                return None
            try:
                chunk = self._queue.get(timeout=0.15)
            except queue.Empty:
                # Hand control back to _run so it can expire the command
                # window, the session, and the multi-question flush timer.
                # The segmenter keeps its partial utterance across calls.
                return None
            chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if chunk.size == 0:
                continue
            utterance = self._segmenter.feed(self._gate_frame(chunk))
            if utterance is not None:
                return utterance.astype(np.float32)
            if time.monotonic() >= deadline:
                return None
        return None

    def _handle_text(self, text: str) -> None:
        # Active session: every utterance is a command (no wake word needed)
        # until the user says "stop" or the session times out.
        if self._session_active:
            if time.monotonic() > self._session_deadline:
                self._session_active = False
            else:
                if _is_stop_phrase(text):
                    logger.info("[WAKE] Stop phrase heard; flushing and ending session.")
                    # Flush what the user already asked, then close the session.
                    # The stop utterance itself is not a command.
                    self._flush_pending()
                    self.end_session()
                    self._mode = "wake"
                    self._set_state("WAKE_LISTENING")
                    return
                # Strip a repeated wake prefix mid-session. A bare wake word
                # (including a Whisper alias such as "fridays") is an ack,
                # never a question: only accumulate real trailing content.
                stripped = _strip_wake_prefix(text, self.cfg.wake_word)
                if stripped != (text or "").strip():
                    candidate = stripped
                else:
                    detected, wake_command = self._wake.extract(text)
                    candidate = wake_command if detected else (text or "").strip()
                if len(candidate) < 2:
                    # Bare wake repeated mid-session — re-ack, keep listening.
                    try:
                        self._on_wake(text)
                    except Exception:
                        pass
                    self._acknowledge()
                    self._set_state("COMMAND_LISTENING")
                    return
                # Accumulate instead of answering immediately.
                logger.info("[WAKE] Accumulated question: %r", candidate[:120])
                self._pending_commands.append(candidate)
                self._flush_deadline = time.monotonic() + self.cfg.flush_timeout_seconds
                self._session_deadline = time.monotonic() + self.cfg.session_timeout_seconds
                try:
                    self._on_wake(text)
                except Exception:
                    pass
                self._set_state("COMMAND_LISTENING")
                return

        detected, command = extract_wake_command(text, self.cfg.wake_word)

        if self._mode == "command":
            candidate = command if command else text.strip()
            if len(candidate) >= 2:
                if not _is_stop_phrase(candidate):
                    self._pending_commands.append(candidate)
                    self._flush_deadline = time.monotonic() + self.cfg.flush_timeout_seconds
                    if not self._session_active:
                        self.start_session()
                    self._session_deadline = time.monotonic() + self.cfg.session_timeout_seconds
                else:
                    self._pending_commands.append(candidate)
                    self._flush_pending()
                    self.end_session()
            # Reset mode after handling.
            self._mode = "wake"
            if self._session_active:
                self._set_state("COMMAND_LISTENING")
            else:
                self._set_state("WAKE_LISTENING")
            return

        if not detected:
            logger.debug("[WAKE] Ignored non-wake speech: %r", text[:80])
            return

        # Wake word detected — start an active session.
        if not command:
            # Bare wake word: acknowledge immediately, before the (possibly
            # slow) first assistant load, so the user hears a reply.
            self._acknowledge()
        try:
            self._on_wake(text)
        except Exception:
            pass
        self.start_session()

        if command:
            if _is_stop_phrase(command):
                self._pending_commands.append(command)
                self._flush_pending()
                self.end_session()
                self._set_state("WAKE_LISTENING")
                return
            logger.info("[WAKE] Accumulated question: %r", command[:120])
            self._pending_commands.append(command)
            self._flush_deadline = time.monotonic() + self.cfg.flush_timeout_seconds
            self.start_session()
            self._session_deadline = time.monotonic() + self.cfg.session_timeout_seconds
            self._set_state("COMMAND_LISTENING")
            return

        logger.info("[WAKE] Wake word detected; waiting for command.")
        self._mode = "command"
        self._command_deadline = time.monotonic() + self.cfg.command_timeout_seconds
        self._command_prompted = True
        self._set_state("COMMAND_LISTENING")

    def _dispatch(self, command: str) -> None:
        command = command.strip()
        if len(command) < 2:
            return
        self._mode = "wake"
        self._command_deadline = 0.0
        self._command_prompted = False
        self._barge_stop.clear()
        self._pending_audio = None
        self._set_state("PROCESSING")
        monitor = threading.Thread(target=self._barge_monitor, name="friday-barge-in", daemon=True)
        monitor.start()
        try:
            self._on_command(command)
        except Exception as exc:
            logger.warning("[WAKE] command pipeline failed: %s", exc)
        finally:
            # Give the barge-in monitor a moment to finalise any captured
            # speech before forcing it to stop.
            monitor.join(timeout=1.5)
            if monitor.is_alive():
                self._barge_stop.set()
                monitor.join(timeout=1.0)
            # Drop stale audio unless a barge-in captured new speech.
            if self._pending_audio is None:
                self._drain()
            if self._session_active:
                self._set_state("COMMAND_LISTENING")
            else:
                self._set_state("WAKE_LISTENING")

    def _barge_monitor(self) -> None:
        """Watch the microphone while the assistant is processing/speaking.

        When speech is detected we (a) interrupt TTS playback and (b) capture
        the utterance so it becomes the next command without re-waking.
        FRIDAY's own playback is gated out first: frames that sit at or below
        the learned echo floor are fed to the segmenter as silence.
        """
        # Preserve the detector mode chosen for the wake loop: an energy-only
        # listener must not silently reload Silero just for barge-in, and a
        # loaded detector is reused instead of being rebuilt every turn.
        barge_vad = self._segmenter._vad if self._segmenter.has_vad else False
        segmenter = SpeechSegmenter(self._segmenter_config(), vad=barge_vad)
        deadline = time.monotonic() + 60.0

        while not self._barge_stop.is_set() and time.monotonic() < deadline:
            try:
                chunk = self._queue.get(timeout=0.15)
            except queue.Empty:
                continue
            chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
            if chunk.size == 0:
                continue

            was_speaking = segmenter.speaking
            utterance = segmenter.feed(self._gate_frame(chunk))
            if segmenter.speaking and not was_speaking and self._interrupt_tts is not None:
                try:
                    self._interrupt_tts()
                except Exception:
                    pass
            if utterance is not None:
                self._pending_audio = utterance.astype(np.float32)
                return
