"""Lightweight, thread-safe activity/task store with JSON persistence.

Every record corresponds to a real operation performed by the assistant, a
tool, the image generator, research, or the voice pipeline. The store never
invents entries; an empty dashboard simply has no activity yet.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_STORE_PATH = "data/dashboard/activity.json"
MAX_ITEMS = 500

KIND_AGENT = "agent"
KIND_TOOL = "tool"
KIND_IMAGE = "image"
KIND_RESEARCH = "research"
KIND_VOICE = "voice"
KIND_CHAT = "chat"
KIND_CODE = "code"
KIND_SYSTEM = "system"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_BLOCKED = "blocked"
STATUS_WAITING = "waiting_approval"

_TERMINAL = {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_BLOCKED}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActivityStore:
    def __init__(self, path: str = DEFAULT_STORE_PATH, max_items: int = MAX_ITEMS) -> None:
        self.path = Path(path)
        self.max_items = max_items
        self._lock = threading.RLock()
        self._items: List[Dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            if self.path.is_file():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    self._items = [item for item in raw if isinstance(item, dict)][: self.max_items]
        except Exception:
            self._items = []

    def _save_locked(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._items, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def add(
        self,
        kind: str,
        title: str,
        *,
        source: str = "",
        status: str = STATUS_RUNNING,
        message: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        item = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "title": title,
            "source": source,
            "status": status,
            "message": message,
            "progress": None,
            "error": "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "completed_at": None,
            "started_ts": now,
            "duration_ms": None,
            "meta": meta or {},
        }
        with self._lock:
            self._items.insert(0, item)
            del self._items[self.max_items:]
            self._save_locked()
        return dict(item)

    def update(self, item_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            for item in self._items:
                if item.get("id") != item_id:
                    continue
                item.update({k: v for k, v in fields.items() if k not in ("id", "created_at")})
                item["updated_at"] = _now_iso()
                status = item.get("status")
                if status in _TERMINAL:
                    item["completed_at"] = item.get("completed_at") or _now_iso()
                    if item.get("duration_ms") is None:
                        item["duration_ms"] = round(
                            (time.time() - float(item.get("started_ts", time.time()))) * 1000.0, 1
                        )
                self._save_locked()
                return dict(item)
        return None

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for item in self._items:
                if item.get("id") == item_id:
                    return dict(item)
        return None

    def list(
        self,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        with self._lock:
            items = list(self._items)
        if kind:
            items = [i for i in items if i.get("kind") == kind]
        if status:
            items = [i for i in items if i.get("status") == status]
        if source:
            items = [i for i in items if i.get("source") == source]
        if search:
            needle = search.lower()
            items = [
                i for i in items
                if needle in str(i.get("title", "")).lower()
                or needle in str(i.get("message", "")).lower()
            ]
        total = len(items)
        start = max(0, int(offset))
        end = start + max(1, min(int(limit), 200))
        return {"total": total, "items": [dict(i) for i in items[start:end]]}

    def recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self.list(limit=limit)["items"]

    def counts(self) -> Dict[str, int]:
        with self._lock:
            items = list(self._items)
        result = {"total": len(items), "running": 0, STATUS_COMPLETED: 0, STATUS_FAILED: 0}
        for item in items:
            status = item.get("status")
            if status == STATUS_RUNNING:
                result["running"] += 1
            elif status in result:
                result[status] += 1
        return result
