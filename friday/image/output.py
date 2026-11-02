"""
Output handling for generated images.

Produces deterministic, unique, never-overwritten filenames under a
``YYYY-MM-DD`` folder (``image_###.png`` + ``image_###.json``), validates the
written PNG, and writes a self-describing metadata sidecar.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from friday.utils.logger import get_logger

logger = get_logger(__name__)

_FILENAME_RE = re.compile(r"^image_(\d+)\.png$")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Session-scoped high-watermark per day directory so that two allocations made
# before either file exists still reserve disjoint names (never overwrite).
_LAST_INDEX: Dict[str, int] = {}


def ensure_output_dir(output_dir: Path, now: Optional[datetime] = None) -> Path:
    """Create ``output_dir/YYYY-MM-DD`` and return it. Raises OSError on failure."""
    day_dir = output_dir / (now or datetime.now()).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def allocate_output_path(output_dir: Path, now: Optional[datetime] = None) -> Path:
    """
    Return the next free ``image_###.png`` path. Never overwrites: successive
    calls allocate monotonically increasing indexes even when files were
    deleted between calls, and even before any file is created.
    """
    day_dir = ensure_output_dir(output_dir, now=now)
    max_index = _LAST_INDEX.get(str(day_dir), 0)
    try:
        for entry in day_dir.iterdir():
            m = _FILENAME_RE.match(entry.name)
            if m:
                max_index = max(max_index, int(m.group(1)))
    except OSError:
        pass
    index = max_index + 1
    _LAST_INDEX[str(day_dir)] = index
    return day_dir / f"image_{index:03d}.png"


def write_metadata(day_dir: Path, filename: str, payload: Dict) -> Optional[str]:
    """Write ``<stem>.json`` sidecar next to the image. Returns its path."""
    stem = Path(filename).stem
    meta_path = Path(day_dir) / f"{stem}.json"
    try:
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=True)
        return str(meta_path)
    except OSError as e:
        logger.warning("[IMAGE] metadata write failed for %s: %s", meta_path, e)
        return None


def is_valid_png(path: Path) -> bool:
    """True when the file exists, is non-empty, and carries a PNG signature.

    Uses Pillow (installed) when available for a deeper decode check, but the
    signature check alone works without any dependency.
    """
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with open(path, "rb") as fh:
            head = fh.read(len(_PNG_MAGIC))
        if head != _PNG_MAGIC:
            return False
        try:
            from PIL import Image
        except Exception:
            # No decoder available: the signature check is the strongest signal.
            return True
        try:
            with Image.open(path) as img:
                img.verify()
        except Exception:
            return False
        return True
    except OSError:
        return False


def parse_seed(raw: Optional[str]) -> int:
    """Parse ``--seed`` argument conservatively (None when unset/invalid)."""
    if raw is None:
        return -1
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return -1
    return max(0, val)


def cleanup_if_failed(output_path: Path) -> None:
    """Remove a half-written output file plus its sidecar, if any."""
    try:
        if output_path.exists():
            output_path.unlink()
        meta = output_path.with_suffix(".json")
        if meta.exists():
            meta.unlink()
    except OSError as e:
        logger.warning("[IMAGE] cleanup of %s failed: %s", output_path, e)