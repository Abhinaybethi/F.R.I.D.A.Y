import queue
import numpy as np
import sounddevice as sd
from typing import Generator

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class AudioInput:
    """
    Persistent microphone stream.

    Lifecycle
    ---------
    start()  → open the InputStream once per session
    drain()  → flush stale queued chunks between utterances (do NOT close stream)
    stop()   → close the stream at end of session
    """

    def __init__(self, sample_rate: int = 16000, chunk_size: int = 512):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.queue: queue.Queue = queue.Queue()
        self.stream: sd.InputStream | None = None

    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        """True if the stream is open and running."""
        return self.stream is not None and self.stream.active

    def start(self):
        """
        Open the microphone stream.  Idempotent — safe to call when already running.
        """
        if self.is_active():
            return  # already open, nothing to do

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.chunk_size,
                callback=self._callback,
            )
            self.stream.start()
            logger.info("Microphone initialized.")
        except Exception as e:
            logger.error("Microphone initialization failed: %s", e)
            self.stream = None

    def drain(self):
        """
        Discard any audio chunks that accumulated in the queue while the
        system was busy (e.g. during transcription).  Does NOT close the
        stream — the same stream keeps running.
        """
        flushed = 0
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                flushed += 1
            except queue.Empty:
                break
        if flushed:
            logger.debug("AudioInput.drain: discarded %d stale chunk(s).", flushed)

    def stop(self):
        """
        Close the stream and release hardware resources.
        Call only at end of session (Ctrl+C / shutdown).
        """
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.warning("Error closing audio stream: %s", e)
            finally:
                self.stream = None

        # Flush any remaining queued data
        self.drain()

    # ------------------------------------------------------------------
    def get_device_info(self) -> dict:
        """
        Return metadata about the active input device.
        Does not require the stream to be open.
        """
        info: dict = {
            "device_name": "Unknown",
            "sample_rate": self.sample_rate,
            "channels": 1,
        }
        try:
            device = sd.query_devices(kind="input")
            info["device_name"] = device.get("name", "Unknown")
            info["default_sample_rate"] = device.get("default_samplerate", self.sample_rate)
        except Exception as e:
            logger.debug("Could not query input device: %s", e)
        return info

    def sample_levels(self, duration: float = 0.5) -> dict[str, float]:
        """
        Collect audio for ``duration`` seconds from the live stream and return
        RMS and peak amplitude.  Chunks are consumed (not returned to the queue)
        — call only when you can afford to lose a short burst (e.g. at startup).

        Returns a dict with keys ``rms`` and ``peak``.  Returns zeros if the
        stream is not active or no data arrives.
        """
        if not self.is_active():
            return {"rms": 0.0, "peak": 0.0}

        n_chunks = max(1, int((duration * self.sample_rate) / self.chunk_size))
        samples = []

        for _ in range(n_chunks):
            try:
                chunk = self.queue.get(timeout=0.2)
                samples.append(chunk)
            except queue.Empty:
                break

        if not samples:
            return {"rms": 0.0, "peak": 0.0}

        data = np.concatenate(samples)
        rms = float(np.sqrt(np.mean(data ** 2)))
        peak = float(np.max(np.abs(data)))
        return {"rms": rms, "peak": peak}

    # ------------------------------------------------------------------
    def _callback(self, indata, frames, time, status):
        if status:
            logger.debug("Audio input status: %s", status)
        self.queue.put(indata.copy().flatten())

    def read_chunks(self) -> Generator[np.ndarray, None, None]:
        """Yield chunks while the stream is active."""
        while self.is_active():
            try:
                yield self.queue.get(timeout=0.1)
            except queue.Empty:
                continue

