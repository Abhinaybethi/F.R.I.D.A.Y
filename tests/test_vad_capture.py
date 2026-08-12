"""
F.R.I.D.A.Y. VAD Capture Test
================================
Records speech using only the Voice Activity Detector — Whisper is NOT invoked.

Purpose
-------
Isolates the VAD / audio capture stage from the STT stage so we can verify:
  1. Is the audio being captured correctly?
  2. Is VAD clipping the start or end of speech?
  3. What does the microphone actually record?

The captured audio is saved to debug_audio/vad_test.wav.
Play it back to hear exactly what the pipeline captures.

Run
---
    python tests/test_vad_capture.py

Press Ctrl+C to stop after one or more captures.
"""

import os
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.audio_input import AudioInput
from friday.voice.vad import VoiceActivityDetector

# ---------------------------------------------------------------------------
DEBUG_DIR = Path("debug_audio")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = 16000
CHUNK_SIZE = 512
MAX_SILENCE_SEC = 1.5
MAX_WAIT_SEC = 12.0


def save_wav(audio: np.ndarray, path: Path, sample_rate: int = SAMPLE_RATE):
    """Save float32 audio to a 16-bit WAV file."""
    audio_int16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())


def capture_one(audio: AudioInput, vad: VoiceActivityDetector) -> tuple[np.ndarray, dict]:
    """
    Capture one utterance via VAD.

    Returns
    -------
    audio_data : float32 ndarray (empty if timeout)
    info       : dict with speech_start_sec, speech_end_sec, audio_sec, rms, peak
    """
    audio.drain()
    vad.reset_states()

    buffer = []
    is_speech = False
    silence_frames = 0
    wait_frames = 0
    speech_start_frame = None
    speech_end_frame = None
    total_frames = 0

    max_silence_frames = int((MAX_SILENCE_SEC * SAMPLE_RATE) / CHUNK_SIZE)
    max_wait_frames = int((MAX_WAIT_SEC * SAMPLE_RATE) / CHUNK_SIZE)

    print("  Waiting for speech...", end="", flush=True)

    for chunk in audio.read_chunks():
        total_frames += 1
        if not is_speech:
            wait_frames += 1
            if wait_frames > max_wait_frames:
                print(" [TIMEOUT]")
                break

        detected = vad.is_speech(chunk)

        if detected:
            if not is_speech:
                is_speech = True
                speech_start_frame = total_frames
                print(" [● Recording]", end="", flush=True)
            silence_frames = 0
            buffer.append(chunk)
        else:
            if is_speech:
                buffer.append(chunk)
                silence_frames += 1
                if silence_frames > max_silence_frames:
                    speech_end_frame = total_frames - silence_frames
                    break

    if not buffer:
        return np.array([], dtype=np.float32), {}

    data = np.concatenate(buffer)
    audio_sec = len(data) / SAMPLE_RATE
    rms = float(np.sqrt(np.mean(data ** 2)))
    peak = float(np.max(np.abs(data)))

    info = {
        "speech_start_sec": (speech_start_frame or 0) * CHUNK_SIZE / SAMPLE_RATE,
        "speech_end_sec": (
            (speech_end_frame or total_frames) * CHUNK_SIZE / SAMPLE_RATE
        ),
        "audio_sec": audio_sec,
        "rms": rms,
        "peak": peak,
    }
    return data, info


def main():
    print("\n" + "=" * 52)
    print("  VAD CAPTURE TEST  (no Whisper)")
    print("=" * 52)
    print("\n  This test records speech and saves WAV files.")
    print("  It does NOT call Whisper — audio only.")
    print("  Listen to the saved WAVs to inspect audio quality.\n")

    print("Opening microphone ...")
    audio = AudioInput(sample_rate=SAMPLE_RATE, chunk_size=CHUNK_SIZE)
    audio.start()
    if not audio.is_active():
        print("[ERROR] Could not open microphone. Aborting.")
        sys.exit(1)

    print("Initializing VAD ...")
    vad = VoiceActivityDetector()
    if vad.session is None:
        print("[ERROR] VAD failed to initialize. Aborting.")
        audio.stop()
        sys.exit(1)

    # Mic diagnostics
    print("\n--- Microphone Diagnostics ---")
    dev = audio.get_device_info()
    print(f"  Input device : {dev.get('device_name', 'Unknown')}")
    print(f"  Sample rate  : {dev.get('sample_rate', 0)} Hz")
    levels = audio.sample_levels(duration=0.5)
    print(f"  RMS          : {levels['rms']:.4f}")
    print(f"  Peak         : {levels['peak']:.4f}")

    if levels["rms"] < 0.001:
        print("  [WARNING] Very low RMS — microphone may be silent or muted.")
    if levels["peak"] > 0.95:
        print("  [WARNING] Near clipping — reduce input gain.")

    print("\n--- Ready ---")
    print("Speak when you see the prompt. Press Ctrl+C to stop.\n")

    capture_count = 0
    try:
        while True:
            capture_count += 1
            save_path = DEBUG_DIR / f"vad_test_{capture_count:03d}.wav"

            print(f"\n[Capture {capture_count}]")
            audio_data, info = capture_one(audio, vad)

            if len(audio_data) == 0:
                print("  Speech detected : NO (timeout)")
                print("  (No file saved)")
                continue

            # Save
            save_wav(audio_data, save_path)

            print()
            print(f"  Speech detected : YES")
            print(f"  Duration        : {info['audio_sec']:.2f}s")
            print(f"  Speech start    : ~{info['speech_start_sec']:.2f}s into listen window")
            print(f"  Speech end      : ~{info['speech_end_sec']:.2f}s into listen window")
            print(f"  RMS             : {info['rms']:.4f}")
            print(f"  Peak            : {info['peak']:.4f}")
            print(f"  Saved           : {save_path}")

            if info["rms"] < 0.01:
                print("  [WARNING] Very quiet capture — check mic gain.")
            if info["peak"] > 0.95:
                print("  [WARNING] Clipping detected.")

            # Optional playback
            print()
            try:
                play = input("  Play back this recording? [y/n] ").strip().lower()
            except EOFError:
                play = "n"

            if play == "y":
                try:
                    import sounddevice as sd
                    import soundfile as sf
                    data, sr = sf.read(str(save_path), dtype="float32")
                    print("  Playing...")
                    sd.play(data, sr)
                    sd.wait()
                    print("  Done.")
                except Exception as e:
                    print(f"  Playback failed: {e}")

            try:
                again = input("\n  Capture another? [y/n] ").strip().lower()
            except EOFError:
                again = "n"

            if again != "y":
                break

    except KeyboardInterrupt:
        print("\n\n[Stopped by user]")
    finally:
        audio.stop()
        print("Microphone closed.")

    if capture_count > 0:
        print(f"\nSaved WAVs to: {DEBUG_DIR}/")
        print("Run Whisper on a WAV: python tests/test_whisper_file.py debug_audio/vad_test_001.wav\n")


if __name__ == "__main__":
    main()
