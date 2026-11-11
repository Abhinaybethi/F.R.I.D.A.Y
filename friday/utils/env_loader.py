"""Zero-dependency ``.env`` loader for F.R.I.D.A.Y.

The project keeps secrets (the NVIDIA API key, optional search keys) in a
git-ignored ``.env`` file. Python does not read that file automatically, so
every entrypoint calls :func:`load_dotenv` exactly once before building any
service that reads credentials.

Behaviour
---------
* Looks for ``FRIDAY_ENV_FILE``, then ``./.env``, then the project-root
  ``.env`` (the directory containing ``config.yaml``/``main.py``). The first
  existing file wins.
* Never overrides variables that are already set unless ``override=True``.
* Supports ``export KEY=value``, single/double quoted values, ``\\n``/``\\t``
  escapes inside double quotes, and trailing ``# comments`` on unquoted values.
* Never logs values. Only the loaded key names are available to callers.

This module intentionally has no third-party dependency so it works even when
``python-dotenv`` is not installed.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

_LOCK = threading.RLock()
_LOADED_PATHS: set[str] = set()
_LOADED_KEYS: set[str] = set()


def _project_root() -> Path:
    # .../friday/utils/env_loader.py -> .../friday/utils -> .../friday -> root
    return Path(__file__).resolve().parents[2]


def _candidate_paths(explicit: Optional[str] = None) -> List[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    env_file = os.environ.get("FRIDAY_ENV_FILE", "").strip()
    if env_file:
        return [Path(env_file).expanduser()]
    return [Path.cwd() / ".env", _project_root() / ".env"]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        quote = value[0]
        inner = value[1:-1]
        if quote == "'":
            return inner
        # Double-quoted: honour the common escapes without mangling UTF-8.
        return (
            inner.replace("\\\\", "\x00")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\r", "\r")
            .replace("\x00", "\\")
        )
    # Unquoted: strip an inline comment introduced by whitespace + '#'.
    for marker in (" #", "\t#"):
        index = value.find(marker)
        if index != -1:
            value = value[:index].rstrip()
    return value


def _parse_line(line: str) -> Optional[tuple[str, str]]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].lstrip()
    if "=" not in line:
        return None
    key, raw = line.split("=", 1)
    key = key.strip()
    if not key or not (key[0].isalpha() or key[0] == "_"):
        return None
    if not all(ch.isalnum() or ch == "_" for ch in key):
        return None
    return key, _unquote(raw)


def _load_file(path: Path, override: bool) -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                parsed = _parse_line(line)
                if parsed is None:
                    continue
                key, value = parsed
                if override or key not in os.environ:
                    os.environ[key] = value
                    loaded[key] = value
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    return loaded


def load_dotenv(
    path: Optional[str] = None,
    override: bool = False,
    candidates: Optional[Sequence[str]] = None,
) -> Dict[str, str]:
    """Load a ``.env`` file into ``os.environ``.

    Returns a mapping of the keys that were actually applied. Existing
    environment variables win unless ``override=True``. Repeated calls are
    cheap and idempotent.
    """
    paths = [Path(p).expanduser() for p in candidates] if candidates else _candidate_paths(path)
    with _LOCK:
        for candidate in paths:
            try:
                resolved = str(candidate.resolve())
            except OSError:
                resolved = str(candidate)
            if resolved in _LOADED_PATHS and not override:
                continue
            if not candidate.is_file():
                continue
            loaded = _load_file(candidate, override)
            _LOADED_PATHS.add(resolved)
            _LOADED_KEYS.update(loaded)
            return loaded
    return {}


def loaded_keys() -> frozenset[str]:
    """Return the key names applied by previous :func:`load_dotenv` calls."""
    return frozenset(_LOADED_KEYS)


__all__ = ["load_dotenv", "loaded_keys"]
