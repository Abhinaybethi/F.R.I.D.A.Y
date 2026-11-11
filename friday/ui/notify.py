"""
Thread-safe UI event bus for F.R.I.D.A.Y.

Publishers (the image tool, the assistant progress phrase) emit non-blocking
image/status events; subscribers (the desktop overlay, tests) receive them on
whatever thread happened to emit. Emitting is always safe: subscriber failures
are isolated and never propagate to the caller.
"""
import os
import threading
from typing import Any, Callable, List, Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)

class _OverlayEventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: List[Any] = []

    def register(self, subscriber: Any) -> None:
        with self._lock:
            if subscriber not in self._subscribers:
                self._subscribers.append(subscriber)

    def unregister(self, subscriber: Any) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def _snapshot(self) -> List[Any]:
        with self._lock:
            return list(self._subscribers)

    def emit_image(self, path: str, metadata: Optional[dict] = None) -> None:
        for sub in self._snapshot():
            self._call(sub, "on_image", path, metadata or {})

    def emit_status(self, status: str) -> None:
        for sub in self._snapshot():
            self._call(sub, "on_status", status)

    @staticmethod
    def _call(sub, name: str, *args) -> None:
        handler = getattr(sub, name, None)
        if not callable(handler):
            return
        try:
            handler(*args)
        except Exception:
            logger.warning("[UI] subscriber %r failed in %s", sub, name, exc_info=True)


_events = _OverlayEventBus()

_overlay_lock = threading.Lock()
_overlay = None


def register_image_listener(subscriber: Any) -> None:
    _events.register(subscriber)


def unregister_image_listener(subscriber: Any) -> None:
    _events.unregister(subscriber)


def emit_image_event(path: str, metadata: Optional[dict] = None) -> None:
    """Publish a generated-image event. Safe from any thread."""
    _ensure_overlay_if_enabled()
    _events.emit_image(path, metadata)


def emit_status_event(status: str) -> None:
    """Publish a status text event (e.g. 'GENERATING'). Safe from any thread."""
    _ensure_overlay_if_enabled()
    _events.emit_status(status)


def _ensure_overlay_if_enabled() -> None:
    """Auto-start the desktop overlay once FRIDAY_OVERLAY is set truthy."""
    global _overlay
    if not os.environ.get("FRIDAY_OVERLAY"):
        return
    with _overlay_lock:
        if _overlay is not None:
            return
        try:
            from friday.ui.overlay import start_overlay
            _overlay = start_overlay()
        except Exception:
            logger.warning("[UI] overlay could not start", exc_info=True)
            _overlay = False