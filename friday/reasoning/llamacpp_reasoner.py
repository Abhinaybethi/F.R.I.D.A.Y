"""
llama.cpp / Bonsai local reasoner.

Connects to a locally running llama.cpp server via its
OpenAI-compatible /v1/chat/completions endpoint.
"""
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

    def request(self, transcript: str, context: ShortTermContext, mode: str = "action") -> dict:
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

        if mode == "chat":
            system_prompt = CHAT_PROMPT
            temperature = 0.4
            max_tokens = 512
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
        }

        try:
            logger.info("[REASONER] Sending request to llama.cpp (model=%s)", self.model)
            req = urllib.request.Request(
                self._chat_url(),
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status == 200:
                    result = json.loads(response.read().decode("utf-8"))
                    choices = result.get("choices", [])
                    if not choices:
                        logger.warning("[LLAMACPP] Empty choices in response")
                        return {"type": "unknown"}
                    raw_output = choices[0].get("message", {}).get("content", "")
                    if not raw_output:
                        logger.warning("[LLAMACPP] Empty content in response")
                        return {"type": "unknown"}

                    if mode == "chat":
                        stripped = raw_output.strip()
                        # If the model still returned JSON, handle it; otherwise
                        # treat everything as a natural-language response.
                        if stripped.startswith("{"):
                            parsed = parse_reasoning_output(stripped)
                            if parsed.get("type") != "unknown":
                                return validate_reasoning_output(parsed)
                        return {"type": "response", "text": stripped}

                    parsed = parse_reasoning_output(raw_output)
                    validated = validate_reasoning_output(parsed)
                    logger.info(
                        "[REASONER] Response received (type=%s)", validated.get("type")
                    )
                    return validated
                else:
                    logger.warning("[LLAMACPP] HTTP %s from %s", response.status, self._chat_url())
        except urllib.error.URLError as e:
            logger.warning("[LLAMACPP] Connection failed: %s", e)
        except TimeoutError:
            logger.warning("[LLAMACPP] Request timed out after %ss", self.timeout)
        except json.JSONDecodeError as e:
            logger.warning("[LLAMACPP] Invalid JSON in response: %s", e)
        except Exception as e:
            logger.warning("[LLAMACPP] Request failed: %s", e)

        return {"type": "unknown"}
