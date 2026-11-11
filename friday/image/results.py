"""
Structured results and errors for the image generation subsystem.

User-facing surfaces never receive raw tracebacks. Every failure is captured
as an ``ImageServiceError`` (an ``error_type`` machine tag + a clean message)
and every generation as an ``ImageGenResult`` containing the output metadata.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional

# Machine-readable error kinds. Message text stays human friendly.
ERROR_NOT_CONFIGURED      = "not_configured"
ERROR_EXECUTABLE_MISSING  = "executable_not_found"
ERROR_MODEL_MISSING       = "model_not_found"
ERROR_COMPONENT_MISSING   = "component_missing"
ERROR_INVALID_CONFIG      = "invalid_config"
ERROR_INVALID_PROMPT      = "invalid_prompt"
ERROR_INSUFFICIENT_VRAM   = "insufficient_vram"
ERROR_DEVICE_UNAVAILABLE  = "device_unavailable"
ERROR_OUTPUT_DIR          = "output_dir_failed"
ERROR_GENERATION_FAILED   = "generation_failed"
ERROR_RUNTIME_FAILED      = "runtime_failed"
ERROR_TIMEOUT             = "timeout"

_PROGRESS_PHRASES = {
    "start": "Generating the image now.",
    "done": "Done. I've generated the image.",
    "failure": "I couldn't generate that image.",
}


class ImageServiceError(Exception):
    """Structured, never raw-traced image generation error."""

    def __init__(self, error_type: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {
            "success": False,
            "message": self.message,
            "error_type": self.error_type,
            "error_code": self.error_type,
            **self.details,
        }


@dataclass
class ImageGenResult:
    """Outcome of one image generation request."""

    success: bool
    message: str
    path: str = ""
    filename: str = ""
    prompt: str = ""
    width: int = 0
    height: int = 0
    steps: int = 0
    seed: Optional[int] = None
    provider: str = "qwen-image"
    backend: str = "stable-diffusion.cpp (sd-cli)"
    device: str = "cpu"
    request_id: str = ""
    elapsed_ms: float = 0.0
    error_type: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "path": self.path,
            "filename": self.filename,
            "prompt": self.prompt,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "seed": self.seed,
            "provider": self.provider,
            "backend": self.backend,
            "device": self.device,
            "request_id": self.request_id,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "error_type": self.error_type,
            "detail": self.detail,
        }

    def spoken_message(self) -> str:
        if self.success:
            return _PROGRESS_PHRASES["done"]
        return _PROGRESS_PHRASES["failure"]

    def metadata_payload(self) -> dict:
        """Full self-describing metadata written to the sidecar .json file."""
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "backend": self.backend,
            "device": self.device,
            "prompt": self.prompt,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "seed": self.seed,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "error_type": self.error_type,
        }