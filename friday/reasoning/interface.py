"""
Base interface for the reasoning layer.
"""
from abc import ABC, abstractmethod
from typing import Optional
from friday.planning.context_resolver import ShortTermContext

class Reasoner(ABC):
    @abstractmethod
    def request(self, transcript: str, context: ShortTermContext, mode: str = "action",
                retrieval_context: str = "") -> dict:
        """
        Processes a transcript and short-term context.

        Args:
            transcript: Clean command / user message (no wake phrase).
            context:    ShortTermContext from the running conversation.
            mode:       "action" -> structured intent/plan JSON
                        "chat"   -> natural language response (QUESTION/CHAT)
            retrieval_context: Optional RAG context block (chat mode only).
        Returns a validated, structured JSON dictionary.
        """
        pass
        
    @abstractmethod
    def is_available(self) -> bool:
        """
        Checks if the reasoning model is available and reachable.
        """
        pass
        
    @abstractmethod
    def health(self) -> str:
        """
        Returns a health string.
        """
        pass
        
    @abstractmethod
    def close(self):
        """
        Cleans up resources.
        """
        pass
