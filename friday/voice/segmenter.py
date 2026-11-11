"""Utterance segmentation for the shared microphone.

One algorithm decides where speech starts and ends, for both the wake loop and
the barge-in monitor. Silero VAD (already shipped for the CLI path) is the
primary detector; a cheap adaptive RMS gate is used as a strong-energy safety
net and as the fallback when VAD is unavailable.

The segmenter works with *whatever block size* the caller feeds it, so it can
sit behind the :class:`~friday.voice.audio_hub.AudioHub` regardless of the
owner's block configuration. Timing is measured in samples, not frame counts,
which keeps short synthetic test blocks exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from friday.utils.logger import get_logger
from friday.voice.speech_evidence import block_has_speech_shape

logger = get_logger(__name__)

# Silero v4 expects fixed 512-sample windows at 16 kHz.
_SILERO_FRAME = 512


@dataclass
class SegmenterConfig:
    sample_rate: int = 16000
    onset_ms: int = 96
    silence_ms: int = 800
    min_speech_ms: int = 320
    max_utterance_ms: int = 12000
    pre_roll_ms: int = 192
    rms_floor: float = 0.004
    speech_ratio: float = 2.5

    def __post_init__(self) -> None:
        self.sample_rate = max(8000, int(self.sample_rate))
        self.onset_ms = max(32, int(self.onset_ms))
        self.silence_ms = max(100, int(self.silence_ms))
        self.min_speech_ms = max(32, int(self.min_speech_ms))
        self.max_utterance_ms = max(self.min_speech_ms, int(self.max_utterance_ms))
        self.pre_roll_ms = max(0, int(self.pre_roll_ms))
        self.rms_floor = max(0.0002, float(self.rms_floor))
        self.speech_ratio = max(1.5, float(self.speech_ratio))

    def samples(self, ms: float) -> int:
        return int(self.sample_rate * float(ms) / 1000.0)


class SpeechSegmenter:
    """Turn a stream of audio blocks into complete utterances."""

    def __init__(self, config: Optional[SegmenterConfig] = None, vad=None) -> None:
        """
        ``vad``:
          * ``None``  — load Silero VAD lazily (production default);
          * ``False`` — energy gate only (deterministic tests, no model);
          * object    — anything exposing ``is_speech(np.ndarray) -> bool``
                        and optionally ``reset_states()``.
        """
        self.cfg = config or SegmenterConfig()
        if vad is False:
            self._vad = None
        elif vad is None:
            self._vad = self._load_vad()
        else:
            self._vad = vad
        self._vad_buffer = np.zeros(0, dtype=np.float32)
        self._last_vad = False
        self._noise = self.cfg.rms_floor
        self.reset()

    # ------------------------------------------------------------------
    def _load_vad(self):
        try:
            from friday.voice.vad import VoiceActivityDetector

            return VoiceActivityDetector(sample_rate=self.cfg.sample_rate)
        except Exception as exc:  # pragma: no cover - depends on local model
            logger.warning("[VAD] Silero unavailable, using energy gate: %s", exc)
            return None

    @property
    def has_vad(self) -> bool:
        return self._vad is not None

    @property
    def noise_floor(self) -> float:
        return self._noise

    @property
    def speaking(self) -> bool:
        """True while an utterance has opened and has not yet been returned."""
        return self._speaking

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Drop any partial utterance (e.g. when the listener is paused)."""
        self._vad_buffer = np.zeros(0, dtype=np.float32)
        self._last_vad = False
        if self._vad is not None and hasattr(self._vad, "reset_states"):
            try:
                self._vad.reset_states()
            except Exception:
                pass
        self._pre_roll: List[np.ndarray] = []
        self._pre_roll_samples = 0
        self._onset_frames: List[np.ndarray] = []
        self._onset_samples = 0
        self._frames: List[np.ndarray] = []
        self._samples = 0
        self._voiced_samples = 0
        self._silence_samples = 0
        self._speaking = False

    def flush(self) -> Optional[np.ndarray]:
        """Force-close the current utterance (listener stopping mid-speech)."""
        if self._speaking:
            return self._finish()
        self.reset()
        return None

    # ------------------------------------------------------------------
    def feed(self, frame) -> Optional[np.ndarray]:
        """Consume one audio block; return a finished utterance if any."""
        data = np.asarray(frame, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return None

        voiced = self._is_speech(data)
        duration = int(data.size)

        if self._speaking:
            self._frames.append(data)
            self._samples += duration
            if voiced:
                self._voiced_samples += duration
                self._silence_samples = 0
            else:
                self._silence_samples += duration
            if self._silence_samples >= self.cfg.samples(self.cfg.silence_ms):
                return self._finish(complete=True)
            if self._samples >= self.cfg.samples(self.cfg.max_utterance_ms):
                return self._finish(complete=False)
            return None

        if voiced:
            self._onset_frames.append(data)
            self._onset_samples += duration
            if self._onset_samples >= self.cfg.samples(self.cfg.onset_ms):
                self._speaking = True
                self._frames = list(self._pre_roll) + list(self._onset_frames)
                self._samples = sum(int(f.size) for f in self._frames)
                self._voiced_samples = self._onset_samples
                self._silence_samples = 0
                self._pre_roll = []
                self._pre_roll_samples = 0
                self._onset_frames = []
                self._onset_samples = 0
        else:
            self._onset_frames = []
            self._onset_samples = 0
            self._append_pre_roll(data)
        return None

    # ------------------------------------------------------------------
    def _append_pre_roll(self, frame: np.ndarray) -> None:
        limit = self.cfg.samples(self.cfg.pre_roll_ms)
        if limit <= 0:
            return
        self._pre_roll.append(frame)
        self._pre_roll_samples += int(frame.size)
        while self._pre_roll and self._pre_roll_samples > limit:
            dropped = self._pre_roll.pop(0)
            self._pre_roll_samples -= int(dropped.size)

    def _finish(self, complete: bool = True) -> Optional[np.ndarray]:
        frames = self._frames
        voiced = self._voiced_samples
        limit = self.cfg.samples(self.cfg.max_utterance_ms)
        audio = np.concatenate(frames) if frames else None
        ok = audio is not None and voiced >= self.cfg.samples(self.cfg.min_speech_ms)
        if audio is not None and audio.size > limit:
            audio = audio[:limit]
        self.reset()
        if not complete:
            logger.info("[VAD] Utterance hit the length cap; dispatching truncated audio.")
        return audio if ok else None

    # ------------------------------------------------------------------
    def _is_speech(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(frame)) + 1e-12))
        base = max(self.cfg.rms_floor, self._noise * self.cfg.speech_ratio)

        # Track the quiet baseline. Only quiet frames influence it, so speech
        # cannot drag the gate upward.
        if rms < base:
            self._noise = 0.98 * self._noise + 0.02 * rms

        if self._vad is None:
            # Deterministic energy-only mode, kept exactly as before for tests
            # and for machines where Silero is unavailable. The spectral gate
            # below is only applied when a real VAD is in use, so the existing
            # ``vad=False`` contract does not change.
            return rms >= base

        # Strong energy alone is NOT enough: a desk knock or a mouse click is
        # loud but not speech. Loud frames may open the gate only when the
        # spectral evidence agrees that the block looks like speech.
        strong_energy = rms >= max(self.cfg.rms_floor * 4.0, base * 4.0)
        if not (self._silero_speech(frame) or strong_energy):
            return False
        return block_has_speech_shape(frame, self.cfg.sample_rate)

    def _silero_speech(self, frame: np.ndarray) -> bool:
        self._vad_buffer = np.concatenate([self._vad_buffer, frame])
        ran = False
        while self._vad_buffer.size >= _SILERO_FRAME:
            window = self._vad_buffer[:_SILERO_FRAME]
            self._vad_buffer = self._vad_buffer[_SILERO_FRAME:]
            try:
                self._last_vad = bool(self._vad.is_speech(window))
            except Exception as exc:  # pragma: no cover - model/runtime failure
                logger.warning("[VAD] inference failed, falling back to energy: %s", exc)
                self._vad = None
                return False
            ran = True
        if ran:
            return self._last_vad
        # No full Silero window yet: reuse the most recent decision (<= 32 ms).
        return self._last_vad
