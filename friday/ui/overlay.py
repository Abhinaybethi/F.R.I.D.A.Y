"""
Desk-only desktop overlay for F.R.I.D.A.Y.

A lightweight, always-on-top, frameless status chip (bottom-right corner) that
also expands to show a generated image plus the confirmation phrase. It is
driven by the ``friday.ui.notify`` event bus, so any thread producing an image
can trigger the display without touching Tk directly.

Optional extras (best effort, never required): pywin32 adds click-through and
a transparent window style; Pillow improves thumbnail scaling (falls back to
plain tk.PhotoImage scaling when absent).

Run a standalone demo::

    python -m friday.ui.overlay --image output\\...\\image_001.png

Enable auto-start inside F.R.I.D.A.Y. (image + status events open the chip):

    $env:FRIDAY_OVERLAY = "1"

Threading note: Tk objects are created, driven and destroyed on the same single
thread (the one entering ``run``). Emitters only touch a ``queue.Queue``, so no
Tcl call ever crosses threads and no Tcl object is finalized off-thread.
"""
import atexit
import math
import queue
import threading
from pathlib import Path
from typing import Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from PIL import Image as PILImage, ImageTk
except Exception:  # pragma: no cover - Pillow is optional
    PILImage = None
    ImageTk = None


def frame_dimensions(width: int, height: int, max_width: int) -> tuple:
    """Scale (width, height) to fit within ``max_width`` keeping aspect."""
    if width <= 0 or height <= 0:
        return max(1, max_width), max_width
    if width <= max_width:
        return width, height
    factor = width / float(max_width)
    return max_width, max(1, int(round(height / factor, 0)))


def photo_subsample_factor(width: int, max_width: int) -> int:
    """Integer divide factor for plain tk.PhotoImage scaling."""
    if width <= max_width:
        return 1
    return max(1, int(math.ceil(width / float(max_width))))


class FridayOverlay:
    """Tk window. Build + mainloop it on one thread; emit from any thread."""

    DEFAULT_MAX_WIDTH = 420
    HOLD_IMAGE_MS = 9000
    HOLD_STATUS_MS = 4000
    IDLE_TEXT = "[IDLE]"

    def __init__(
        self,
        max_width: int = DEFAULT_MAX_WIDTH,
        margin: int = 24,
        alpha: float = 0.96,
    ) -> None:
        self.max_width = max_width
        self.margin = margin
        self.alpha = alpha
        self.root = None
        self._status_label = None
        self._image_label = None
        self._visible = None
        self._thread: Optional[threading.Thread] = None

        self._queue: "queue.Queue" = queue.Queue()
        self._photo_refs = []
        self._collapse_id = None
        self._stop_requested = threading.Event()

    # -- cross-thread API --------------------------------------------------
    def on_image(self, path: str, metadata: Optional[dict] = None) -> None:
        self._queue.put(("image", str(path), metadata or {}))

    def on_status(self, status: str) -> None:
        self._queue.put(("status", str(status), {}))

    # -- lifecycle ---------------------------------------------------------
    def run(self, timeout_ms: Optional[int] = None) -> None:
        """Build the window and run the Tk mainloop on the calling thread."""
        import tkinter as tk

        self._tk = tk
        root = self.root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", self.alpha)
        except tk.TclError:
            pass

        self._status_label = tk.Label(
            root,
            text=self.IDLE_TEXT,
            font=("Segoe UI", 10, "bold"),
            fg="#e8eaed",
            bg="#202125",
            padx=12,
            pady=6,
        )
        self._image_label = tk.Label(root, bg="#101114", bd=0, compound="top")
        self._visible = None
        root.after(40, self._poll)
        if timeout_ms:
            root.after(timeout_ms, self._close)
        root.deiconify()
        self._place_chip()
        try:
            root.mainloop()
        finally:
            self._teardown()

    def spawn(self) -> threading.Thread:
        def _target() -> None:
            try:
                self.run()
            except Exception:
                logger.warning("[OVERLAY] window thread exited", exc_info=True)

        thread = threading.Thread(
            target=_target,
            name="friday-overlay",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return thread

    def stop(self, join_timeout: float = 0.0) -> None:
        """Signal the Tk thread to close. Safe to call from any thread."""
        self._stop_requested.set()
        if join_timeout and self._thread is not None:
            self._thread.join(timeout=join_timeout)

    def _close(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def _teardown(self) -> None:
        """Called on the Tk thread after mainloop; drop all Tcl references here."""
        import tkinter as tk

        try:
            if getattr(tk, "_default_root", None) is self.root:
                tk._default_root = None
        except Exception:
            pass
        self.root = None
        self._status_label = None
        self._image_label = None
        self._visible = None
        self._photo_refs = []
        self._collapse_id = None
        self._tk = None

    # -- internal (Tk thread only below) ------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                kind, payload, meta = self._queue.get_nowait()
                if kind == "image":
                    self._show_image(payload, meta)
                elif kind == "status":
                    self._show_status(payload)
        except queue.Empty:
            pass
        if self._stop_requested.is_set():
            self._close()
            return
        try:
            self.root.after(40, self._poll)
        except Exception:
            pass

    def _show_image(self, path: str, metadata: dict) -> None:
        if not Path(path).is_file():
            self._show_status(f"[{Path(path).name} missing]")
            return
        photo = self._load_thumbnail(path)
        if photo is None:
            self._show_status(f"[{Path(path).name} unreadable]")
            return
        self._photo_refs.append(photo)
        if len(self._photo_refs) > 4:
            self._photo_refs.pop(0)

        caption = "Done. I've generated the image.\n" + str(path)
        self._image_label.configure(image=photo, text=caption)
        self._image_label.image = photo
        self._show(self._image_label)
        self._schedule_collapse(self.HOLD_IMAGE_MS)
        logger.info(
            "[OVERLAY] showing %s (%sx%s)", Path(path).name, photo.width(), photo.height()
        )

    def _load_thumbnail(self, path: str):
        try:
            if PILImage is not None:
                with PILImage.open(path) as im:
                    width, height = im.size
                    width, height = frame_dimensions(width, height, self.max_width)
                    thumb = im.convert("RGB").resize(
                        (width, height), PILImage.Resampling.LANCZOS
                    )
                    return ImageTk.PhotoImage(thumb)
        except Exception:
            return None

        import tkinter as tk

        try:
            photo = tk.PhotoImage(file=path)
            factor = photo_subsample_factor(photo.width(), self.max_width)
            if factor > 1:
                photo = photo.subsample(factor, factor)
            return photo
        except tk.TclError:
            return None

    def _show_status(self, status: str) -> None:
        self._status_label.configure(
            text=f"[{status.strip().strip('[]')}]" if status else self.IDLE_TEXT
        )
        self._show(self._status_label)
        self._schedule_collapse(self.HOLD_STATUS_MS)

    def _show(self, widget) -> None:
        if self._visible is widget:
            return
        if self._visible is not None:
            self._visible.pack_forget()
        self._visible = widget
        widget.pack(padx=8, pady=8)
        self._place_chip()

    def _schedule_collapse(self, hold_ms: int) -> None:
        if self._collapse_id is not None:
            try:
                self.root.after_cancel(self._collapse_id)
            except Exception:
                pass
        self._collapse_id = self.root.after(hold_ms, self._collapse)

    def _collapse(self) -> None:
        self._status_label.configure(text=self.IDLE_TEXT)
        self._show(self._status_label)

    def _place_chip(self) -> None:
        try:
            self.root.update_idletasks()
            w = self.root.winfo_reqwidth()
            h = self.root.winfo_reqheight()
            x = self.root.winfo_screenwidth() - w - self.margin
            y = self.root.winfo_screenheight() - h - self.margin
            self.root.geometry(f"{max(1, w)}x{max(1, h)}+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass


def start_overlay(size: Optional[int] = None) -> FridayOverlay:
    """Build a FridayOverlay, subscribe it to the event bus, and spawn it."""
    from friday.ui.notify import register_image_listener

    overlay = FridayOverlay(max_width=size or FridayOverlay.DEFAULT_MAX_WIDTH)
    register_image_listener(overlay)
    thread = overlay.spawn()
    atexit.register(_shutdown_overlay, overlay, thread)
    return overlay


def _shutdown_overlay(overlay: FridayOverlay, thread: threading.Thread) -> None:
    try:
        overlay.stop(join_timeout=0.7)
    except Exception:
        pass


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m friday.ui.overlay",
        description="Desktop overlay demo for F.R.I.D.A.Y.",
    )
    parser.add_argument("--image", default="", help="Path to an image to display.")
    parser.add_argument("--status", default="GENERATING", help="Status text before any image.")
    parser.add_argument("--hold", type=float, default=8.0, help="Seconds to hold the image.")
    parser.add_argument("--max-width", type=int, default=420)
    args = parser.parse_args(argv)

    overlay = FridayOverlay(max_width=args.max_width)
    if args.status:
        overlay.on_status(args.status)
    if args.image:
        overlay.on_image(args.image)

    overlay.run(timeout_ms=int((args.hold + 3.0) * 1000))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())