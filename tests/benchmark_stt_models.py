"""
F.R.I.D.A.Y. STT Model Benchmark
==================================
Benchmarks tiny.en / base.en / small.en against the same 10 saved WAV files.
No microphone. No new recordings. Every model gets identical audio.

Run
---
    python tests/benchmark_stt_models.py

Optional: test beam_size=5 on the best candidate after baseline
    python tests/benchmark_stt_models.py --beam5 small.en
"""

import argparse
import os
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.speech_to_text import SpeechToText
_HF_HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"

def check_model_available(model_size: str) -> bool:
    d = _HF_HUB / f"models--Systran--faster-whisper-{model_size}" / "snapshots"
    return d.exists() and any(d.iterdir())

# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------

PHRASES = {
    "001.wav": "Open Chrome",
    "002.wav": "Open YouTube",
    "003.wav": "Close Chrome",
    "004.wav": "Find my resume",
    "005.wav": "Search for Python tutorials",
    "006.wav": "What time is it now",
    "007.wav": "Open my Downloads folder",
    "008.wav": "Open VS Code",
    "009.wav": "Close YouTube",
    "010.wav": "Friday",
}

MODELS = ["tiny.en", "base.en", "small.en"]
AUDIO_DIR = Path("debug_audio")

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_hard(text: str) -> str:
    """Lowercase, remove ALL non-alpha chars (catches 'openvscode' == 'open vs code')."""
    return re.sub(r"[^a-z]", "", text.lower())


def wer(expected: str, actual: str) -> float:
    """Word Error Rate via Levenshtein on word lists."""
    ref = _norm(expected).split()
    hyp = _norm(actual).split()
    if not ref:
        return 0.0
    # simple O(m*n) DP — fine for ≤20 words
    m, n = len(ref), len(hyp)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            prev, dp[j] = dp[j], prev if ref[i-1] == hyp[j-1] else 1 + min(prev, dp[j], dp[j-1])
    return dp[n] / len(ref)


def exact_match(expected: str, actual: str) -> bool:
    return _norm(expected) == _norm(actual)


def semantic_match(expected: str, actual: str) -> bool:
    """
    Semantic pass: strip all non-alpha chars and check if the key phrase
    is present in the actual output (handles 'openvscode', repeated phrases, etc.).
    No LLM — pure string containment on collapsed tokens.
    """
    e = _norm_hard(expected)
    a = _norm_hard(actual)
    return e in a or a in e


# ---------------------------------------------------------------------------
# WAV loader (mono float32 @ 16 kHz)
# ---------------------------------------------------------------------------

def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        n_ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sw == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2**31
    else:
        raise ValueError(f"Unsupported sample width {sw}")

    if n_ch == 2:
        samples = samples.reshape(-1, 2).mean(axis=1)

    if sr != 16000:
        # linear resample — no extra deps
        target = int(len(samples) * 16000 / sr)
        samples = np.interp(
            np.linspace(0, len(samples) - 1, target),
            np.arange(len(samples)), samples,
        ).astype(np.float32)

    return samples


# ---------------------------------------------------------------------------
# Single-model run
# ---------------------------------------------------------------------------

def run_model(model_size: str, beam_size: int = 1) -> dict | None:
    """
    Load model, warm up, transcribe all 10 WAVs, return result dict.
    Returns None if the model is unavailable.
    """
    tag = f"{model_size} beam={beam_size}"

    if not check_model_available(model_size):
        print(f"\n  [SKIP] Model unavailable: {model_size}")
        print(f"         Run: huggingface-cli download Systran/faster-whisper-{model_size}")
        return None

    print(f"\n{'='*56}")
    print(f"  Model: {tag}")
    print(f"{'='*56}\n")

    stt = SpeechToText(model_size=model_size, device="cpu", compute_type="int8", language="en")
    if stt.model is None:
        print(f"  [ERROR] Failed to load {model_size}")
        return None

    utterances = []

    for filename, phrase in PHRASES.items():
        wav_path = AUDIO_DIR / filename
        if not wav_path.exists():
            print(f"  [MISSING] {wav_path} — skipping")
            continue

        audio = load_wav(wav_path)
        audio_sec = len(audio) / 16000

        # Transcribe with the requested beam_size (override SpeechToText default)
        t0 = time.perf_counter()
        try:
            segs, _ = stt.model.transcribe(
                audio,
                language="en",
                beam_size=beam_size,
                temperature=0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            text = "".join(s.text for s in segs).strip().lower()
        except Exception as e:
            print(f"  [ERROR] {filename}: {e}")
            text = ""
        stt_sec = time.perf_counter() - t0
        rtf = stt_sec / audio_sec if audio_sec > 0 else 0.0

        exact = exact_match(phrase, text)
        sem = semantic_match(phrase, text)
        w = wer(phrase, text)

        mark_exact = "PASS" if exact else "FAIL"
        mark_sem   = "~ok " if (sem and not exact) else mark_exact

        print(f"  {filename}")
        print(f"    Expected : {phrase.lower()}")
        print(f"    Actual   : {text if text else '(empty)'}")
        print(f"    Exact    : {mark_exact}  Semantic: {mark_sem}  WER: {w:.2f}  RTF: {rtf:.2f}")

        utterances.append({
            "file": filename,
            "phrase": phrase,
            "actual": text,
            "audio_sec": audio_sec,
            "stt_sec": stt_sec,
            "rtf": rtf,
            "exact": exact,
            "semantic": sem,
            "wer": w,
        })

    return {"model": tag, "utterances": utterances}


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]):
    print(f"\n{'='*72}")
    print("  MODEL SUMMARY")
    print(f"{'='*72}")
    print(f"\n  {'Model':<22} {'Exact':>7} {'Semantic':>9} {'Avg WER':>8} {'Avg RTF':>8} {'Worst RTF':>10}")
    print(f"  {'-'*22} {'-'*7} {'-'*9} {'-'*8} {'-'*8} {'-'*10}")

    for r in results:
        if r is None:
            continue
        u = r["utterances"]
        if not u:
            continue
        n = len(u)
        exact_pct = 100.0 * sum(x["exact"] for x in u) / n
        sem_pct   = 100.0 * sum(x["semantic"] for x in u) / n
        avg_wer   = sum(x["wer"] for x in u) / n
        avg_rtf   = sum(x["rtf"] for x in u) / n
        worst_rtf = max(x["rtf"] for x in u)

        print(
            f"  {r['model']:<22} {exact_pct:>6.0f}% {sem_pct:>8.0f}% "
            f"{avg_wer:>8.2f} {avg_rtf:>8.2f} {worst_rtf:>10.2f}"
        )

    print(f"\n  Exact    = normalized exact string match")
    print(f"  Semantic = key tokens present (catches 'openvscode' == 'open vs code')")
    print(f"  WER      = word error rate (0 = perfect, 1 = total mismatch)")

    # Per-model failure list
    print(f"\n{'='*72}")
    print("  FAILURES BY MODEL")
    print(f"{'='*72}")
    for r in results:
        if r is None:
            continue
        fails = [u for u in r["utterances"] if not u["semantic"]]
        if not fails:
            print(f"\n  {r['model']}: no semantic failures")
            continue
        print(f"\n  {r['model']} — {len(fails)} semantic failure(s):")
        for u in fails:
            print(f"    {u['file']}  expected: {u['phrase'].lower()!r:<35}  got: {u['actual']!r}")

    # Critical commands audit
    CRITICAL = {"001.wav", "003.wav", "008.wav", "009.wav"}  # Chrome/VS Code/YouTube controls
    print(f"\n{'='*72}")
    print("  CRITICAL COMMAND RELIABILITY  (application-control phrases)")
    print(f"{'='*72}")
    print(f"\n  {'Model':<22} {'Pass/Total':>10}  Failures")
    print(f"  {'-'*22} {'-'*10}  {'-'*30}")
    for r in results:
        if r is None:
            continue
        crit = [u for u in r["utterances"] if u["file"] in CRITICAL]
        passed = sum(u["semantic"] for u in crit)
        fails_str = ", ".join(u["file"] for u in crit if not u["semantic"]) or "none"
        print(f"  {r['model']:<22} {passed}/{len(crit):>9}  {fails_str}")

    print(f"\n{'='*72}\n")
    print("  NOTE: Winner is NOT chosen automatically.")
    print("  Evaluate: command reliability > accuracy > speed.")
    print(f"{'='*72}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="STT model benchmark on saved WAVs.")
    parser.add_argument(
        "--beam5", metavar="MODEL",
        help="After baseline, also test beam_size=5 on this model (e.g. --beam5 small.en)."
    )
    args = parser.parse_args()

    print(f"\n{'='*56}")
    print("  F.R.I.D.A.Y. STT MODEL BENCHMARK")
    print("  tiny.en / base.en / small.en  |  CPU / int8")
    print(f"  WAVs: {AUDIO_DIR}/")
    print(f"{'='*56}")

    # Verify WAVs exist
    missing = [f for f in PHRASES if not (AUDIO_DIR / f).exists()]
    if missing:
        print(f"\n[ERROR] Missing WAV files: {', '.join(missing)}")
        print(f"Run tests/test_stt_accuracy.py first to generate them.")
        sys.exit(1)

    results = [run_model(m, beam_size=1) for m in MODELS]

    # Optional beam_size=5 comparison on one model
    if args.beam5:
        if args.beam5 not in MODELS:
            print(f"\n[WARN] --beam5 model '{args.beam5}' not in {MODELS}, skipping.")
        else:
            print(f"\n--- beam_size=5 comparison for {args.beam5} ---")
            r5 = run_model(args.beam5, beam_size=5)
            if r5:
                r5["model"] = f"{args.beam5} beam=5"
                results.append(r5)

    print_summary(results)


if __name__ == "__main__":
    main()
