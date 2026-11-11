"""
Process-wide GPU-memory release hooks.

Image generation wants the GPU's VRAM, but other F.R.I.D.A.Y. components (the
llama.cpp reasoner server) hold some of it. Rather than make the image module
import reasoning internals, the assistant registers a hook here. Around a
generation the manager runs every hook, each of which frees its memory and
returns an optional callable that restores it.
"""
import threading
from typing import Callable, List, Optional

from friday.utils.logger import get_logger

logger = get_logger(__name__)

Restore = Callable[[], None]
ReleaseHook = Callable[[], Optional[Restore]]

_lock = threading.Lock()
_release_hooks: List[ReleaseHook] = []


def register_gpu_release_hook(hook: ReleaseHook) -> None:
    """Register a callable that frees GPU memory and returns a restore hook."""
    with _lock:
        if hook not in _release_hooks:
            _release_hooks.append(hook)


def clear_gpu_release_hooks() -> None:
    """Remove all registered hooks (used to replace a prior assistant)."""
    with _lock:
        _release_hooks.clear()


def release_gpu_memory() -> List[Restore]:
    """Run every release hook; return the restore callables in run order.

    Hooks are best-effort: a failing hook is logged and skipped so a broken
    releaser never prevents image generation from starting.
    """
    with _lock:
        hooks = list(_release_hooks)
    restores: List[Restore] = []
    for hook in hooks:
        try:
            restore = hook()
        except Exception as e:
            logger.warning("[GPU] release hook failed: %s", e)
            continue
        if callable(restore):
            restores.append(restore)
    return restores


def restore_gpu_memory(restores: Optional[List[Restore]]) -> None:
    """Run restore hooks in reverse order; failures are logged, never raised."""
    for restore in reversed(restores or []):
        try:
            restore()
        except Exception as e:
            logger.warning("[GPU] restore hook failed: %s", e)
