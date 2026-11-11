"""Regression tests for the noise / false-transcription fix.

Real failure seen in the field: a desk knock or mouse click was captured by the
energy/VAD gate and Whisper hallucinated ``"boom."`` / ``"tell me."``. The fix
has three layers, each covered here:

1. :mod:`friday.voice.speech_evidence` — deterministic spectral evidence that
   separates sustained speech from clicks, knocks, thuds, white noise and hum.
2. :class:`friday.voice.segmenter.SpeechSegmenter` — loud energy can no longer
   bypass the evidence gate when Silero VAD is in use; ``vad=False`` keeps its
   historical energy-only contract.
3. ``DashboardRuntime._transcribe_handsfree`` — rejects non-speech before STT
   and ignores low-quality Whisper metadata.

The synthetic signals are generated deterministically so the suite needs no
hardware, model download or recorded fixtures.
"""
from __future__ import annotations

import numpy as np
import pytest

from friday.voice.segmenter import SegmenterConfig, SpeechSegmenter
from friday.voice.speech_evidence import (
    analyse_frame,
    analyse_utterance,
    block_has_speech_shape,
)

SR = 16000


# ---------------------------------------------------------------------------
# Deterministic signal generators
# ---------------------------------------------------------------------------
def _speech(duration: float = 1.1, amp: float = 0.12, f0: float = 115.0) -> np.ndarray:
    """Voiced, harmonic, amplitude-modulated signal standing in for speech."""
    t = np.arange(int(SR * duration)) / SR
    track = f0 * (1.0 + 0.02 * np.sin(2 * np.pi * 3.0 * t) + 0.01 * np.sin(2 * np.pi * 1.3 * t))
    phase = 2 * np.pi * np.cumsum(track) / SR
    sig = np.zeros_like(t)
    for n in range(1, 21):
        sig += (1.0 / n) * np.sin(n * phase)
    # Crude formant movement keeps the spectrum speech-like rather than a tone.
    sig *= 1.0 + 0.35 * np.sin(2 * np.pi * 3.1 * t)
    env = 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 2.2 * t))
    sig = sig / (np.max(np.abs(sig)) + 1e-9) * amp * env
    return sig.astype(np.float32)


def _pad(sig: np.ndarray, lead: float = 0.10, trail: float = 0.80) -> np.ndarray:
    return np.concatenate(
        [
            np.zeros(int(SR * lead), dtype=np.float32),
            sig,
            np.zeros(int(SR * trail), dtype=np.float32),
        ]
    ).astype(np.float32)


def _knock(amp: float = 0.6, duration: float = 0.35) -> np.ndarray:
    rng = np.random.default_rng(7)
    t = np.arange(int(SR * duration)) / SR
    burst = np.sin(2 * np.pi * 75 * t) * np.exp(-t * 18)
    thump = rng.standard_normal(t.size) * np.exp(-t * 60) * 0.6
    return ((burst + thump) * amp / np.max(np.abs(burst + thump))).astype(np.float32)


def _click(amp: float = 0.8) -> np.ndarray:
    rng = np.random.default_rng(11)
    sig = np.zeros(int(SR * 0.05), dtype=np.float32)
    n = int(SR * 0.012)
    sig[:n] = rng.standard_normal(n) * np.exp(-np.linspace(0, 6, n))
    return (sig / (np.max(np.abs(sig)) + 1e-9) * amp).astype(np.float32)


def _table_thud(amp: float = 0.5, duration: float = 0.30) -> np.ndarray:
    rng = np.random.default_rng(13)
    t = np.arange(int(SR * duration)) / SR
    noise = rng.standard_normal(t.size)
    out = np.zeros_like(noise)
    for i in range(1, noise.size):
        out[i] = 0.85 * out[i - 1] + 0.15 * noise[i]
    return (out * np.exp(-t * 25) * amp / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


def _white(amp: float = 0.02, duration: float = 0.8, seed: int = 17) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(SR * duration)) * amp).astype(np.float32)


def _keyboard_taps(amp: float = 0.6) -> np.ndarray:
    rng = np.random.default_rng(31)
    sig = np.zeros(int(SR * 1.2), dtype=np.float32)
    for k in range(6):
        start = int(SR * (0.10 + 0.15 * k))
        n = int(SR * 0.012)
        sig[start:start + n] += (
            rng.standard_normal(n) * np.exp(-np.linspace(0, 6, n)) * amp
        )
    return sig


def _hum(amp: float = 0.05, duration: float = 0.8) -> np.ndarray:
    t = np.arange(int(SR * duration)) / SR
    return (
        amp * (np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 120 * t))
    ).astype(np.float32)


def _blocks(sig: np.ndarray, size: int = 512):
    for start in range(0, len(sig), size):
        chunk = sig[start:start + size]
        if chunk.size < size:
            chunk = np.pad(chunk, (0, size - chunk.size))
        yield chunk.astype(np.float32)


class _AlwaysSpeechVAD:
    """Worst case: Silero says 'speech' even for a knock."""

    def is_speech(self, _chunk) -> bool:
        return True

    def reset_states(self) -> None:
        return None


class _never_speech_vad:
    def is_speech(self, _chunk) -> bool:
        return False

    def reset_states(self) -> None:
        return None


_ALWAYS_SPEECH = _AlwaysSpeechVAD()
_NEVER_SPEECH = _never_speech_vad()


# ---------------------------------------------------------------------------
# 1. Acoustic evidence
# ---------------------------------------------------------------------------
def test_normal_and_quiet_speech_are_accepted():
    normal = analyse_utterance(_pad(_speech(amp=0.12)))
    quiet = analyse_utterance(_pad(_speech(amp=0.01)))
    assert normal.is_speech, normal.reason
    assert quiet.is_speech, quiet.reason
    # Evidence is amplitude independent (ratios, not absolute loudness).
    assert normal.speech_ratio == pytest.approx(quiet.speech_ratio, abs=0.05)


def test_quiet_speech_survives_microphone_noise():
    rng = np.random.default_rng(23)
    padded = _pad(_speech(amp=0.008))
    noise = rng.standard_normal(padded.size).astype(np.float32) * 0.0015
    evidence = analyse_utterance(padded + noise)
    assert evidence.is_speech, (
        f"quiet speech rejected: reason={evidence.reason} "
        f"ratio={evidence.speech_ratio:.2f} frames={evidence.speech_frames}"
    )


@pytest.mark.parametrize(
    "name,signal",
    [
        ("knock", _knock()),
        ("loud_knock", _knock(amp=1.0)),
        ("click", _click()),
        ("table_thud", _table_thud()),
        ("white_noise", _white()),
        ("mains_hum", _hum()),
        ("keyboard_taps", _keyboard_taps()),
    ],
)
def test_disturbances_are_rejected(name, signal):
    evidence = analyse_utterance(_pad(signal))
    assert not evidence.is_speech, (
        f"{name} was accepted as speech: ratio={evidence.speech_ratio:.2f} "
        f"frames={evidence.speech_frames}"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_white_noise_variants_are_rejected(seed):
    assert not analyse_utterance(_pad(_white(seed=seed), trail=0.2)).is_speech


def test_silence_is_rejected():
    assert not analyse_utterance(np.zeros(int(SR * 1.5), dtype=np.float32)).is_speech


def test_block_helper_sees_speech_but_not_transients():
    assert block_has_speech_shape(_speech()[:512])
    assert not block_has_speech_shape(_knock()[:512])
    assert not block_has_speech_shape(_click()[:512])


def test_frame_features_separate_speech_from_click():
    speech_frame = _speech()[4000:4512]
    click_frame = _knock()[:512]
    speech_ev = analyse_frame(speech_frame)
    click_ev = analyse_frame(click_frame)
    assert speech_ev.speech_like
    assert not click_ev.speech_like
    assert speech_ev.flatness < click_ev.flatness


# ---------------------------------------------------------------------------
# 2. Segmenter: loud energy may not bypass the evidence gate
# ---------------------------------------------------------------------------
def _vad_segmenter(vad) -> SpeechSegmenter:
    return SpeechSegmenter(SegmenterConfig(), vad=vad)


def _feed(segmenter: SpeechSegmenter, signal: np.ndarray):
    finished = []
    for block in _blocks(signal):
        utterance = segmenter.feed(block)
        if utterance is not None:
            finished.append(utterance)
    return finished


def test_segmenter_accepts_genuine_speech_in_vad_mode():
    finished = _feed(_vad_segmenter(_ALWAYS_SPEECH), _pad(_speech(amp=0.08)))
    assert finished, "genuine speech did not produce an utterance"
    assert finished[0].size > SR * 0.5


def test_segmenter_rejects_loud_knock_even_with_vad_positive():
    # VAD says speech for every block; only the spectral gate can reject it.
    finished = _feed(_vad_segmenter(_ALWAYS_SPEECH), _pad(_knock(amp=0.9), trail=1.0))
    assert finished == []


def test_segmenter_rejects_click_and_thud_with_vad_positive():
    assert _feed(_vad_segmenter(_ALWAYS_SPEECH), _pad(_click(), trail=1.0)) == []
    assert _feed(_vad_segmenter(_ALWAYS_SPEECH), _pad(_table_thud(), trail=1.0)) == []


def test_strong_energy_does_not_bypass_evidence_when_vad_is_negative():
    # Loud click: strong_energy is true, Silero says no -> must still be rejected.
    finished = _feed(_vad_segmenter(_NEVER_SPEECH), _pad(_knock(amp=1.0), trail=1.0))
    assert finished == []


def test_energy_only_mode_contract_is_unchanged():
    """vad=False stays deterministic and loudness-based (existing tests rely on it)."""
    segmenter = SpeechSegmenter(SegmenterConfig(), vad=False)
    # Constant DC has no spectral speech shape, but energy-only mode ignores it.
    signal = np.concatenate(
        [
            np.full(int(SR * 0.6), 0.2, dtype=np.float32),
            np.zeros(int(SR * 1.0), dtype=np.float32),
        ]
    )
    finished = _feed(segmenter, signal)
    assert finished, "energy-only mode must keep its historical behaviour"


# ---------------------------------------------------------------------------
# 3. Runtime: gate runs before STT, Whisper quality is honoured
# ---------------------------------------------------------------------------
def _runtime(transcriber):
    from friday.web.runtime import DashboardRuntime

    runtime = object.__new__(DashboardRuntime)
    runtime._transcribe_samples = transcriber
    return runtime


def test_handsfree_rejects_noise_before_calling_stt():
    called = []

    def _must_not_run(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("STT must not run for a non-speech utterance")

    runtime = _runtime(_must_not_run)
    assert runtime._transcribe_handsfree(_pad(_knock(amp=0.9))) == ""
    assert runtime._transcribe_handsfree(_pad(_click())) == ""
    assert called == []


def test_handsfree_transcribes_genuine_speech():
    def _fake(samples, detailed=False, publish=True):
        assert detailed is True
        return {
            "text": "open youtube",
            "quality_ok": True,
            "avg_logprob": -0.7,
            "no_speech_prob": 0.05,
            "duration_seconds": len(samples) / SR,
        }

    runtime = _runtime(_fake)
    assert runtime._transcribe_handsfree(_pad(_speech(amp=0.01))) == "open youtube"


def test_handsfree_rejects_low_quality_whisper_output():
    def _fake(samples, detailed=False, publish=True):
        return {
            "text": "boom.",
            "quality_ok": False,
            "avg_logprob": -0.8,
            "no_speech_prob": 0.95,
            "duration_seconds": len(samples) / SR,
        }

    runtime = _runtime(_fake)
    assert runtime._transcribe_handsfree(_pad(_speech())) == ""


def test_handsfree_tolerates_stt_failure():
    def _explode(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    runtime = _runtime(_explode)
    assert runtime._transcribe_handsfree(_pad(_speech())) == ""
