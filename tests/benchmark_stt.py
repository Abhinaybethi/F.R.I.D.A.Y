"""
F.R.I.D.A.Y. STT Benchmark
============================
Live microphone benchmark comparing tiny.en / base.en / small.en.

Usage
-----
    python tests/benchmark_stt.py

Rules
-----
- CPU only (device=cpu, compute_type=int8) — GPU optimization is a future task.
- Models are loaded from the local Hugging Face cache. Missing models are
  reported clearly; the benchmark does NOT download them silently.
- One silent warm-up pass is run after each model load to absorb JIT overhead
  so that first-utterance RTF is not artificially inflated.
- The microphone is opened ONCE per model under test and stays open for all
  10 phrases.

Output
------
Per-utterance results are printed in real time.
A final summary table (Avg RTF / Median RTF / Worst RTF) and side-by-side
transcription comparison are printed at the end.
"""

import os
import sys
import time
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Add project root to sys.path so we can import friday.*
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ---------------------------------------------------------------------------
# Fixed test phrases — speak each one naturally when prompted.
# ---------------------------------------------------------------------------
TEST_PHRASES = [
    "Friday",
    "Open Chrome",
    "Open YouTube",
    "Close Chrome",
    "Find my resume",
    "Search for Python tutorials",
    "What time is it now",
    "Open my Downloads folder",
    "Open VS Code",
    "Close YouTube",
]

# Models to benchmark, in order from fastest to most accurate.
MODELS_TO_TEST = ["tiny.en", "base.en", "small.en"]

# Hugging Face cache root for faster-whisper models.
# faster-whisper stores models under: HF_HOME / hub / models--Systran--faster-whisper-<size>/
_HF_HOME = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
_HF_HUB = _HF_HOME / "hub"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UtteranceResult:
    phrase_index: int        # 1-based index into TEST_PHRASES
    expected: str            # what the user was asked to say
    transcription: str       # what Whisper heard
    audio_sec: float         # duration of captured audio (seconds)
    transcription_sec: float # time spent in transcribe() (seconds)
    rtf: float               # transcription_sec / audio_sec


@dataclass
class ModelResult:
    model: str
    available: bool = True
    utterances: list[UtteranceResult] = field(default_factory=list)

    # Computed after all utterances
    rtf_values: list[float] = field(default_factory=list)
    avg_rtf: float = 0.0
    median_rtf: float = 0.0
    worst_rtf: float = 0.0


# ---------------------------------------------------------------------------
# Model availability check
# ---------------------------------------------------------------------------

def _model_cache_path(model_size: str) -> Path | None:
    """
    Return the snapshot directory for a faster-whisper model in the HF cache,
    or None if it is not present.

    faster-whisper resolves short names like "small.en" to:
      Systran/faster-whisper-small.en
    so the HF hub directory is:
      models--Systran--faster-whisper-<model_size>/snapshots/<hash>/
    """
    model_dir_name = f"models--Systran--faster-whisper-{model_size}"
    model_dir = _HF_HUB / model_dir_name
    if not model_dir.exists():
        return None

    snapshots_dir = model_dir / "snapshots"
    if not snapshots_dir.exists():
        return None

    # Return the first snapshot directory found
    snapshots = list(snapshots_dir.iterdir())
    if not snapshots:
        return None

    return snapshots[0]


def check_model_available(model_size: str) -> bool:
    return _model_cache_path(model_size) is not None


# ---------------------------------------------------------------------------
# Audio capture helpers (microphone + VAD without full session_manager)
# ---------------------------------------------------------------------------

def capture_utterance(audio_input, vad, sample_rate: int = 16000, chunk_size: int = 512,
                       max_silence_sec: float = 1.5, max_wait_sec: float = 12.0) -> np.ndarray:
    """
    Capture one utterance from the open microphone.
    Returns float32 numpy array at 16 kHz, or empty array on timeout/silence.
    """
    audio_input.drain()
    vad.reset_states()

    buffer = []
    is_speech = False
    silence_frames = 0
    wait_frames = 0

    max_silence_frames = int((max_silence_sec * sample_rate) / chunk_size)
    max_wait_frames = int((max_wait_sec * sample_rate) / chunk_size)

    for chunk in audio_input.read_chunks():
        if not is_speech:
            wait_frames += 1
            if wait_frames > max_wait_frames:
                break

        speech = vad.is_speech(chunk)

        if speech:
            if not is_speech:
                is_speech = True
                print("  [●] Recording...", end="", flush=True)
            silence_frames = 0
            buffer.append(chunk)
        else:
            if is_speech:
                buffer.append(chunk)
                silence_frames += 1
                if silence_frames > max_silence_frames:
                    break

    if not buffer:
        return np.array([], dtype=np.float32)

    return np.concatenate(buffer)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark():
    print("\n" + "=" * 62)
    print("  F.R.I.D.A.Y. STT Benchmark")
    print("  Models: tiny.en  base.en  small.en")
    print("  Device: CPU / int8")
    print("=" * 62)

    # Import here (after sys.path is set)
    from friday.voice.audio_input import AudioInput
    from friday.voice.vad import VoiceActivityDetector
    from friday.voice.speech_to_text import SpeechToText

    # Open the microphone ONCE — we'll reuse it across all models.
    print("\nInitializing microphone...")
    audio = AudioInput()
    audio.start()
    if not audio.is_active():
        print("[ERROR] Could not open microphone. Aborting.")
        sys.exit(1)
    print("Microphone ready.\n")

    print("Initializing VAD...")
    vad = VoiceActivityDetector()
    if vad.session is None:
        print("[ERROR] VAD failed to load. Aborting.")
        audio.stop()
        sys.exit(1)
    print("VAD ready.\n")

    all_results: list[ModelResult] = []

    try:
        for model_size in MODELS_TO_TEST:
            print("\n" + "-" * 62)
            print(f"  Model: {model_size}")
            print("-" * 62)

            # --- availability check ---
            if not check_model_available(model_size):
                print(f"\n  [SKIP] Model unavailable: {model_size}")
                print(f"         Run: python main.py --download-voice-models")
                print(f"         (or: huggingface-cli download Systran/faster-whisper-{model_size})\n")
                all_results.append(ModelResult(model=model_size, available=False))
                continue

            # --- load model ---
            print(f"  Loading {model_size} (CPU / int8) ...")
            load_t0 = time.perf_counter()
            stt = SpeechToText(
                model_size=model_size,
                device="cpu",
                compute_type="int8",
                language="en",
            )
            load_elapsed = time.perf_counter() - load_t0

            if stt.model is None:
                print(f"  [ERROR] Model failed to load: {model_size}")
                all_results.append(ModelResult(model=model_size, available=False))
                continue

            print(f"  Model loaded in {load_elapsed:.1f}s (warm-up included).\n")

            result = ModelResult(model=model_size)
            all_results.append(result)

            # --- run phrases ---
            for i, phrase in enumerate(TEST_PHRASES, start=1):
                print(f"\n  [{i:02d}/{len(TEST_PHRASES)}] Please say: \"{phrase}\"")
                print(f"  Waiting for speech...", end="", flush=True)

                audio_data = capture_utterance(audio, vad)

                if len(audio_data) == 0:
                    print("\n  [TIMEOUT] No speech detected. Skipping phrase.")
                    continue

                audio_sec = len(audio_data) / 16000
                print(f"  captured {audio_sec:.1f}s", flush=True)

                # Transcribe and measure
                t0 = time.perf_counter()
                text, rtf = stt.transcribe(audio_data)
                transcription_sec = time.perf_counter() - t0

                # Guard empty/noise output
                display_text = text if text else "(no speech detected)"

                print(f"  Model     : {model_size}")
                print(f"  Audio     : {audio_sec:.2f}s")
                print(f"  STT time  : {transcription_sec:.2f}s")
                print(f"  RTF       : {rtf:.2f}")
                print(f"  Result    : {display_text}")

                utterance = UtteranceResult(
                    phrase_index=i,
                    expected=phrase,
                    transcription=text,
                    audio_sec=audio_sec,
                    transcription_sec=transcription_sec,
                    rtf=rtf,
                )
                result.utterances.append(utterance)
                result.rtf_values.append(rtf)

            # Compute statistics
            if result.rtf_values:
                result.avg_rtf = statistics.mean(result.rtf_values)
                result.median_rtf = statistics.median(result.rtf_values)
                result.worst_rtf = max(result.rtf_values)

            print(f"\n  [{model_size}] Done. Avg RTF={result.avg_rtf:.2f} | "
                  f"Median={result.median_rtf:.2f} | Worst={result.worst_rtf:.2f}")

    finally:
        # Always close the microphone cleanly
        audio.stop()
        print("\nMicrophone closed.")

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("  BENCHMARK SUMMARY")
    print("=" * 62)
    print(f"\n  {'Model':<12} {'Avg RTF':>9} {'Median RTF':>11} {'Worst RTF':>10}  {'Phrases tested':>14}")
    print(f"  {'-'*12} {'-'*9} {'-'*11} {'-'*10}  {'-'*14}")
    for r in all_results:
        if not r.available:
            print(f"  {r.model:<12}  {'(unavailable — model not in cache)'}")
        elif not r.rtf_values:
            print(f"  {r.model:<12}  {'(no data — all phrases timed out)'}")
        else:
            print(f"  {r.model:<12} {r.avg_rtf:>9.2f} {r.median_rtf:>11.2f} "
                  f"{r.worst_rtf:>10.2f}  {len(r.utterances):>14}/{len(TEST_PHRASES)}")

    # -----------------------------------------------------------------------
    # Transcription quality table
    # -----------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("  TRANSCRIPTION QUALITY")
    print("=" * 62)

    available_results = [r for r in all_results if r.available and r.utterances]
    if available_results:
        # Header
        model_col_width = 14
        header = f"\n  {'Phrase':<35}"
        for r in available_results:
            header += f"  {r.model:<{model_col_width}}"
        print(header)
        print("  " + "-" * (35 + (model_col_width + 2) * len(available_results)))

        for i, phrase in enumerate(TEST_PHRASES, start=1):
            row = f"  {phrase:<35}"
            for r in available_results:
                # Find utterance for this phrase index
                utt = next((u for u in r.utterances if u.phrase_index == i), None)
                if utt is None:
                    cell = "(skipped)"
                elif not utt.transcription:
                    cell = "(no speech)"
                else:
                    cell = utt.transcription[:model_col_width]
                row += f"  {cell:<{model_col_width}}"
            print(row)

    print("\n" + "=" * 62)
    print("  NOTE: Winner is NOT chosen automatically.")
    print("  Evaluate: speed (RTF) + accuracy + stability.")
    print("=" * 62 + "\n")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_benchmark()
