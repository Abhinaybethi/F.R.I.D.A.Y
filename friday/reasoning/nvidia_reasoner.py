"""NVIDIA API Catalog provider for F.R.I.D.A.Y.

Uses the OpenAI Python SDK against an OpenAI-compatible NVIDIA endpoint.

Credentials are read exclusively from environment variables (never from
``config.yaml`` secrets and never logged):

    NVIDIA_API_KEY / FRIDAY_NVIDIA_API_KEY      bearer token
    NVIDIA_BASE_URL / FRIDAY_NVIDIA_BASE_URL    default integrate.api.nvidia.com/v1
    NVIDIA_MODEL / FRIDAY_NVIDIA_MODEL          default nvidia/nemotron-3.5-bolt-e4b

Design notes
------------
* The client is created lazily. A missing/invalid key never raises from the
  constructor — the provider simply reports itself unavailable so the caller
  can fall back to the local Bonsai/llama.cpp provider.
* Works with the existing :class:`Reasoner` contract: ``request()`` returns a
  validated structured dict in ``action`` mode and a ``{"type": "response"}``
  dict in ``chat`` mode, using the same prompts/parsers as the local reasoner.
* ``request_stream()`` yields incremental text chunks for callers that want
  token-by-token output.
* Model capabilities are not assumed: tool calls are only sent when a caller
  explicitly supplies tools, and unsupported parameters are never guessed.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Optional

try:  # pragma: no cover - import guard keeps the module importable without SDK
    import openai
except Exception:  # pragma: no cover
    openai = None  # type: ignore[assignment]

from friday.reasoning.interface import Reasoner
from friday.reasoning.prompt import SYSTEM_PROMPT
from friday.reasoning.chat_prompt import CHAT_PROMPT
from friday.reasoning.parser import parse_reasoning_output
from friday.reasoning.validator import validate_reasoning_output
from friday.planning.context_resolver import ShortTermContext
from friday.utils.logger import get_logger

logger = get_logger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3.5-bolt-e4b"
DEFAULT_TIMEOUT = 30.0

_ENV_ALIASES = {
    "api_key": ("NVIDIA_API_KEY", "FRIDAY_NVIDIA_API_KEY"),
    "base_url": ("NVIDIA_BASE_URL", "FRIDAY_NVIDIA_BASE_URL"),
    "model": ("NVIDIA_MODEL", "FRIDAY_NVIDIA_MODEL"),
}


def _first_env(names: Iterable[str]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""


def _env_raw() -> Dict[str, str]:
    """Return raw environment values (empty string when unset)."""
    return {key: _first_env(names) for key, names in _ENV_ALIASES.items()}


def _env_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Resolve the effective NVIDIA settings.

    Priority for model/base URL: environment > ``config`` > built-in default.
    The API key is **only** read from the environment; it is never accepted
    from ``config.yaml``.
    """
    raw = _env_raw()
    cfg = config or {}
    return {
        "api_key": raw["api_key"],
        "base_url": raw["base_url"]
        or str(cfg.get("base_url") or "").strip()
        or DEFAULT_BASE_URL,
        "model": raw["model"] or str(cfg.get("model") or "").strip() or DEFAULT_MODEL,
    }


def resolve_settings(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Public helper: env-over-config resolution without constructing a client."""
    return _env_config(config)


def has_credentials() -> bool:
    """True when an NVIDIA API key is present in the environment."""
    return bool(_env_raw()["api_key"])


def _scrub(text: str, secret: str) -> str:
    if text and secret:
        return text.replace(secret, "***")
    return text


def _extract_content(response: Any) -> str:
    """Safely pull text out of a chat-completion response object/dict."""
    try:
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            return ""
        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None and isinstance(choice, dict):
            message = choice.get("message")
        if message is None:
            return ""
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        return content if isinstance(content, str) else ""
    except Exception:
        return ""


class NVIDIAReasoner(Reasoner):
    """NVIDIA API Catalog provider implementing :class:`Reasoner`."""

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        env = _env_config({"model": model, "base_url": base_url})
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        self.model = env["model"]
        self.base_url = env["base_url"]
        self.api_key = (api_key or env["api_key"]).strip()
        # Cached capability flag. We never *assume* tool support.
        self._supports_tools: Optional[bool] = None
        self._client = self._make_client()

    # ── Client lifecycle ────────────────────────────────────────────────

    def _make_client(self):
        if not self.api_key or openai is None:
            return None
        try:
            return openai.OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
                max_retries=0,  # fail fast so the router can fall back
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[REASONER] Unable to initialise NVIDIA client: %s",
                _scrub(str(exc), self.api_key),
            )
            return None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def close(self) -> None:
        client = getattr(self, "_client", None)
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    # ── Reasoner interface ──────────────────────────────────────────────

    def is_available(self) -> bool:
        """Best-effort reachability/auth check. Never raises."""
        if self._client is None:
            return False
        try:
            self._client.models.list()
            return True
        except Exception:
            return False

    def health(self) -> str:
        """Human-readable health string. Never contains the API key."""
        if self._client is None:
            return "NVIDIA not configured (missing API key)"
        return (
            f"NVIDIA reachable ({self.model})"
            if self.is_available()
            else "NVIDIA unreachable"
        )

    def request(
        self,
        transcript: str,
        context: ShortTermContext,
        mode: str = "action",
        retrieval_context: str = "",
    ) -> dict:
        """Run a single completion and normalise the result.

        Returns an error dict instead of raising when the provider is not
        configured or the call fails, so callers can fall back cleanly.
        """
        if self._client is None:
            return {
                "type": "error",
                "error": "missing_credentials",
                "message": "NVIDIA API key not configured",
                "provider": "nvidia",
            }

        start = time.monotonic()
        try:
            messages = self._build_messages(transcript, context, mode, retrieval_context)
            temperature, max_tokens = self._generation_params(mode)
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": self.timeout,
            }

            logger.debug(
                "[REASONER] Sending to NVIDIA (model=%s mode=%s)", self.model, mode
            )
            response = self._client.chat.completions.create(**payload)
            raw = _extract_content(response).strip()

            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = (
                getattr(usage, "completion_tokens", None)
                if usage
                else max(1, len(raw) // 4)
            )
            if usage:
                logger.info(
                    "[LLM] provider=nvidia prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                    getattr(usage, "total_tokens", None),
                )

            latency_ms = (time.monotonic() - start) * 1000.0
            result = self._normalise_output(raw, mode)
            result.setdefault("provider", "nvidia")
            result.setdefault("model", self.model)
            result.setdefault("latency_ms", round(latency_ms, 1))
            if prompt_tokens is not None:
                result.setdefault("prompt_tokens", prompt_tokens)
            if completion_tokens is not None:
                result.setdefault("completion_tokens", completion_tokens)
            return result

        except Exception as exc:  # noqa: BLE001 - mapped explicitly below
            return self._error_from_exception(exc)

    # ── Streaming ───────────────────────────────────────────────────────

    def request_stream(
        self,
        transcript: str,
        context: ShortTermContext,
        mode: str = "chat",
        retrieval_context: str = "",
    ) -> Iterable[str]:
        """Yield incremental text deltas for streaming consumers.

        Errors are yielded as a single ``"[error] ..."`` chunk rather than
        raised, matching the non-streaming error contract.
        """
        if self._client is None:
            yield "[error] NVIDIA API key not configured"
            return

        messages = self._build_messages(transcript, context, mode, retrieval_context)
        temperature, max_tokens = self._generation_params(mode)
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.timeout,
            )
            for chunk in stream:
                delta = self._extract_delta(chunk)
                if delta:
                    yield delta
        except Exception as exc:  # noqa: BLE001
            err = self._error_from_exception(exc)
            yield f"[error] {err.get('message', 'NVIDIA request failed')}"

    @staticmethod
    def _extract_delta(chunk: Any) -> str:
        try:
            choices = getattr(chunk, "choices", None)
            if not choices and isinstance(chunk, dict):
                choices = chunk.get("choices")
            if not choices:
                return ""
            delta = getattr(choices[0], "delta", None)
            if delta is None and isinstance(choices[0], dict):
                delta = choices[0].get("delta")
            content = getattr(delta, "content", None)
            if content is None and isinstance(delta, dict):
                content = delta.get("content")
            return content if isinstance(content, str) else ""
        except Exception:
            return ""

    # ── Helpers ─────────────────────────────────────────────────────────

    def _build_messages(
        self,
        transcript: str,
        context: Optional[ShortTermContext],
        mode: str,
        retrieval_context: str,
    ) -> List[Dict[str, str]]:
        context_str = ""
        if context is not None:
            if getattr(context, "last_search_query", ""):
                context_str += f"- Last search query: '{context.last_search_query}'\n"
            if getattr(context, "last_action", None):
                context_str += f"- Last action: {context.last_action.name}\n"
            if getattr(context, "last_transcript", ""):
                context_str += f"- Last transcript: '{context.last_transcript}'\n"

        user_content = f"Transcript: {transcript}\n\n"
        if context_str:
            user_content += f"Context:\n{context_str}\n"
        if mode == "chat" and retrieval_context:
            user_content += f"\n{retrieval_context}\n"

        system_prompt = CHAT_PROMPT if mode == "chat" else SYSTEM_PROMPT
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _generation_params(mode: str):
        # Chat output can be long; reasoning-style models also spend tokens on
        # hidden reasoning before emitting content, so leave a generous budget.
        if mode == "chat":
            return 0.4, 768
        return 0.0, 512

    @staticmethod
    def _normalise_output(raw: str, mode: str) -> dict:
        if not raw:
            return {"type": "error", "error": "empty_response", "message": "NVIDIA returned an empty response"}
        if mode == "chat":
            trimmed = raw.strip()
            if trimmed.startswith("{"):
                parsed = parse_reasoning_output(trimmed)
                if parsed.get("type") != "unknown":
                    return validate_reasoning_output(parsed)
            return {"type": "response", "text": trimmed}
        parsed = parse_reasoning_output(raw)
        return validate_reasoning_output(parsed)

    def _error_from_exception(self, exc: Exception) -> dict:
        message = _scrub(str(exc), self.api_key)
        if openai is not None:
            if isinstance(exc, openai.AuthenticationError):
                logger.warning("[REASONER] NVIDIA authentication failed")
                return {"type": "error", "error": "authentication", "message": "Invalid NVIDIA API key", "provider": "nvidia"}
            if isinstance(exc, openai.RateLimitError):
                logger.warning("[REASONER] NVIDIA rate limit exceeded")
                return {"type": "error", "error": "rate_limit", "message": "NVIDIA rate limit exceeded", "provider": "nvidia"}
            if isinstance(exc, openai.APITimeoutError):
                logger.warning("[REASONER] NVIDIA request timed out")
                return {"type": "error", "error": "timeout", "message": "NVIDIA request timed out", "provider": "nvidia"}
            if isinstance(exc, openai.APIConnectionError):
                logger.warning("[REASONER] NVIDIA connection error: %s", message)
                return {"type": "error", "error": "connection", "message": "NVIDIA unreachable", "provider": "nvidia"}
            if isinstance(exc, openai.APIError):
                lowered = message.lower()
                if "insufficient" in lowered or "credit" in lowered or "quota" in lowered:
                    code = "insufficient_credits"
                elif "rate limit" in lowered:
                    code = "rate_limit"
                elif "internal" in lowered or "server" in lowered or "unavailable" in lowered:
                    code = "server_error"
                else:
                    code = "api_error"
                logger.warning("[REASONER] NVIDIA API error (%s): %s", code, message)
                return {"type": "error", "error": code, "message": message or "NVIDIA API error", "provider": "nvidia"}
        if isinstance(exc, TimeoutError):
            logger.warning("[REASONER] NVIDIA request timed out")
            return {"type": "error", "error": "timeout", "message": "NVIDIA request timed out", "provider": "nvidia"}
        logger.warning("[REASONER] NVIDIA request failed: %s", message)
        return {"type": "error", "error": "unknown", "message": message or "NVIDIA request failed", "provider": "nvidia"}

    # ── Capability probing (optional; never assumed) ────────────────────

    def probe_tool_support(self) -> bool:
        """Return True only if the model accepts a minimal tool payload.

        Cached per instance. Expensive (one tiny request) so it is *not* run
        unless a caller actually needs tool calls.
        """
        if self._supports_tools is not None:
            return self._supports_tools
        if self._client is None:
            self._supports_tools = False
            return False
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Say ok."}],
                max_tokens=4,
                temperature=0.0,
                stream=False,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "description": "echo a value",
                            "parameters": {
                                "type": "object",
                                "properties": {"x": {"type": "string"}},
                            },
                        },
                    }
                ],
                tool_choice="none",
                timeout=self.timeout,
            )
            self._supports_tools = True
        except Exception:
            self._supports_tools = False
        return self._supports_tools

    # Backwards-compatible private alias.
    _probe_tool_support = probe_tool_support

    def __repr__(self) -> str:  # never include the key
        state = "configured" if self._client is not None else "unconfigured"
        return f"<NVIDIAReasoner model={self.model} state={state}>"
