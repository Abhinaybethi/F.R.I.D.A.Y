"""Versioned, thread-safe event bus for the dashboard WebSocket.

Events are produced from both async request handlers and background threads
(the image tool, the assistant). ``publish_threadsafe`` bridges thread callers
onto the event loop so a single shared WebSocket broadcaster can fan events out
to every connected client without opening duplicate connections.
"""
import asyncio
import itertools
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

SCHEMA_VERSION = 1

_seq = itertools.count(1)
_seq_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event(
    event_type: str,
    *,
    source: str = "",
    message: str = "",
    task_id: Optional[str] = None,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a versioned event payload with a globally monotonic sequence."""
    with _seq_lock:
        seq = next(_seq)
    return {
        "type": event_type,
        "v": SCHEMA_VERSION,
        "seq": seq,
        "timestamp": utc_now(),
        "task_id": task_id,
        "status": status,
        "source": source,
        "message": message,
        "progress": progress,
        "data": data or {},
    }


class EventBus:
    """Fan-out bus with a bounded per-subscriber queue (drop-oldest)."""

    def __init__(self, max_queue: int = 512) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._max_queue = max_queue
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: Dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def publish_threadsafe(self, event: Dict[str, Any]) -> None:
        """Publish from a non-async thread (image tool, assistant callbacks)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.publish(event)))
        except RuntimeError:
            pass


bus = EventBus()


class _NotifyBridge:
    """Adapts the existing :mod:`friday.ui.notify` bus to dashboard events."""

    def on_image(self, path: str, metadata: Optional[dict] = None) -> None:
        bus.publish_threadsafe(
            make_event(
                "image.completed",
                source="image",
                status="completed",
                message="Image generated",
                data={"path": path, "metadata": metadata or {}},
            )
        )

    def on_status(self, status: str) -> None:
        bus.publish_threadsafe(
            make_event("status.updated", source="assistant", status=str(status))
        )


_notify_bridge: Optional[_NotifyBridge] = None


def install_notify_bridge() -> None:
    """Subscribe the dashboard to the existing UI notification bus (idempotent)."""
    global _notify_bridge
    if _notify_bridge is not None:
        return
    from friday.ui import notify

    _notify_bridge = _NotifyBridge()
    notify.register_image_listener(_notify_bridge)


def event_types() -> List[str]:
    return [
        "connection.ready",
        "server.heartbeat",
        "task.created",
        "task.updated",
        "task.completed",
        "task.failed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "model.changed",
        "model.unavailable",
        "voice.state",
        "voice.transcribed",
        "voice.handsfree",
        "transcript.updated",
        "research.started",
        "research.completed",
        "image.started",
        "image.completed",
        "image.failed",
        "automation.updated",
        "status.updated",
        # Generic failure channel. Declared in the contract so clients can
        # filter a schema-level error without guessing at an undeclared type;
        # domain-specific failures still use task.failed/image.failed/etc.
        "error",
    ]
