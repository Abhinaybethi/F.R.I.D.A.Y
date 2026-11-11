"""
UNIT TEST — F.R.I.D.A.Y. desktop overlay plumbing
===================================================
Covers the thread-safe event bus (subscribe/emit/unregister, subscriber
failure isolation, lazy auto-start gating) and the pure geometry helpers the
overlay uses for thumbnails. No real Tk windows are opened here.
"""
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.ui import notify
from friday.ui.notify import (
    emit_image_event,
    emit_status_event,
    register_image_listener,
    unregister_image_listener,
)
from friday.ui.overlay import frame_dimensions, photo_subsample_factor


class SpyListener:
    def __init__(self) -> None:
        self.images = []
        self.statuses = []

    def on_image(self, path, metadata=None):
        self.images.append((path, metadata or {}))

    def on_status(self, status):
        self.statuses.append(status)


class BurstingListener:
    def on_image(self, path, metadata=None):
        raise RuntimeError("boom")

    def on_status(self, status):
        raise RuntimeError("boom")


class NotANotifier:
    pass


@pytest.fixture(autouse=True)
def _clean_bus():
    before = list(notify._events._snapshot())
    yield
    for sub in notify._events._snapshot():
        notify._events.unregister(sub)
    for sub in before:
        notify._events.register(sub)


def test_emit_reaches_all_subscribers():
    a, b = SpyListener(), SpyListener()
    register_image_listener(a)
    register_image_listener(b)
    emit_image_event(r"output\img.png", {"seed": 1})
    assert a.images == [(r"output\img.png", {"seed": 1})]
    assert b.images == [(r"output\img.png", {"seed": 1})]
    emit_status_event("GENERATING")
    assert a.statuses == ["GENERATING"]
    assert b.statuses == ["GENERATING"]


def test_unregister_stops_delivery():
    a = SpyListener()
    register_image_listener(a)
    unregister_image_listener(a)
    emit_image_event(r"output\img.png")
    assert a.images == []


def test_subscriber_exception_is_isolated():
    ok = SpyListener()
    bad = BurstingListener()
    register_image_listener(bad)
    register_image_listener(ok)
    emit_image_event(r"output\img.png", {"seed": 2})
    emit_status_event("SPEAKING")
    assert ok.images == [(r"output\img.png", {"seed": 2})]
    assert ok.statuses == ["SPEAKING"]


def test_non_notifier_subscriber_is_skipped():
    a = SpyListener()
    register_image_listener(NotANotifier())
    register_image_listener(a)
    emit_image_event(r"output\img.png")
    assert a.images[0][0].endswith("img.png")


def test_multithreaded_emit_is_safe():
    a = SpyListener()
    register_image_listener(a)
    errors = []

    def worker(n):
        try:
            for i in range(200):
                emit_image_event(f"out-{n}-{i}.png", {"n": n, "i": i})
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(a.images) == 800
    assert {meta["n"] for _, meta in a.images} == {0, 1, 2, 3}


def test_emit_does_not_autostart_when_disabled(monkeypatch):
    a = SpyListener()
    register_image_listener(a)
    monkeypatch.delenv("FRIDAY_OVERLAY", raising=False)
    notify._overlay = None
    emit_image_event(r"output\img.png")
    assert notify._overlay is None
    assert len(a.images) == 1


def _stub_overlay_module(monkeypatch, overlay_stub):
    import types as _types

    stub_module = _types.SimpleNamespace(start_overlay=overlay_stub)
    monkeypatch.setitem(sys.modules, "friday.ui.overlay", stub_module)


def test_autostart_gates_on_env_and_registers_listener(monkeypatch):
    class FakeOverlay:
        def __init__(self):
            self.images = []
            self.statuses = []

        def on_image(self, path, metadata=None):
            self.images.append((path, metadata or {}))

        def on_status(self, status):
            self.statuses.append(status)

        def spawn(self):
            pass

    fake = FakeOverlay()

    def fake_start(size=None):
        from friday.ui.notify import register_image_listener
        register_image_listener(fake)
        return fake

    _stub_overlay_module(monkeypatch, fake_start)

    monkeypatch.setenv("FRIDAY_OVERLAY", "1")
    notify._overlay = None
    emit_image_event(r"output\img.png", {"seed": 3})
    assert notify._overlay is fake
    assert fake.images == [(r"output\img.png", {"seed": 3})]

    notify._overlay = None
    emit_status_event("GENERATING")
    assert fake.statuses == ["GENERATING"]

    notify._overlay = None
    monkeypatch.delenv("FRIDAY_OVERLAY")
    emit_image_event(r"output\img2.png")
    assert notify._overlay is None
    assert fake.images[-1] == (r"output\img2.png", {})  # subscription persists


def test_autostart_stays_disabled_after_import_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no display")
    _stub_overlay_module(monkeypatch, boom)
    monkeypatch.setenv("FRIDAY_OVERLAY", "1")
    notify._overlay = None
    emit_image_event(r"output\img.png")
    assert notify._overlay is False  # sticky failure, no window spam


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def test_frame_dimensions_keeps_aspect():
    assert frame_dimensions(512, 512, 420) == (420, 420)
    assert frame_dimensions(1024, 768, 420) == (420, 315)
    assert frame_dimensions(300, 200, 420) == (300, 200)
    assert frame_dimensions(0, 0, 420) == (420, 420)
    assert frame_dimensions(100, 200, 1) == (1, 2)


def test_photo_subsample_factor():
    assert photo_subsample_factor(512, 420) == 2
    assert photo_subsample_factor(400, 420) == 1
    assert photo_subsample_factor(840, 420) == 2
    assert photo_subsample_factor(100, 420) == 1


class _FakeResult:
    def __init__(self, path):
        self._path = path

    def to_dict(self):
        return {
            "success": True,
            "path": self._path,
            "filename": "image_001.png",
            "prompt": "a cat",
            "width": 512,
            "height": 512,
        }

    def spoken_message(self):
        return "Done. I've generated the image."


class _FakeManager:
    def __init__(self, path):
        self.path = path

    def generate(self, **kwargs):
        return _FakeResult(self.path)


def test_generate_image_real_emits_event(tmp_path):
    from friday.tools.image_gen import generate_image

    img = tmp_path / "image_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    spy = SpyListener()
    register_image_listener(spy)
    result = generate_image("a cat", dry_run=False, manager=_FakeManager(str(img)))

    assert result["path"] == str(img)
    assert spy.images, "real generation must emit an image event"
    emitted_path, emitted_meta = spy.images[0]
    assert emitted_path == str(img)
    assert emitted_meta.get("width") == 512
    assert "event" not in emitted_meta


def test_generate_image_dry_run_emits_nothing():
    from friday.tools.image_gen import generate_image

    spy = SpyListener()
    register_image_listener(spy)
    generate_image("a cat", dry_run=True)
    assert spy.images == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])