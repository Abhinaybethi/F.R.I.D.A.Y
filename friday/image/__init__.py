"""
Qwen Image Generation Subsystem for F.R.I.D.A.Y.

Local text-to-image generation using the Qwen-Image GGUF model family served
through stable-diffusion.cpp (the ggml ecosystem companion to llama.cpp).

The subsystem is lazy by design: nothing loads or probes the inference runtime
or model files at assistant startup. The first ``generate_image`` tool call
initializes the manager, resolves/validates the model components, checks
resources, and reports structured results. When the runtime or model files are
missing the subsystem reports the exact missing dependency — it never
fabricates success.
"""
from friday.image.config import QwenImageConfig
from friday.image.manager import QwenImageManager
from friday.image.results import ImageGenResult, ImageServiceError

__all__ = [
    "QwenImageConfig",
    "QwenImageManager",
    "ImageGenResult",
    "ImageServiceError",
]