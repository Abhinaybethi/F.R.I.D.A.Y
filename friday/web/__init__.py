"""Read-only HTTP/WebSocket dashboard for F.R.I.D.A.Y.

The web layer is a thin adapter over the existing assistant, reasoning, tool,
research, RAG, and image-generation services. It never fabricates state: every
metric, health flag, model, task, and activity entry originates from a real
measurement or a recorded operation.
"""
from friday.web.app import create_app

__all__ = ["create_app"]
