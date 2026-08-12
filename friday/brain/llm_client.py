"""
LLM "brain" client for Friday.

Talks to a local Ollama server (https://ollama.com) running on your own
machine. This is what makes "knowledge base trained on vast internet data,
free, unlimited" actually true rather than a marketing line: Ollama runs an
open-source language model entirely on your computer, so there's no API
bill, no rate limit, and no internet dependency once the model is
downloaded.

One-time setup (see README for full details):
    1. Install Ollama from https://ollama.com
    2. Run:  ollama pull llama3.2     (or any model you prefer)
    3. Leave the Ollama app/service running in the background.

If Ollama isn't running, Friday won't crash - she'll just fall back to
plain web-search answers (see friday/skills/knowledge_skill.py).
"""
import requests

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._available = None  # cached availability check

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            self._available = resp.status_code == 200
        except requests.RequestException:
            self._available = False
        return self._available

    def generate(self, prompt: str) -> str:
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=30,
            )
            resp.raise_for_status()
            self._available = True
            return resp.json().get("response", "").strip()
        except requests.RequestException as e:
            logger.warning("Ollama request failed: %s", e)
            self._available = False
            return ""
