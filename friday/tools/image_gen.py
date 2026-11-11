"""
Image generation tool — registry executor for Action.IMAGE_GENERATION.

The dry-run branch returns the standard tool contract with no side effects and
no model loading (assistant startup stays load-free). The real-execution branch
drives the QwenImageManager through a structured generation.

Result contract beyond the common keys:
    path, filename, prompt, width, height, steps, seed, provider,
    event="image_generated", metadata (self-describing sidecar payload)
"""
from typing import Dict, Optional

from friday.image.manager import QwenImageManager
from friday.intent.models import Intent
from friday.ui.notify import emit_image_event
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def _intent_args(intent: Optional[Intent]) -> Dict:
    if not intent:
        return {}
    args = getattr(intent, "arguments", None) or {}
    return args if isinstance(args, dict) else {}


def generate_image(
    target: str,
    dry_run: bool = True,
    intent: Optional[Intent] = None,
    manager: Optional[QwenImageManager] = None,
) -> dict:
    prompt = (target or "").strip()
    args = _intent_args(intent)

    if dry_run:
        return {
            "success": True,
            "message": (
                f"[DRY RUN] Would generate image of: {prompt!r} "
                f"({args.get('width', 768)}x{args.get('height', 768)}, "
                f"{args.get('steps', 8)} steps)."
            ),
            "spoken_message": "Generating the image now.",
            "event": "image_generated",
            "dry_run": True,
        }

    mgr = manager or QwenImageManager()
    result = mgr.generate(
        prompt=prompt,
        width=args.get("width"),
        height=args.get("height"),
        steps=args.get("steps"),
        seed=args.get("seed"),
    )
    data = result.to_dict()
    data["event"] = "image_generated"
    data["metadata"] = data.copy()
    data["metadata"].pop("event", None)
    data["spoken_message"] = result.spoken_message()
    if data.get("path"):
        emit_image_event(str(data["path"]), data.get("metadata") or {})
    return data