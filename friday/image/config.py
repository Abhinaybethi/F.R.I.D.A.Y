"""
Qwen Image Generation configuration.

Settings come from environment variables (``FRIDAY_*``), falling back to the
``image:`` block in ``config.yaml``, then to safe defaults. Nothing here
touches the inference runtime — this is pure resolution so tests stay fast.
"""
import os
from dataclasses import dataclass
from typing import Mapping, Optional

_ENV_ENABLED            = "FRIDAY_IMAGE_ENABLED"
_ENV_PROVIDER           = "FRIDAY_IMAGE_PROVIDER"
_ENV_MODEL              = "FRIDAY_QWEN_IMAGE_MODEL_PATH"
_ENV_TEXT_ENCODER       = "FRIDAY_QWEN_TEXT_ENCODER_PATH"
_ENV_VAE                = "FRIDAY_QWEN_VAE_PATH"
_ENV_EXECUTABLE         = "FRIDAY_QWEN_SD_EXECUTABLE"
_ENV_OUTPUT_DIR         = "FRIDAY_QWEN_OUTPUT_DIR"
_ENV_DEVICE             = "FRIDAY_QWEN_DEVICE"
_ENV_TEXT_ENCODER_DEVICE = "FRIDAY_QWEN_TEXT_ENCODER_DEVICE"
_ENV_KEEP_LOADED        = "FRIDAY_QWEN_KEEP_LOADED"
_ENV_FREE_VRAM          = "FRIDAY_QWEN_FREE_VRAM"
_ENV_PROMPT_ENHANCEMENT = "FRIDAY_QWEN_PROMPT_ENHANCEMENT"
_ENV_WIDTH              = "FRIDAY_QWEN_WIDTH"
_ENV_HEIGHT             = "FRIDAY_QWEN_HEIGHT"
_ENV_STEPS              = "FRIDAY_QWEN_STEPS"
_ENV_CFG_SCALE          = "FRIDAY_QWEN_CFG_SCALE"
_ENV_EXTRA_ARGS         = "FRIDAY_QWEN_EXTRA_ARGS"
_ENV_TIMEOUT            = "FRIDAY_QWEN_TIMEOUT"

DEFAULT_MODEL_BASE = "models/qwen-image"
DEFAULT_OUTPUT_DIR = "output/generated_images"


def _env_bool(env: Mapping, name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_int(env: Mapping, name: str, default: int, lo: int, hi: int) -> int:
    try:
        val = int((env.get(name) or "").strip() or default)
    except (ValueError, TypeError):
        return default
    return max(lo, min(hi, val))


def _env_float(env: Mapping, name: str, default: float, lo: float, hi: float) -> float:
    try:
        val = float((env.get(name) or "").strip() or default)
    except (ValueError, TypeError):
        return default
    return max(lo, min(hi, val))


@dataclass
class QwenImageConfig:
    """Resolved image subsystem settings (env > config.yaml > defaults)."""

    enabled: bool = True
    provider: str = "qwen-image"
    model_path: str = ""                 # diffusion GGUF file or discovery dir
    text_encoder_path: str = ""          # Qwen2.5-VL-7B GGUF / safetensors
    vae_path: str = ""                   # VAE safetensors / GGUF
    executable: str = "sd-cli"           # stable-diffusion.cpp CLI binary name
    output_dir: str = DEFAULT_OUTPUT_DIR
    device: str = "auto"                 # auto | cuda | cpu
    text_encoder_device: str = "auto"    # auto | cpu | gpu (sd-cli --backend llm=...)
    keep_loaded: bool = True
    prompt_enhancement: bool = False
    width: int = 768
    height: int = 768
    steps: int = 8
    cfg_scale: float = 2.5
    sampling_method: str = "euler"
    flow_shift: float = 3.0
    vae_tiling: bool = True
    diffusion_fa: bool = True
    offload_to_cpu: bool = True
    free_vram_before_generate: bool = True
    timeout: float = 900.0
    extra_args: str = ""      # extra tokens appended to the sd-cli command line

    @classmethod
    def from_mapping(
        cls,
        mapping: Optional[Mapping] = None,
        env: Optional[Mapping] = None,
    ) -> "QwenImageConfig":
        m = mapping if isinstance(mapping, Mapping) else {}
        e = env if isinstance(env, Mapping) else os.environ

        def pick(name: str, file_key: str, default):
            return e.get(name, m.get(file_key, default))

        raw_enabled = pick(_ENV_ENABLED, "enabled", True)
        if isinstance(raw_enabled, bool):
            enabled = raw_enabled
        elif isinstance(raw_enabled, str):
            enabled = raw_enabled.strip().lower() in ("1", "true", "yes", "on")
        else:
            enabled = bool(raw_enabled)

        provider = str(pick(_ENV_PROVIDER, "provider", "qwen-image")).strip()
        if not provider:
            provider = "qwen-image"

        steps = _env_int(e, _ENV_STEPS, int(m.get("steps", 8) or 8), 1, 50)
        width = _env_int(e, _ENV_WIDTH, int(m.get("width", 768) or 768), 64, 2048)
        height = _env_int(e, _ENV_HEIGHT, int(m.get("height", 768) or 768), 64, 2048)
        cfg_scale = _env_float(e, _ENV_CFG_SCALE, float(m.get("cfg_scale", 2.5) or 2.5), 1.0, 20.0)
        timeout = _env_float(e, _ENV_TIMEOUT, float(m.get("timeout", 900) or 900), 10.0, 3600.0)

        return cls(
            enabled=enabled,
            provider=provider,
            model_path=str(pick(_ENV_MODEL, "model_path", "") or "").strip(),
            text_encoder_path=str(pick(_ENV_TEXT_ENCODER, "text_encoder_path", "") or "").strip(),
            vae_path=str(pick(_ENV_VAE, "vae_path", "") or "").strip(),
            executable=str(pick(_ENV_EXECUTABLE, "executable", "sd-cli") or "sd-cli").strip(),
            output_dir=str(pick(_ENV_OUTPUT_DIR, "output_dir", DEFAULT_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR).strip(),
            device=str(pick(_ENV_DEVICE, "device", "auto") or "auto").strip().lower(),
            text_encoder_device=str(
                pick(_ENV_TEXT_ENCODER_DEVICE, "text_encoder_device", "auto") or "auto"
            ).strip().lower(),
            keep_loaded=_env_bool(e, _ENV_KEEP_LOADED, bool(m.get("keep_loaded", True))),
            prompt_enhancement=_env_bool(
                e, _ENV_PROMPT_ENHANCEMENT, bool(m.get("prompt_enhancement", False))
            ),
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            sampling_method=str(m.get("sampling_method", "euler") or "euler").strip(),
            flow_shift=float(m.get("flow_shift", 3.0) or 3.0),
            vae_tiling=bool(m.get("vae_tiling", True)),
            diffusion_fa=bool(m.get("diffusion_fa", True)),
            offload_to_cpu=bool(m.get("offload_to_cpu", True)),
            free_vram_before_generate=_env_bool(
                e, _ENV_FREE_VRAM, bool(m.get("free_vram_before_generate", True))
            ),
            timeout=timeout,
            extra_args=str(e.get(_ENV_EXTRA_ARGS, m.get("extra_args", "") or "") or "").strip(),
        )

    @classmethod
    def load(cls, config_file: str = "config.yaml") -> "QwenImageConfig":
        """Load image config from environment + optional config.yaml ``image:`` block."""
        image_block: dict = {}
        try:
            import yaml

            with open(config_file, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            image_block = raw.get("image", {}) or {}
        except Exception:
            image_block = {}
        return cls.from_mapping(image_block)