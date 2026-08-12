"""
F.R.I.D.A.Y. Whisper from WAV File
=====================================
Run Whisper directly against an existing WAV file — no microphone, no VAD.

Purpose
-------
Separates the two stages of the pipeline:

    Stage 1:  Microphone → VAD → WAV          (test_vad_capture.py)
    Stage 2:  WAV → Whisper → Text            (THIS SCRIPT)

If the WAV sounds correct when played but Whisper produces wrong text,
the problem is in the Whisper configuration.

If the WAV itself sounds clipped, distorted, or wrong, fix the audio
pipeline first.

Usage
-----
    python tests/test_whisper_file.py debug_audio/001.wav
    python tests/test_whisper_file.py debug_audio/vad_test_001.wav

Optional: play the WAV before transcribing
    python tests/test_whisper_file.py debug_audio/001.wav --play
"""

import os
import sys
import time
import wave
import struct
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def load_wav(path: str) -> tuple[np.ndarray, int]:
    """
    Load a WAV file and return (float32_audio, sample_rate).
    Handles mono 16-bit PCM (the format DebugAudioSaver produces).
    Raises ValueError on unsupported formats.
    """
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()

        raw = wf.readframes(n_frames)

    if sample_width == 2:
        # 16-bit PCM
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2**31
    else:
        raise ValueError(f"Unsupported sample width: {sample_width} bytes")

    # Mix down to mono if stereo
    if n_channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)

    return samples, sample_rate


def resample_to_16k(audio: np.ndarray, original_rate: int) -> np.ndarray:
    """
    Simple linear resample to 16 kHz if needed.
    faster-whisper requires 16000 Hz float32 audio.
    """
    if original_rate == 16000:
        return audio

    print(f"[WARN] WAV sample rate is {original_rate} Hz — resampling to 16000 Hz.")
    try:
        # Use scipy if available
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(16000, original_rate)
        audio = resample_poly(audio, 16000 // g, original_rate // g)
    except ImportError:
        # Fallback: numpy linear interpolation (lower quality but no extra deps)
        target_len = int(len(audio) * 16000 / original_rate)
        audio = np.interp(
            np.linspace(0, len(audio) - 1, target_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)

    return audio.astype(np.float32)


def print_wav_info(path: str, audio: np.ndarray, sample_rate: int):
    """Print diagnostics about the WAV file."""
    audio_sec = len(audio) / sample_rate
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))

    print(f"\n  File        : {path}")
    print(f"  Duration    : {audio_sec:.2f}s")
    print(f"  Sample rate : {sample_rate} Hz")
    print(f"  Samples     : {len(audio)}")
    print(f"  RMS         : {rms:.4f}")
    print(f"  Peak        : {peak:.4f}")

    if rms < 0.005:
        print("  [WARNING] Very low RMS — audio may be near-silent.")
    if peak > 0.95:
        print("  [WARNING] Near clipping detected.")
    if audio_sec < 0.3:
        print("  [WARNING] Very short audio (<0.3s) — may be clipped at start.")


def play_wav(path: str):
    """Play a WAV file using sounddevice + soundfile."""
    try:
        import sounddevice as sd
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32")
        print("Playing...")
        sd.play(data, sr)
        sd.wait()
        print("Done.\n")
    except Exception as e:
        print(f"Playback failed: {e}\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run faster-whisper on an existing WAV file."
    )
    parser.add_argument("wav_file", help="Path to the WAV file to transcribe.")
    parser.add_argument(
        "--play", action="store_true",
        help="Play the WAV before transcribing so you can hear what Whisper will process."
    )
    args = parser.parse_args()

    wav_path = args.wav_file
    if not Path(wav_path).exists():
        print(f"[ERROR] File not found: {wav_path}")
        sys.exit(1)

    print("\n" + "=" * 52)
    print("  WHISPER FROM FILE")
    print("=" * 52)

    # -- Load WAV --
    try:
        audio, sample_rate = load_wav(wav_path)
    except Exception as e:
        print(f"[ERROR] Failed to read WAV: {e}")
        sys.exit(1)

    print_wav_info(wav_path, audio, sample_rate)

    # Resample if needed
    audio = resample_to_16k(audio, sample_rate)

    # -- Optional playback --
    if args.play:
        print()
        play_wav(wav_path)
    else:
        try:
            answer = input("\nPlay the WAV before transcribing? [y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer == "y":
            play_wav(wav_path)

    # -- Load STT model --
    print("Loading faster-whisper small.en ...")
    from friday.voice.speech_to_text import SpeechToText

    stt = SpeechToText(model_size="small.en", device="cpu", compute_type="int8", language="en")
    if stt.model is None:
        print("[ERROR] STT model failed to load.")
        sys.exit(1)

    # -- Transcribe --
    print("\nTranscribing ...\n")
    t0 = time.perf_counter()
    text, rtf = stt.transcribe(audio)
    stt_sec = time.perf_counter() - t0

    audio_sec = len(audio) / 16000

    print("-" * 52)
    print(f"  Audio    : {wav_path}")
    print()
    print(f"  Transcription:")
    print(f"    {text if text else '(no speech detected / empty)'}")
    print()
    print(f"  Audio    : {audio_sec:.2f}s")
    print(f"  STT time : {stt_sec:.2f}s")
    print(f"  RTF      : {rtf:.2f}")
    print("-" * 52)

    if not text:
        print("\n  [NOTE] Whisper returned empty output.")
        print("  Possible causes:")
        print("    - Audio is too quiet (check RMS above)")
        print("    - Audio is mostly silence")
        print("    - VAD captured noise/garbage instead of speech")
        print("    - Very short utterance (<0.5s)")

    print()


if __name__ == "__main__":
    main()
