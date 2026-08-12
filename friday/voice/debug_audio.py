"""
Debug audio utilities for F.R.I.D.A.Y. development.

DebugAudioSaver
---------------
Saves captured audio buffers to sequentially-numbered WAV files so the
developer can inspect (and optionally play back) exactly what was sent to
Whisper.

Disabled by default.  Enable via config.yaml:

    voice:
      debug:
        save_audio: true
        directory: debug_audio
        playback_audio: false
        max_files: 50
"""

import wave
from pathlib import Path

import numpy as np

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class DebugAudioSaver:
    """
    Saves float32 audio arrays to WAV files (mono, 16-bit, 16 kHz).

    Files are numbered sequentially: 001.wav, 002.wav, ...
    When max_files is reached the counter wraps around and overwrites the
    oldest file, so disk usage is bounded.
    """

    def __init__(
        self,
        directory: str = "debug_audio",
        max_files: int = 50,
        enabled: bool = False,
        playback: bool = False,
    ):
        self.enabled = enabled
        self.playback = playback
        self.max_files = max(1, max_files)
        self.directory = Path(directory)
        self._counter = 0

        if not enabled:
            return

        self.directory.mkdir(parents=True, exist_ok=True)

        # Resume numbering from the highest existing sequential file
        existing = sorted(
            f for f in self.directory.glob("*.wav")
            if f.stem.isdigit()
        )
        if existing:
            try:
                self._counter = int(existing[-1].stem)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    def save(self, audio: np.ndarray, sample_rate: int = 16000) -> str | None:
        """
        Write ``audio`` (float32, mono) to the next numbered WAV file.

        Returns the file path as a string, or None if saving is disabled or
        an error occurs.
        """
        if not self.enabled:
            return None

        self._counter += 1
        file_index = ((self._counter - 1) % self.max_files) + 1
        filepath = self.directory / f"{file_index:03d}.wav"

        try:
            # Clamp float32 [-1, 1] → int16
            audio_int16 = (
                np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
            )
            with wave.open(str(filepath), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)          # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(audio_int16.tobytes())

            logger.debug("[DEBUG AUDIO] Saved: %s", filepath)
            print(f"[DEBUG AUDIO] Saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error("[DEBUG AUDIO] Failed to save %s: %s", filepath, e)
            return None

    # ------------------------------------------------------------------
    def maybe_playback(self, path: str | None):
        """
        If playback is enabled and a path was provided, ask the user
        interactively whether to play the recording.
        """
        if not self.playback or not path:
            return

        print(f"\nCaptured audio: {path}")
        try:
            answer = input("Play this recording? [y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if answer != "y":
            return

        try:
            import sounddevice as sd
            import soundfile as sf

            data, sr = sf.read(path, dtype="float32")
            print("Playing...")
            sd.play(data, sr)
            sd.wait()
            print("Done.")
        except Exception as e:
            print(f"Playback failed: {e}")
