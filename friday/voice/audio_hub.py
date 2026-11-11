"""Single microphone owner + frame fan-out for the whole process.

FRIDAY used to open one ``sounddevice.InputStream`` per consumer (the dashboard
hands-free listener, the CLI voice session, the dashboard recorder). Two open
streams on one microphone either fail at the OS level or make each consumer
fight over the same device, and neither can know when the other is recording.

:class:`AudioHub` owns exactly one stream:

* one *owner* at a time (``acquire("handsfree")`` / ``release("handsfree")``);
* the owner's requested block size is honoured when the stream opens;
* any number of read-only *subscribers* may tap the frames (fan-out does not
  affect ownership);
* the process-wide instance is reachable through :func:`get_audio_hub`.

The owner lock is process-global, not machine-global: a separately started CLI
process still arbitrates with the OS. It does, however, guarantee the dashboard
itself never opens two competing streams.
"""
from __future__ import annotations

import itertools
import threading
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from friday.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_BLOCK_MS = 32

# A stream callback must do as little as possible. Each subscriber is wrapped
# so one failing consumer cannot silence the others.
Subscriber = Callable[[np.ndarray], None]


def _default_stream_factory(**kwargs):
    import sounddevice as sd

    return sd.InputStream(**kwargs)


class AudioHub:
    """One microphone stream with an explicit owner and frame subscribers."""

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
        stream_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.sample_rate = max(8000, int(sample_rate))
        self.channels = max(1, int(channels))
        self._stream_factory = stream_factory or _default_stream_factory
        self._lock = threading.RLock()
        self._stream = None
        self._owner: Optional[str] = None
        self._blocksize: Optional[int] = None
        self._subscribers: Dict[int, Subscriber] = {}
        self._tokens = itertools.count(1)
        self._frames = 0

    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------
    @property
    def owner(self) -> Optional[str]:
        with self._lock:
            return self._owner

    @property
    def stream(self):
        with self._lock:
            return self._stream

    def active(self) -> bool:
        with self._lock:
            stream = self._stream
        try:
            return stream is not None and bool(stream.active)
        except Exception:
            return stream is not None

    def owned_by(self, owner: str) -> bool:
        with self._lock:
            return self._owner == owner

    def _desired_block(self, block_ms: Optional[int], blocksize: Optional[int]) -> int:
        if blocksize is not None:
            return max(64, int(blocksize))
        if block_ms is not None:
            return max(64, int(self.sample_rate * float(block_ms) / 1000.0))
        return max(64, int(self.sample_rate * DEFAULT_BLOCK_MS / 1000.0))

    def acquire(
        self,
        owner: str,
        block_ms: Optional[int] = None,
        blocksize: Optional[int] = None,
        device: Optional[int] = None,
    ) -> bool:
        """Take microphone ownership and open the stream.

        Raises ``RuntimeError`` when another owner already holds the hub. The
        error is deliberately loud: silently opening a second stream is the
        bug this class exists to prevent.
        """
        if not owner:
            raise ValueError("AudioHub.acquire requires a non-empty owner name")

        desired = self._desired_block(block_ms, blocksize)
        to_close = None
        should_open = False

        with self._lock:
            if self._owner is not None and self._owner != owner:
                raise RuntimeError(
                    f"microphone is already owned by {self._owner!r}; "
                    f"{owner!r} cannot open a second stream"
                )
            self._owner = owner
            if self._stream is not None and self._blocksize not in (None, desired):
                # Same owner asked for a different block size: restart.
                to_close = self._stream
                self._stream = None
            if self._stream is None:
                self._blocksize = desired
                should_open = True

        if to_close is not None:
            self._close_stream(to_close)

        if should_open:
            try:
                stream = self._stream_factory(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    blocksize=desired,
                    device=device,
                    callback=self._on_audio,
                )
                stream.start()
            except Exception:
                with self._lock:
                    if self._owner == owner:
                        self._owner = None
                        self._blocksize = None
                raise
            with self._lock:
                # A concurrent stop() may have landed while we opened; honour it.
                if self._owner != owner:
                    stale = stream
                else:
                    self._stream = stream
                    stale = None
            if stale is not None:
                self._close_stream(stale)
                raise RuntimeError("microphone ownership changed while opening the stream")
            logger.info(
                "[AUDIO] stream opened for %r (%d Hz, block=%d)",
                owner,
                self.sample_rate,
                desired,
            )
        return True

    def release(self, owner: str) -> bool:
        """Release ownership and close the stream when this owner still holds it."""
        stream = None
        with self._lock:
            if self._owner != owner:
                return False
            stream = self._stream
            self._stream = None
            self._owner = None
            self._blocksize = None
        if stream is not None:
            self._close_stream(stream)
        logger.info("[AUDIO] stream released by %r", owner)
        return True

    def start(self, block_ms: int = DEFAULT_BLOCK_MS, owner: Optional[str] = None) -> bool:
        """Open the stream without changing an existing owner when one is set."""
        with self._lock:
            current = self._owner
        target = owner or current or "system"
        return self.acquire(target, block_ms=block_ms)

    def stop(self) -> None:
        """Force-close the stream regardless of owner (shutdown path)."""
        stream = None
        with self._lock:
            stream = self._stream
            self._stream = None
            self._owner = None
            self._blocksize = None
        if stream is not None:
            self._close_stream(stream)

    # ------------------------------------------------------------------
    # Frame subscribers
    # ------------------------------------------------------------------
    def subscribe(self, callback: Subscriber) -> int:
        """Register a read-only frame consumer; returns a token to unsubscribe."""
        if not callable(callback):
            raise TypeError("AudioHub.subscribe requires a callable")
        with self._lock:
            token = next(self._tokens)
            self._subscribers[token] = callback
            return token

    def unsubscribe(self, token: int) -> bool:
        with self._lock:
            return self._subscribers.pop(token, None) is not None

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # ------------------------------------------------------------------
    # Stream callback
    # ------------------------------------------------------------------
    def _on_audio(self, indata, _frames, _time_info, status) -> None:
        if status:
            logger.debug("[AUDIO] input status: %s", status)
        data = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        if data.size == 0:
            return
        with self._lock:
            self._frames += 1
            subscribers: List[Subscriber] = list(self._subscribers.values())
        for callback in subscribers:
            try:
                callback(data)
            except Exception as exc:  # subscriber bugs must not kill audio
                logger.debug("[AUDIO] subscriber failed: %s", exc)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def state(self) -> Dict[str, Any]:
        with self._lock:
            owner = self._owner
            blocksize = self._blocksize
            subscribers = len(self._subscribers)
            frames = self._frames
            stream = self._stream
        try:
            running = stream is not None and bool(stream.active)
        except Exception:
            running = stream is not None
        return {
            "owner": owner,
            "active": running,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "blocksize": blocksize,
            "block_ms": round(1000.0 * blocksize / self.sample_rate, 1) if blocksize else None,
            "subscribers": subscribers,
            "frames": frames,
        }

    def health(self) -> Dict[str, Any]:
        """Small health summary for the dashboard's health endpoint."""
        state = self.state()
        return {
            "status": "healthy" if state["active"] or state["owner"] is None else "degraded",
            "detail": (
                f"owner={state['owner'] or 'idle'} block={state['blocksize'] or '-'} "
                f"subscribers={state['subscribers']}"
            ),
        }

    # ------------------------------------------------------------------
    def _close_stream(self, stream) -> None:
        try:
            stream.stop()
        except Exception as exc:
            logger.debug("[AUDIO] stream stop failed: %s", exc)
        try:
            stream.close()
        except Exception as exc:
            logger.debug("[AUDIO] stream close failed: %s", exc)


_HUB: Optional[AudioHub] = None
_HUB_LOCK = threading.Lock()


def get_audio_hub() -> AudioHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = AudioHub()
        return _HUB


def reset_audio_hub() -> None:
    """Tear down the process-wide hub (tests / process shutdown)."""
    global _HUB
    with _HUB_LOCK:
        hub = _HUB
        _HUB = None
    if hub is not None:
        hub.stop()
