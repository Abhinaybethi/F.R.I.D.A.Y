"""
llama.cpp / Bonsai local reasoner.

Connects to a locally running llama.cpp server via its
OpenAI-compatible /v1/chat/completions endpoint.

Streams SSE tokens so the first patch of text arrives as soon as it is
generated (first-token latency), enforces a hard per-request deadline, and
records usage + timings for the [LLM] performance log (P2/P3/P14).
"""
import time
import urllib.request
import urllib.error
import json

from friday.reasoning.interface import Reasoner
from friday.reasoning.prompt import SYSTEM_PROMPT
from friday.reasoning.chat_prompt import CHAT_PROMPT
from friday.reasoning.parser import parse_reasoning_output
from friday.reasoning.validator import validate_reasoning_output
from friday.planning.context_resolver import ShortTermContext
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def _extract_text_from_choice(choice) -> str:
    """Return the first non-empty text field from a chat-completion choice.

    Handles ``message.content`` (absent or explicitly ``null`` on thinking
    models), ``message.reasoning_content`` (deepseek/Qwen-style reasoning
    traces), and the SSE ``delta`` equivalents for the same two keys.
    Never returns ``None`` — empty output stays a plain string so callers
    can distinguish "no content yet" from a parse failure.
    """
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message") or {}
    delta = choice.get("delta") or {}
    for block in (message, delta):
        for key in ("content", "reasoning_content"):
            val = block.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


class LlamaCppReasoner(Reasoner):
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "C:\\AI\\models\\Bonsai-8B-Q1_0.gguf",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _health_url(self) -> str:
        return f"{self.base_url}/health"

    def _chat_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(self._health_url(), method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as response:
                if response.status == 200:
                    body = json.loads(response.read().decode("utf-8"))
                    return body.get("status") == "ok"
                return False
        except Exception:
            return False

    def health(self) -> str:
        if self.is_available():
            return f"llama.cpp reachable ({self.model})"
        return "llama.cpp unreachable"

    def close(self):
        pass

    def request(self, transcript: str, context: ShortTermContext, mode: str = "action",
                retrieval_context: str = "") -> dict:
        if not self.is_available():
            return {"type": "unknown"}

        context_str = ""
        if context.last_search_query:
            context_str += f"- Last search query: '{context.last_search_query}'\n"
        if context.last_action:
            context_str += f"- Last action: {context.last_action.name}\n"
        if context.last_transcript:
            context_str += f"- Last transcript: '{context.last_transcript}'\n"

        user_content = f"Transcript: {transcript}\n\n"
        if context_str:
            user_content += f"Context:\n{context_str}\n"
        if mode == "chat" and retrieval_context:
            user_content += f"\n{retrieval_context}\n"

        if mode == "chat":
            system_prompt = CHAT_PROMPT
            temperature = 0.4
            max_tokens = 256
            logger.info("[REASONER] Mode=CHAT (natural language response)")
        else:
            system_prompt = SYSTEM_PROMPT
            temperature = 0.0
            max_tokens = 128
            logger.info("[REASONER] Mode=ACTION (structured intent/plan)")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        # Hard per-request budget cap. ACTION mode never gets more than 20s;
        # chat gets at most the configured timeout (P14).
        effective_timeout = self.timeout
        if mode != "chat":
            effective_timeout = min(self.timeout, 20.0)
        deadline = time.monotonic() + max(effective_timeout, 1.0)

        t_start = time.monotonic()
        try:
            logger.info("[REASONER] Sending request to llama.cpp (model=%s)", self.model)
            req = urllib.request.Request(
                self._chat_url(),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    logger.warning("[LLAMACPP] HTTP %s from %s", response.status, self._chat_url())
                    return {"type": "unknown"}

                raw, prompt_tokens, completion_tokens, ttft_ms, gen_ms, streamed, deadline_hit, finish_reason = (
                    self._read_payload(response, deadline)
                )
                total_ms = (time.monotonic() - t_start) * 1000.0

                if not raw or not raw.strip():
                    logger.warning(
                        "[LLAMACPP] Empty content after %s parse (finish_reason=%s stream_done=%s)",
                        "SSE" if streamed else "bulk",
                        finish_reason or "-", not deadline_hit,
                    )
                    return {"type": "unknown"}

                tokens_per_sec = 0.0
                if streamed and completion_tokens > 0 and gen_ms > 0:
                    tokens_per_sec = completion_tokens / (gen_ms / 1000.0)
                logger.info(
                    "[LLM] mode=%s stream=%s prompt_tokens=%s completion_tokens=%s "
                    "ttft_ms=%.0f generation_ms=%.0f tokens_per_sec=%.1f total_ms=%.0f",
                    mode, "yes" if streamed else "no", prompt_tokens, completion_tokens,
                    ttft_ms, gen_ms, tokens_per_sec, total_ms,
                )
                if deadline_hit:
                    logger.warning(
                        "[LLM] deadline reached after %.0fms — used partial output", total_ms
                    )

                if mode == "chat":
                    stripped = raw.strip()
                    if stripped.startswith("{"):
                        parsed = parse_reasoning_output(stripped)
                        if parsed.get("type") != "unknown":
                            return validate_reasoning_output(parsed)
                    return {"type": "response", "text": stripped}

                parsed = parse_reasoning_output(raw)
                validated = validate_reasoning_output(parsed)
                logger.info(
                    "[REASONER] Response received (type=%s)", validated.get("type")
                )
                return validated
        except urllib.error.URLError as e:
            logger.warning("[LLAMACPP] Connection failed: %s", e)
        except TimeoutError:
            logger.warning("[LLAMACPP] Request timed out after %ss", self.timeout)
        except json.JSONDecodeError as e:
            logger.warning("[LLAMACPP] Invalid JSON in response: %s", e)
        except Exception as e:
            logger.warning("[LLAMACPP] Request failed: %s", e)

        return {"type": "unknown"}

    def _read_payload(self, response, deadline: float):
        """
        Read the response body, preferring SSE streaming.

        Returns ``(text, prompt_tokens, completion_tokens, ttft_ms, gen_ms,
        streamed, deadline_hit, finish_reason)``. Falls back to a single bulk
        ``.read()`` when the response is not SSE (older servers) or when the
        transport object does not expose ``readline()`` (unit-test mocks).
        """
        try:
            first = response.readline()
        except Exception:
            first = None

        if not isinstance(first, (str, bytes)):
            # Bulk fallback for mocks / non-SSE bodies.
            try:
                body = response.read()
            except Exception:
                body = b""
            if isinstance(body, str):
                body = body.encode("utf-8", "replace")
            if not body:
                return "", 0, 0, -1.0, -1.0, False, False, ""
            try:
                result = json.loads(body.decode("utf-8", "replace"))
                choices = result.get("choices", [])
                text = ""
                finish_reason = ""
                if choices:
                    text = _extract_text_from_choice(choices[0])
                    finish_reason = choices[0].get("finish_reason") or ""
                usage = result.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", max(1, len(text) // 4))
                return text, prompt_tokens, completion_tokens, -1.0, -1.0, False, False, finish_reason
            except Exception:
                return "", 0, 0, -1.0, -1.0, False, False, ""

        # SSE streaming.
        start = time.monotonic()
        text_parts = []
        prompt_tokens = 0
        completion_tokens = 0
        ttft_ms = -1.0
        gen_ms = -1.0
        saw_data = False
        deadline_hit = False
        finish_reason = ""
        pending = [first]

        while True:
            if time.monotonic() >= deadline:
                deadline_hit = True
                break
            if not pending:
                try:
                    line_bytes = response.readline()
                except Exception:
                    break
                if not line_bytes:
                    break
                pending.append(line_bytes)
                continue
            line = pending.pop(0)
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            elif not isinstance(line, str):
                continue
            stripped = line.strip()
            if not stripped or not stripped.startswith("data:"):
                continue
            data = stripped[len("data:"):].strip()
            if data == "[DONE]":
                break
            saw_data = True
            try:
                obj = json.loads(data)
            except Exception:
                continue
            # content may be absent or explicitly null on thinking models;
            # fall back to reasoning_content, then to a full message block.
            piece = ""
            try:
                choice = obj["choices"][0]
            except Exception:
                choice = None
            if choice is not None:
                piece = _extract_text_from_choice(choice)
                chunk_finish = choice.get("finish_reason")
                if chunk_finish:
                    finish_reason = chunk_finish
            if piece:
                if ttft_ms < 0.0:
                    ttft_ms = (time.monotonic() - start) * 1000.0
                text_parts.append(piece)
                gen_ms = (time.monotonic() - start) * 1000.0
            usage = obj.get("usage") or {}
            if usage.get("prompt_tokens") is not None:
                prompt_tokens = usage["prompt_tokens"]
            if usage.get("completion_tokens") is not None:
                completion_tokens = usage["completion_tokens"]

        text = "".join(text_parts)
        if not saw_data and not text:
            # Server ignored the stream flag and returned a plain JSON body.
            try:
                body = response.read()
                if isinstance(body, str):
                    body = body.encode("utf-8", "replace")
                if body:
                    result = json.loads(body.decode("utf-8", "replace"))
                    choices = result.get("choices", [])
                    if choices:
                        text = _extract_text_from_choice(choices[0])
                        finish_reason = choices[0].get("finish_reason") or finish_reason
            except Exception:
                pass

        if completion_tokens == 0:
            completion_tokens = max(1, len(text) // 4)
        return text, prompt_tokens, completion_tokens, ttft_ms, gen_ms, True, deadline_hit, finish_reason