"""
F.R.I.D.A.Y. STT Accuracy Test
================================
Controlled 10-phrase test.  One phrase is shown at a time; the user speaks it
naturally; the transcript is compared and scored.

Features
--------
- Per-utterance: expected, actual, audio duration, STT time, RTF, PASS/FAIL
- Word Error Rate (WER) computed without external dependencies
- Debug WAVs saved to debug_audio/ so you can inspect what Whisper heard
- Optional playback of each WAV (set playback=True below or in config.yaml)

Run
---
    python tests/test_stt_accuracy.py

Press Ctrl+C to abort at any time.
"""

import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.audio_input import AudioInput
from friday.voice.vad import VoiceActivityDetector
from friday.voice.speech_to_text import SpeechToText
from friday.voice.debug_audio import DebugAudioSaver

# ---------------------------------------------------------------------------
# Test phrases — speak each one naturally when prompted
# ---------------------------------------------------------------------------
TEST_PHRASES = [
    "Open Chrome",
    "Open YouTube",
    "Close Chrome",
    "Find my resume",
    "Search for Python tutorials",
    "What time is it now",
    "Open my Downloads folder",
    "Open VS Code",
    "Close YouTube",
    "Friday",
]

# ---------------------------------------------------------------------------
# Debug audio — always enabled for this test so you can inspect the WAVs
# ---------------------------------------------------------------------------
DEBUG_DIR = Path("debug_audio")
PLAYBACK_AUDIO = False       # set True to be prompted to play each WAV


# ---------------------------------------------------------------------------
# WER helpers — no external dependencies
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)   # remove punctuation
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _levenshtein(a: list, b: list) -> int:
    """Edit distance between two lists of tokens."""
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def word_error_rate(expected: str, actual: str) -> float:
    """
    WER = edit_distance(expected_words, actual_words) / len(expected_words).
    Returns 0.0 if expected is empty.
    """
    ref = _normalize(expected).split()
    hyp = _normalize(actual).split()
    if not ref:
        return 0.0
    return _levenshtein(ref, hyp) / len(ref)


def exact_match(expected: str, actual: str) -> bool:
    return _normalize(expected) == _normalize(actual)


# ---------------------------------------------------------------------------
# Audio capture (mirrors benchmark_stt.py — no VoiceSessionManager coupling)
# ---------------------------------------------------------------------------

def capture_utterance(
    audio: AudioInput,
    vad: VoiceActivityDetector,
    sample_rate: int = 16000,
    chunk_size: int = 512,
    max_silence_sec: float = 1.5,
    max_wait_sec: float = 12.0,
) -> tuple[np.ndarray, float | None, float | None]:
    """
    Capture one utterance.

    Returns
    -------
    audio_data      : float32 ndarray (may be empty on timeout)
    speech_start_sec: seconds from listen-start to first VAD-detected speech
    audio_sec       : duration of captured audio
    """
    audio.drain()
    vad.reset_states()

    buffer = []
    is_speech = False
    silence_frames = 0
    wait_frames = 0
    speech_start_frame = None

    max_silence_frames = int((max_silence_sec * sample_rate) / chunk_size)
    max_wait_frames = int((max_wait_sec * sample_rate) / chunk_size)

    for chunk in audio.read_chunks():
        if not is_speech:
            wait_frames += 1
            if wait_frames > max_wait_frames:
                break

        speech = vad.is_speech(chunk)

        if speech:
            if not is_speech:
                is_speech = True
                speech_start_frame = wait_frames
                print(" [●] Recording...", end="", flush=True)
            silence_frames = 0
            buffer.append(chunk)
        else:
            if is_speech:
                buffer.append(chunk)
                silence_frames += 1
                if silence_frames > max_silence_frames:
                    break

    if not buffer:
        return np.array([], dtype=np.float32), None, None

    data = np.concatenate(buffer)
    audio_sec = len(data) / sample_rate
    speech_start_sec = (
        (speech_start_frame or 0) * chunk_size / sample_rate
    )
    return data, speech_start_sec, audio_sec


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_accuracy_test():
    print("\n" + "=" * 52)
    print("  STT ACCURACY TEST")
    print("=" * 52)
    print("\n  Model  : small.en | CPU / int8")
    print(f"  Phrases: {len(TEST_PHRASES)}")
    print(f"  WAVs   : {DEBUG_DIR}/\n")

    # -- Load components --
    print("Loading STT model (small.en) ...")
    stt = SpeechToText(model_size="small.en", device="cpu", compute_type="int8", language="en")
    if stt.model is None:
        print("[ERROR] STT model failed to load. Aborting.")
        sys.exit(1)

    print("Initializing VAD ...")
    vad = VoiceActivityDetector()
    if vad.session is None:
        print("[ERROR] VAD failed to initialize. Aborting.")
        sys.exit(1)

    print("Opening microphone ...")
    audio = AudioInput()
    audio.start()
    if not audio.is_active():
        print("[ERROR] Microphone failed to open. Aborting.")
        sys.exit(1)

    # -- Mic diagnostics --
    print("\n--- Microphone Diagnostics ---")
    dev = audio.get_device_info()
    print(f"  Input device : {dev.get('device_name', 'Unknown')}")
    print(f"  Sample rate  : {dev.get('sample_rate', 0)} Hz")
    print(f"  Channels     : {dev.get('channels', 1)}")
    levels = audio.sample_levels(duration=0.6)
    print(f"  RMS          : {levels['rms']:.4f}")
    print(f"  Peak         : {levels['peak']:.4f}")

    if levels["rms"] < 0.001:
        print("  [WARNING] Very low RMS — mic may be muted or too quiet.")
    elif levels["peak"] > 0.95:
        print("  [WARNING] Near clipping — reduce input gain.")

    # -- Debug WAV saver --
    saver = DebugAudioSaver(
        directory=str(DEBUG_DIR),
        max_files=50,
        enabled=True,        # always save for this diagnostic test
        playback=PLAYBACK_AUDIO,
    )

    print("\n--- Ready ---")
    print("Speak each phrase when prompted. Press Ctrl+C to abort.\n")

    results = []

    try:
        for i, phrase in enumerate(TEST_PHRASES, start=1):
            print("\n" + "=" * 52)
            print(f"  [{i}/{len(TEST_PHRASES)}]  Say:")
            print(f"\n      {phrase}\n")
            print("  Waiting for speech...", end="", flush=True)

            audio_data, speech_start_sec, audio_sec = capture_utterance(audio, vad)

            if len(audio_data) == 0:
                print("\n  [TIMEOUT] No speech detected — skipping.")
                results.append({
                    "phrase": phrase,
                    "actual": "",
                    "audio_sec": 0.0,
                    "stt_sec": 0.0,
                    "rtf": 0.0,
                    "pass": False,
                    "wer": 1.0,
                    "timeout": True,
                })
                continue

            print(f"  captured {audio_sec:.1f}s", flush=True)

            # VAD clipping diagnostics
            if speech_start_sec is not None:
                print(f"  [VAD] Speech detected at ~{speech_start_sec:.2f}s into listen window")

            # Save debug WAV
            wav_path = saver.save(audio_data, 16000)

            # Transcribe
            t0 = time.perf_counter()
            text, rtf = stt.transcribe(audio_data)
            stt_sec = time.perf_counter() - t0

            passed = exact_match(phrase, text)
            wer = word_error_rate(phrase, text)

            print()
            print(f"  Expected  : {phrase.lower()}")
            print(f"  Actual    : {text if text else '(no speech detected)'}")
            print(f"  Audio     : {audio_sec:.1f}s")
            print(f"  STT time  : {stt_sec:.2f}s")
            print(f"  RTF       : {rtf:.2f}")
            print(f"  WER       : {wer:.2f}")
            print(f"  Result    : {'PASS ✓' if passed else 'FAIL ✗'}")

            saver.maybe_playback(wav_path)

            results.append({
                "phrase": phrase,
                "actual": text,
                "audio_sec": audio_sec,
                "stt_sec": stt_sec,
                "rtf": rtf,
                "pass": passed,
                "wer": wer,
                "timeout": False,
            })

    except KeyboardInterrupt:
        print("\n\n[Aborted by user]")
    finally:
        audio.stop()
        print("Microphone closed.\n")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    if not results:
        print("No results to summarize.")
        return

    attempted = [r for r in results if not r["timeout"]]
    passed = [r for r in attempted if r["pass"]]
    failed = [r for r in attempted if not r["pass"]]
    timedout = [r for r in results if r["timeout"]]

    total_wer = (
        sum(r["wer"] for r in attempted) / len(attempted) if attempted else 0.0
    )
    avg_rtf = (
        sum(r["rtf"] for r in attempted) / len(attempted) if attempted else 0.0
    )

    print("=" * 52)
    print("  ACCURACY SUMMARY")
    print("=" * 52)
    print(f"\n  Total phrases : {len(TEST_PHRASES)}")
    print(f"  Attempted     : {len(attempted)}")
    print(f"  Timed out     : {len(timedout)}")
    print(f"  Correct (exact) : {len(passed)}")
    print(f"  Incorrect     : {len(failed)}")
    if attempted:
        accuracy = 100.0 * len(passed) / len(attempted)
        print(f"  Accuracy      : {accuracy:.1f}%")
    print(f"  Avg WER       : {total_wer:.2f}")
    print(f"  Avg RTF       : {avg_rtf:.2f}")

    if failed:
        print("\n  --- Failures ---")
        for r in failed:
            print(f"  Expected : {r['phrase']}")
            print(f"  Actual   : {r['actual'] or '(empty)'}")
            print(f"  WER      : {r['wer']:.2f}")
            print()

    print(f"\n  Debug WAVs saved to: {DEBUG_DIR}/")
    print("  Use tests/test_whisper_file.py to re-run Whisper on any WAV.\n")


if __name__ == "__main__":
    run_accuracy_test()
