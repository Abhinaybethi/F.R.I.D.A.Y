"""CLI microphone wrapper, backed by the process-wide AudioHub.

``AudioInput`` keeps its historical contract (``start``/``drain``/``stop``/
``read_chunks``/``sample_levels``/``is_active``) but no longer opens its own
``sounddevice.InputStream``. It takes ownership of
:class:`~friday.voice.audio_hub.AudioHub` under the ``"cli"`` owner and taps the
hub's frames into a local queue, so the dashboard and the CLI can never open
two competing streams inside one process.
"""
import queue

import numpy as np
from typing import Generator

from friday.utils.logger import get_logger
from friday.voice.audio_hub import AudioHub, get_audio_hub

logger = get_logger(__name__)

OWNER = "cli"


class AudioInput:
    """
    Persistent microphone stream.

    Lifecycle
    ---------
    start()  → take hub ownership and subscribe to frames
    drain()  → flush stale queued chunks between utterances (do NOT close stream)
    stop()   → unsubscribe and release the hub at end of session
    """

    def __init__(self, sample_rate: int = 16000, chunk_size: int = 512, hub: AudioHub | None = None):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.queue: queue.Queue = queue.Queue()
        self.stream = None
        self._hub = hub or get_audio_hub()
        self._token: int | None = None

    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        """True if this wrapper currently owns a running hub stream."""
        hub = getattr(self, "_hub", None)
        if hub is not None and hub.owned_by(OWNER):
            return hub.active()
        stream = getattr(self, "stream", None)
        return stream is not None and bool(getattr(stream, "active", False))

    def start(self):
        """
        Take microphone ownership. Idempotent — safe to call when already running.
        """
        if self.is_active():
            return  # already open, nothing to do

        try:
            self._hub.acquire(OWNER, blocksize=self.chunk_size)
            self._token = self._hub.subscribe(self._callback)
            self.stream = self._hub.stream
            logger.info("Microphone initialized (shared audio hub).")
        except Exception as e:
            logger.error("Microphone initialization failed: %s", e)
            self._release()
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
        Release the microphone and hardware resources.
        Call only at end of session (Ctrl+C / shutdown).
        """
        if getattr(self, "stream", None) is not None:
            self._release()
            self.stream = None

        # Flush any remaining queued data
        self.drain()

    def _release(self) -> None:
        token = getattr(self, "_token", None)
        self._token = None
        if token is not None:
            try:
                self._hub.unsubscribe(token)
            except Exception:
                pass
        try:
            self._hub.release(OWNER)
        except Exception:
            pass

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
            import sounddevice as sd

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
    def _callback(self, indata, *args):
        # The hub calls subscribers with a flat float32 frame; the legacy
        # sounddevice callback shape is still tolerated for direct callers.
        if args:
            status = args[-1] if len(args) >= 3 else None
            if status:
                logger.debug("Audio input status: %s", status)
        self.queue.put(np.asarray(indata, dtype=np.float32).reshape(-1).copy())

    def read_chunks(self) -> Generator[np.ndarray, None, None]:
        """Yield chunks while the stream is active."""
        while self.is_active():
            try:
                yield self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
