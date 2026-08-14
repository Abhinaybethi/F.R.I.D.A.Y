"""
Ollama-based local reasoner.
"""
import urllib.request
import urllib.error
import json
from typing import Optional

from friday.reasoning.interface import Reasoner
from friday.reasoning.prompt import SYSTEM_PROMPT
from friday.reasoning.parser import parse_reasoning_output
from friday.reasoning.validator import validate_reasoning_output
from friday.planning.context_resolver import ShortTermContext
from friday.utils.logger import get_logger

logger = get_logger(__name__)

class OllamaReasoner(Reasoner):
    def __init__(self, endpoint: str = "http://localhost:11434/api/generate", model: str = "llama3:latest"):
        self.endpoint = endpoint
        self.model = model
        
    def is_available(self) -> bool:
        try:
            req = urllib.request.Request("http://localhost:11434/", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as response:
                return response.status == 200
        except Exception:
            return False
            
    def health(self) -> str:
        if self.is_available():
            return f"Ollama reachable ({self.model})"
        return "Ollama unreachable"
        
    def close(self):
        pass
        
    def request(self, transcript: str, context: ShortTermContext) -> dict:
        if not self.is_available():
            return {"type": "unknown"}
            
        context_str = ""
        if context.last_search_query:
            context_str += f"- Last search query: '{context.last_search_query}'\n"
        if context.last_action:
            context_str += f"- Last action: {context.last_action.name}\n"
        if context.last_transcript:
            context_str += f"- Last transcript: '{context.last_transcript}'\n"
            
        user_prompt = f"Transcript: {transcript}\n\n"
        if context_str:
            user_prompt += f"Context:\n{context_str}\n"
            
        payload = {
            "model": self.model,
            "prompt": user_prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.0
            }
        }
        
        try:
            req = urllib.request.Request(
                self.endpoint, 
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60.0) as response:
                if response.status == 200:
                    result = json.loads(response.read().decode('utf-8'))
                    raw_output = result.get("response", "")
                    
                    parsed = parse_reasoning_output(raw_output)
                    validated = validate_reasoning_output(parsed)
                    return validated
        except Exception as e:
            logger.warning("[REASONER] Request failed: %s", e)
            
        return {"type": "unknown"}
