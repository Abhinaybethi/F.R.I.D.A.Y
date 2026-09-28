"""
Research configuration.

Provider settings come from environment variables, falling back to the
``research:`` block in ``config.yaml``, then to safe defaults. No credentials
are ever hard-coded or logged. When research is disabled the subsystem is a
no-op and F.R.I.D.A.Y. continues exactly as before.
"""
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

# Environment variable names (mirror the task's suggested surface).
_ENV_ENABLED = "WEB_RESEARCH_ENABLED"
_ENV_PROVIDER = "WEB_SEARCH_PROVIDER"
_ENV_API_KEY = "WEB_SEARCH_API_KEY"
_ENV_MAX_RESULTS = "WEB_SEARCH_MAX_RESULTS"
_ENV_TIMEOUT = "WEB_SEARCH_TIMEOUT"

_DEFAULT_PROVIDER = "duckduckgo"


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        val = int(os.environ.get(name, "").strip() or default)
    except (ValueError, TypeError):
        return default
    return max(lo, min(hi, val))


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        val = float(os.environ.get(name, "").strip() or default)
    except (ValueError, TypeError):
        return default
    return max(lo, min(hi, val))


@dataclass
class ResearchConfig:
    """Resolved research subsystem settings (env > config.yaml > defaults)."""

    enabled: bool = False
    provider: str = _DEFAULT_PROVIDER
    api_key: str = ""
    max_results: int = 5
    timeout: float = 10.0
    max_queries: int = 3
    prefer_official: bool = False

    @classmethod
    def from_mapping(
        cls,
        mapping: Optional[Mapping] = None,
        env: Optional[Mapping] = None,
    ) -> "ResearchConfig":
        m = mapping if isinstance(mapping, Mapping) else {}
        e = env if isinstance(env, Mapping) else os.environ

        def pick(key: str, file_key: str):
            return e.get(key, m.get(file_key))

        enabled_raw = pick(_ENV_ENABLED, "enabled")
        provider_raw = pick(_ENV_PROVIDER, "provider")
        max_results = _env_int(_ENV_MAX_RESULTS, int(m.get("max_results", 5) or 5), 1, 20)
        timeout = _env_float(_ENV_TIMEOUT, float(m.get("timeout", 10) or 10), 1.0, 60.0)

        enabled = True
        if isinstance(enabled_raw, bool):
            enabled = enabled_raw
        elif isinstance(enabled_raw, str):
            enabled = enabled_raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            enabled = bool(m.get("enabled", False))

        provider = str(provider_raw or _DEFAULT_PROVIDER).strip().lower()
        if not provider:
            provider = _DEFAULT_PROVIDER

        api_key = str(pick(_ENV_API_KEY, "api_key") or "").strip()
        max_queries = int(m.get("max_queries", 3) or 3)
        max_queries = max(1, min(5, max_queries))
        prefer_official = bool(m.get("prefer_official", False))

        return cls(
            enabled=enabled,
            provider=provider,
            api_key=api_key,
            max_results=max_results,
            timeout=timeout,
            max_queries=max_queries,
            prefer_official=prefer_official,
        )

    @classmethod
    def load(cls, config_file: str = "config.yaml") -> "ResearchConfig":
        """Load research config from environment + optional config.yaml."""
        research_block: dict = {}
        try:
            import yaml

            with open(config_file, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            research_block = raw.get("research", {}) or {}
        except Exception:
            research_block = {}
        return cls.from_mapping(research_block)