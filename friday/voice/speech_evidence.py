"""Acoustic speech-evidence analysis for microphone frames.

Why this module exists
----------------------
The hands-free microphone sees more than the user's voice: desk knocks, mouse
clicks, keyboard taps, fan hum and room transients. Silero VAD is good at
speech/non-speech, but a *loud* broadband transient can still look like
activity to an energy gate (and Whisper will happily hallucinate a word such
as "boom." from a bump).

This module adds a deterministic, model-free second opinion based purely on
the spectral shape of the audio:

* speech carries most of its energy in the 250-4000 Hz band;
* speech is not spectrally flat (harmonics / formants), unlike clicks and
  white-noise bursts;
* speech has bounded zero-crossing rate and visible periodicity in the
  pitch range.

The result is used in two places:

1. :class:`~friday.voice.segmenter.SpeechSegmenter` — a frame may only count
   as speech when it is both VAD-positive *and* speech-shaped. Loud energy
   alone no longer bypasses the check.
2. The transcription boundary — a captured utterance whose active frames are
   mostly not speech-shaped is dropped before STT, so Whisper never sees a
   knock and never invents a transcript from it.

No thresholds here are used to reject quiet *genuine* speech: the features
are amplitude-independent (ratios), and the utterance gate works on the
proportion of active frames that look like speech, not on loudness.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import numpy as np

# Speech band used for the band-energy ratio.
_BAND_LOW = 250.0
_BAND_HIGH = 4000.0
# Limits of the spectrum we analyse (ignore DC and near-Nyquist rumble).
_SPEC_LOW = 50.0
_SPEC_HIGH = 7800.0
# Pitch search range for the periodicity proxy.
_PITCH_LOW = 80.0
_PITCH_HIGH = 400.0

# A frame is speech-shaped when all of these hold. The thresholds were
# calibrated against 13 real captured utterances (all genuine speech) and
# synthetic knocks, clicks, thuds, white noise and mains hum:
#
#   feature      real speech (10th-90th pct)   disturbances
#   flatness     0.003 - 0.074                 thud 0.19, white 0.53, click 1.0
#   band ratio   0.15  - 0.90                  hum/knock ~0.0
#   ZCR          0.01  - 0.10                  white 0.52
#
# Flatness (how tone-like vs noise-like the spectrum is) is the strongest
# discriminator; the band ratio rejects low-frequency rumble that is equally
# "unflat". Periodicity is deliberately *not* required: breathy and quiet
# speech can have a weak autocorrelation peak, and the other features already
# reject the disturbances we see.
MIN_BAND_RATIO = 0.12
MAX_FLATNESS = 0.12
MAX_ZCR = 0.28

# Second acceptance path for genuinely quiet / noisy speech. Microphone noise
# raises spectral flatness and zero-crossing rate, so a strict flatness gate
# alone rejects a soft voice at low SNR. Voiced speech still shows a clear
# periodicity peak in the pitch range, which clicks, thuds and white noise do
# not. This path is deliberately wider but *requires* that periodicity.
MAX_NOISY_FLATNESS = 0.50
MAX_NOISY_ZCR = 0.42
MIN_NOISY_PERIODICITY = 0.28
MIN_NOISY_BAND_RATIO = 0.15

# Utterance-level gate.
FRAME_MS = 32
FRAME_SAMPLES = 512
MIN_SPEECH_FRAMES = 3          # >= ~96 ms of speech-shaped audio
MIN_SPEECH_RATIO = 0.55        # of the *active* (non-silent) frames
MIN_UTTERANCE_SECONDS = 0.30
# A frame is "active" when it is meaningfully above the utterance's noise
# floor. Both parts are amplitude-independent, so quiet speech is not rejected:
#   * at least 5% of the loudest frame, and
#   * well above the quietest decile of frames (estimated microphone noise).
ACTIVE_RELATIVE_FLOOR = 0.05
ACTIVE_NOISE_MULTIPLIER = 2.5
NOISE_FLOOR_CAP = 0.10         # never let the noise estimate exceed 10% of peak


@dataclass(frozen=True)
class FrameEvidence:
    """Spectral evidence for one short frame."""

    rms: float
    peak: float
    crest: float
    zcr: float
    band_ratio: float
    flatness: float
    periodicity: float
    speech_like: bool


def _as_mono(frame) -> np.ndarray:
    data = np.asarray(frame, dtype=np.float32).reshape(-1)
    if data.size == 0:
        return data
    if not np.all(np.isfinite(data)):
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    return data


def _autocorrelation_periodicity(spec_power: np.ndarray, sample_rate: int) -> float:
    """Normalised autocorrelation peak in the pitch lag range (0..1)."""
    acf = np.fft.irfft(spec_power)
    if acf.size == 0 or acf[0] <= 1e-12:
        return 0.0
    acf = acf / acf[0]
    low_lag = max(1, int(sample_rate / _PITCH_HIGH))
    high_lag = min(acf.size - 1, int(sample_rate / _PITCH_LOW))
    if high_lag <= low_lag:
        return 0.0
    peak = float(np.max(acf[low_lag:high_lag + 1]))
    return max(0.0, min(1.0, peak))


def analyse_frame(frame, sample_rate: int = 16000) -> FrameEvidence:
    """Return spectral evidence for ``frame`` (float32 mono, any length)."""
    data = _as_mono(frame)
    if data.size < 16:
        return FrameEvidence(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, False)

    samples = int(sample_rate)
    window = np.hanning(data.size).astype(np.float32)
    centred = data - float(np.mean(data))
    spectrum = np.fft.rfft(centred * window)
    power = np.abs(spectrum) ** 2
    freqs = np.fft.rfftfreq(data.size, d=1.0 / samples)

    rms = float(np.sqrt(np.mean(np.square(data)) + 1e-12))
    peak = float(np.max(np.abs(data)))
    crest = peak / rms if rms > 1e-9 else 0.0
    zcr = float(np.mean(np.abs(np.diff(np.signbit(data).astype(np.int8)))))

    analyse_mask = (freqs >= _SPEC_LOW) & (freqs <= _SPEC_HIGH)
    band_mask = (freqs >= _BAND_LOW) & (freqs <= _BAND_HIGH)
    total = float(np.sum(power[analyse_mask]))
    band = float(np.sum(power[band_mask]))
    band_ratio = band / total if total > 1e-12 else 0.0

    analysed_power = power[analyse_mask] + 1e-12
    flatness = float(
        np.exp(np.mean(np.log(analysed_power))) / max(np.mean(analysed_power), 1e-12)
    )
    flatness = max(0.0, min(1.0, flatness))
    periodicity = _autocorrelation_periodicity(power, samples)

    speech_like = bool(
        band_ratio >= MIN_BAND_RATIO
        and (
            (flatness <= MAX_FLATNESS and zcr <= MAX_ZCR)
            or (
                band_ratio >= MIN_NOISY_BAND_RATIO
                and flatness <= MAX_NOISY_FLATNESS
                and zcr <= MAX_NOISY_ZCR
                and periodicity >= MIN_NOISY_PERIODICITY
            )
        )
    )
    return FrameEvidence(
        rms=rms,
        peak=peak,
        crest=crest,
        zcr=zcr,
        band_ratio=band_ratio,
        flatness=flatness,
        periodicity=periodicity,
        speech_like=speech_like,
    )


def is_speech_shaped(frame, sample_rate: int = 16000) -> bool:
    """Cheap boolean wrapper used by the segmenter."""
    return analyse_frame(frame, sample_rate).speech_like


def block_has_speech_shape(frame, sample_rate: int = 16000) -> bool:
    """True when any 32 ms window inside ``frame`` is speech-shaped.

    The microphone delivers blocks of arbitrary size (often 32-160 ms). A block
    that straddles a word boundary can contain both silence and speech, so a
    whole-block analysis would be misleading. Splitting into the same windows
    the segmenter/VAD use keeps the decision local and lets a genuine word open
    the gate while a click or knock — which has no speech-shaped window —
    cannot.
    """
    data = _as_mono(frame)
    if data.size == 0:
        return False
    if data.size <= FRAME_SAMPLES:
        return analyse_frame(data, sample_rate).speech_like
    for chunk in _iter_frames(data):
        if analyse_frame(chunk, sample_rate).speech_like:
            return True
    return False


@dataclass(frozen=True)
class UtteranceEvidence:
    """Aggregate evidence for a captured utterance."""

    duration_seconds: float
    active_frames: int
    speech_frames: int
    speech_ratio: float
    speech_seconds: float
    peak: float
    is_speech: bool

    @property
    def reason(self) -> str:
        if self.is_speech:
            return "speech"
        if self.duration_seconds < MIN_UTTERANCE_SECONDS:
            return "too_short"
        if self.speech_frames < MIN_SPEECH_FRAMES:
            return "no_sustained_speech"
        return "non_speech_shaped"


def _iter_frames(audio: np.ndarray) -> Iterable[np.ndarray]:
    for start in range(0, audio.size, FRAME_SAMPLES):
        chunk = audio[start:start + FRAME_SAMPLES]
        if chunk.size < FRAME_SAMPLES:
            chunk = np.pad(chunk, (0, FRAME_SAMPLES - chunk.size))
        yield chunk


def analyse_utterance(audio, sample_rate: int = 16000) -> UtteranceEvidence:
    """Decide whether a captured utterance contains sustained speech.

    The utterance may include pre-roll and trailing silence (the segmenter
    intentionally keeps both), so the ratio is computed over frames that are
    active relative to the loudest frame rather than over every frame.
    """
    data = _as_mono(audio)
    duration = float(data.size) / float(sample_rate) if sample_rate else 0.0
    if data.size == 0:
        return UtteranceEvidence(0.0, 0, 0, 0.0, 0.0, 0.0, False)

    peak = float(np.max(np.abs(data)))
    frames: List[FrameEvidence] = [analyse_frame(f, sample_rate) for f in _iter_frames(data)]
    rms_values = np.asarray([f.rms for f in frames], dtype=np.float64)
    noise_floor = float(np.percentile(rms_values, 10)) if rms_values.size else 0.0
    noise_floor = min(noise_floor, peak * NOISE_FLOOR_CAP)
    active_floor = max(
        peak * ACTIVE_RELATIVE_FLOOR,
        noise_floor * ACTIVE_NOISE_MULTIPLIER,
        1e-5,
    )
    active = [f for f in frames if f.rms >= active_floor]
    speech_frames = sum(1 for f in active if f.speech_like)
    speech_ratio = (speech_frames / len(active)) if active else 0.0
    speech_seconds = speech_frames * (FRAME_SAMPLES / float(sample_rate))

    is_speech = bool(
        duration >= MIN_UTTERANCE_SECONDS
        and speech_frames >= MIN_SPEECH_FRAMES
        and speech_ratio >= MIN_SPEECH_RATIO
    )
    return UtteranceEvidence(
        duration_seconds=duration,
        active_frames=len(active),
        speech_frames=speech_frames,
        speech_ratio=speech_ratio,
        speech_seconds=speech_seconds,
        peak=peak,
        is_speech=is_speech,
    )
