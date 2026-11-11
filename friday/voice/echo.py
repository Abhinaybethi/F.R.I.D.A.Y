"""Echo suppression for the always-on microphone.

FRIDAY speaks through the same speakers its microphone hears. Without a gate,
the TTS output re-enters the mic, gets transcribed, and can trigger a false
barge-in or a repeated/garbled command. This module implements the first line
of defence: a playback gate plus an adaptive echo-floor.

How it works
------------
* :meth:`EchoSuppressor.mark_started` / :meth:`mark_stopped` are called by the
  TTS layer around actual speaker playback.
* While playback is active (plus a short hangover so the room tail is covered)
  the live RMS the mic sees is treated as *echo*, tracked in ``echo_floor``.
* Callers ask for the speech threshold for each frame. During playback the
  threshold is raised above the tracked echo level, so only speech that is
  clearly louder than FRIDAY's own voice opens the barge-in gate.

This is deliberately reference-free: it needs no loopback device and no
knowledge of the audio pipeline latency.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

# A frame is treated as echo while its level stays within this factor of the
# tracked echo floor; louder frames are left alone so user speech can raise
# the gate.
_ECHO_TRACK_FACTOR = 1.5
# How long after playback stops echo is still expected (room tail / buffers).
DEFAULT_HANGOVER_SECONDS = 0.25
# The mic must be at least this much louder than the echo floor to be speech.
DEFAULT_ECHO_MARGIN = 2.0
# Absolute ceiling for a gated frame. Requiring clipping-level input to barge
# in would make the assistant uninterruptible, so the raised threshold never
# goes above this.
DEFAULT_SCALE = 0.95


class EchoSuppressor:
    """Playback gate + adaptive echo floor, safe to share across threads."""

    def __init__(
        self,
        hangover_seconds: float = DEFAULT_HANGOVER_SECONDS,
        echo_margin: float = DEFAULT_ECHO_MARGIN,
        threshold_scale: float = DEFAULT_SCALE,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.hangover_seconds = max(0.0, float(hangover_seconds))
        self.echo_margin = max(1.0, float(echo_margin))
        self.threshold_scale = min(1.0, max(0.05, float(threshold_scale)))
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._depth = 0
        self._stopped_at: Optional[float] = None
        self._echo_floor: Optional[float] = None

    # ------------------------------------------------------------------
    # Playback state
    # ------------------------------------------------------------------
    def mark_started(self) -> None:
        with self._lock:
            self._depth += 1
            self._stopped_at = None
            self._echo_floor = None

    def mark_stopped(self) -> None:
        with self._lock:
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._stopped_at = self._clock()

    @property
    def playing(self) -> bool:
        with self._lock:
            return self._depth > 0

    def active(self) -> bool:
        """True while playback, or its hangover, can contaminate the mic."""
        with self._lock:
            if self._depth > 0:
                return True
            if self._stopped_at is None:
                return False
            return (self._clock() - self._stopped_at) < self.hangover_seconds

    def reset(self) -> None:
        """Drop tracking state (call between turns / on listener restart)."""
        with self._lock:
            self._depth = 0
            self._stopped_at = None
            self._echo_floor = None

    @contextmanager
    def playback(self) -> Iterator["EchoSuppressor"]:
        self.mark_started()
        try:
            yield self
        finally:
            self.mark_stopped()

    # ------------------------------------------------------------------
    # Frame gating
    # ------------------------------------------------------------------
    def threshold(self, base_threshold: float, rms: float) -> float:
        """Return the RMS threshold to use for this frame.

        ``base_threshold`` is the caller's normal speech threshold. When
        playback is active the echo floor is learned from the mic and the
        returned threshold sits above it.
        """
        base = max(1e-9, float(base_threshold))
        if not self.active():
            with self._lock:
                self._echo_floor = None
            return base

        level = max(0.0, float(rms))
        with self._lock:
            if self._echo_floor is None:
                self._echo_floor = max(level, base)
            elif level <= self._echo_floor * _ECHO_TRACK_FACTOR:
                # Still inside the echo envelope: track it, don't let it decay
                # instantly (speech pauses in the TTS output must not reset it).
                self._echo_floor = 0.85 * self._echo_floor + 0.15 * level
            raised = max(base * 2.0, self._echo_floor * self.echo_margin)
            return min(raised, self.threshold_scale)

    @property
    def echo_floor(self) -> Optional[float]:
        with self._lock:
            return self._echo_floor


_GLOBAL_GATE = EchoSuppressor()


def get_playback_gate() -> EchoSuppressor:
    """Process-wide gate shared by the TTS layer and the mic consumers."""
    return _GLOBAL_GATE


def reset_playback_gate() -> None:
    _GLOBAL_GATE.reset()
