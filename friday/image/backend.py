"""
stable-diffusion.cpp inference adapter for Qwen-Image-2.1 GGUF.

Qwen-Image-2.1 is available as GGUF quantized diffusion weights
(``leejet/Qwen-Image-2.1-GGUF``), which llama.cpp's text server cannot load.
The supported headless runtime is stable-diffusion.cpp (``sd-cli``), whose
Qwen-Image-2.1 mode takes the diffusion GGUF, the 2.1 VAE, and the
Qwen3-VL-8B-Instruct text encoder GGUF (see stable-diffusion.cpp
``docs/qwen_image_2.1.md``).

This module only *builds and drives* the subprocess. It never imports torch or
Pillow at module scope, so unit tests remain fast and dependency-light.
"""
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from friday.image.config import DEFAULT_MODEL_BASE, QwenImageConfig
from friday.image.results import (
    ERROR_COMPONENT_MISSING,
    ERROR_DEVICE_UNAVAILABLE,
    ERROR_EXECUTABLE_MISSING,
    ERROR_GENERATION_FAILED,
    ERROR_INVALID_CONFIG,
    ERROR_MODEL_MISSING,
    ERROR_TIMEOUT,
    ImageServiceError,
)
from friday.utils.logger import get_logger

logger = get_logger(__name__)

# Qwen-Image-2.1 stages its ~4.3 GB text encoder (Qwen3-VL-8B) onto the compute
# GPU. On GPUs below this many MiB the encoder plus its compute workspace no
# longer fits, so sd-cli aborts with a "workspace capacity check" error. Below
# the threshold the encoder is placed on CPU while diffusion/VAE stay on GPU.
_GPU_TEXT_ENCODER_MIN_VRAM_MB = 10240

# sd-cli writes its "[E] ..." failure lines to stderr; keep every error line
# plus a rolling tail so the actionable root cause is never truncated away.
_DIAGNOSTIC_TAIL_LINES = 40
_DIAGNOSTIC_MAX_LINES = 60

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_PROGRESS_RE = re.compile(r"\|[#=.>\s]*\|(?!\w)|\d+\s*/\s*\d+|\d+\.\d+\s*(?:it/s|s/it)|MB/s")


def _is_progress_line(line: str) -> bool:
    return bool(_PROGRESS_RE.search(_ANSI_RE.sub("", line)))


def _as_path(name: str) -> Path:
    return Path(name).expanduser() if name else Path()


def _diagnostic_tail(stdout: object, stderr: object, max_lines: int = _DIAGNOSTIC_TAIL_LINES) -> List[str]:
    """Combine sd-cli's stderr/stdout into a diagnostic tail.

    All ``[E]`` error lines are retained ahead of the last ``max_lines`` lines,
    deduplicated in order, so the failing operation survives truncation.
    """
    def _text(value: object) -> str:
        if not value:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value)

    combined = "\n".join(part for part in (_text(stderr), _text(stdout)) if part.strip())
    lines = [_ANSI_RE.sub("", line).rstrip() for line in combined.splitlines() if line.strip()]
    errors = [line for line in lines if "[E]" in line]
    tail = [line for line in lines if not _is_progress_line(line)][-max_lines:]
    seen, out = set(), []
    for line in errors + tail:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out[:_DIAGNOSTIC_MAX_LINES]


def text_encoder_backend(
    config: QwenImageConfig,
    device_info: Dict[str, object],
    extra_args: str = "",
) -> str:
    """Return the sd-cli ``--backend`` value that keeps the text encoder off a
    small/shared GPU, or ``""`` to let sd-cli's auto-fit choose placement.

    ``text_encoder_device`` semantics: ``cpu`` forces ``llm=cpu``, ``gpu``
    forces auto-fit, and ``auto`` picks ``llm=cpu`` when the resolved device is
    CUDA with less than ``_GPU_TEXT_ENCODER_MIN_VRAM_MB`` of VRAM. An explicit
    ``--backend`` in ``extra_args`` always wins and disables this heuristic.
    """
    if "--backend" in shlex.split(extra_args or ""):
        return ""
    mode = str(getattr(config, "text_encoder_device", "auto") or "auto").strip().lower()
    if mode == "cpu":
        return "llm=cpu"
    if mode == "gpu":
        return ""
    device = str(device_info.get("device") or "").lower()
    vram = device_info.get("vram_total_mb")
    if device == "cuda" and isinstance(vram, int) and vram < _GPU_TEXT_ENCODER_MIN_VRAM_MB:
        return "llm=cpu"
    return ""


def resolve_executable(config: QwenImageConfig) -> Optional[str]:
    """Resolve the sd.cpp CLI binary (explicit path, PATH, or project models/bin)."""
    exe = config.executable.strip()
    if not exe:
        return None

    if os.path.sep in exe or (os.path.altsep and os.path.altsep in exe):
        cand = _as_path(exe)
        if os.access(cand, os.X_OK):
            return str(cand)
        # allow Windows-style paths without extension resolution oddities
        if os.path.exists(str(cand) + ".exe"):
            return str(cand) + ".exe"
        return None

    found = shutil.which(exe)
    if found:
        return found

    local_bin = Path(DEFAULT_MODEL_BASE).parent / "bin"
    for cand in (local_bin / exe, Path("bin") / exe):
        for path in (cand, Path(str(cand) + ".exe")):
            if os.access(path, os.X_OK):
                return str(path)
    return None


def _first_file(folder: Path, patterns: Tuple[str, ...], prefer: Optional[str] = None) -> Optional[str]:
    candidates = []
    for pat in patterns:
        candidates.extend(sorted(folder.glob(pat)))
    if not candidates:
        return None
    if prefer:
        for cand in candidates:
            if cand.suffix.lower() == prefer.lower():
                return str(cand)
    return str(candidates[0])


def resolve_components(config: QwenImageConfig) -> Dict[str, str]:
    """
    Resolve the three model components: explicit configured paths are honored,
    otherwise a canonical ``models/qwen-image/{diffusion,text_encoder,vae}``
    layout is discovered. Returns {model, text_encoder, vae}. Raises a
    structured ImageServiceError naming exactly what is missing.
    """
    base = Path(DEFAULT_MODEL_BASE)

    def pick(explicit: str, folder: str, patterns: Tuple[str, ...], prefer: Optional[str]) -> str:
        if explicit:
            p = _as_path(explicit)
            if p.is_file():
                return str(p)
            if p.is_dir():
                found = _first_file(p, patterns, prefer)
                if found:
                    return found
            raise ImageServiceError(
                ERROR_MODEL_MISSING,
                f"Qwen image model component not found at configured path: {explicit}",
                {"path": explicit},
            )
        found = _first_file(base / folder, patterns, prefer)
        if found:
            return found
        raise ImageServiceError(
            ERROR_COMPONENT_MISSING,
            f"Qwen image component '{folder}' is missing. "
            f"Place a model file in models/qwen-image/{folder}/ or set "
            f"FRIDAY_QWEN_{folder.upper().replace('-', '_')}_PATH.",
            {"folder": folder, "expected_dir": str(base / folder)},
        )

    model = pick(config.model_path, "diffusion", ("*.gguf",), None)
    text_encoder = pick(
        config.text_encoder_path,
        "text_encoder",
        ("*.gguf", "*.safetensors"),
        ".gguf",
    )
    vae = pick(config.vae_path, "vae", ("*.safetensors", "*.gguf"), ".safetensors")

    return {"model": model, "text_encoder": text_encoder, "vae": vae}


def detect_device(config: QwenImageConfig) -> Dict[str, object]:
    """
    Resolve the inference device. ``auto`` picks CUDA when an NVIDIA GPU is
    present (nvidia-smi), otherwise CPU with an honest slow-path warning.
    An explicit ``cuda`` with no usable GPU raises instead of silently
    degrading. Also returns GPU name and total VRAM (MiB) when known.
    """
    requested = (config.device or "auto").strip().lower()

    gpu_name: Optional[str] = None
    vram_total_mb: Optional[int] = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            line = out.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            gpu_name = parts[0] or None
            if len(parts) > 1:
                try:
                    vram_total_mb = int(parts[1])
                except ValueError:
                    vram_total_mb = None
    except (OSError, subprocess.SubprocessError):
        pass

    cuda_available = bool(gpu_name)

    if requested == "cuda":
        if not cuda_available:
            raise ImageServiceError(
                ERROR_DEVICE_UNAVAILABLE,
                "FRIDAY_QWEN_DEVICE='cuda' but no NVIDIA GPU was detected. "
                "Set FRIDAY_QWEN_DEVICE=auto (or cpu) to run on CPU.",
                {"requested": requested},
            )
        device = "cuda"
    elif requested == "cpu":
        device = "cpu"
        if cuda_available:
            logger.info("[IMAGE] device=cpu forced by config (GPU %s present)", gpu_name)
    else:  # auto
        device = "cuda" if cuda_available else "cpu"
        if not cuda_available:
            logger.warning(
                "[IMAGE] Qwen image device: CPU (no NVIDIA GPU detected). "
                "Image generation will be slow."
            )
        else:
            logger.info("[IMAGE] Qwen image device: CUDA (%s, %s MiB)", gpu_name, vram_total_mb)

    if device == "cuda" and vram_total_mb is not None and vram_total_mb < 6144:
        logger.warning(
            "[IMAGE] GPU has only %d MiB VRAM. Use a small quantization "
            "(Q4_K_M class) and keep --offload-to-cpu enabled, or generation "
            "may fail or be very slow.", vram_total_mb,
        )

    return {
        "device": device,
        "gpu_name": gpu_name,
        "vram_total_mb": vram_total_mb,
    }


def gpu_memory_mb() -> Optional[Tuple[int, int]]:
    """Return ``(used_mb, free_mb)`` for GPU 0 via nvidia-smi, or None."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
            return int(parts[0]), int(parts[1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return None


def gpu_compute_process_names() -> List[str]:
    """Best-effort names of processes holding GPU memory (nvidia-smi excluded)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=process_name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return []
        names: List[str] = []
        for line in out.stdout.splitlines():
            name = line.strip()
            if not name:
                continue
            base = Path(name).name
            if base.lower().startswith("nvidia-smi") or base in names:
                continue
            names.append(base)
        return names
    except (OSError, subprocess.SubprocessError):
        return []


def probe_executable(exe: str, timeout: int = 15) -> Tuple[bool, str]:
    """Probe a sd.cpp binary via ``--help``. (ok, snippet)."""
    try:
        out = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=timeout)
        text = (out.stdout or out.stderr or "").strip()
        return out.returncode == 0, text[:200]
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


@dataclass
class BuildParams:
    prompt: str
    width: int = 1024
    height: int = 1024
    steps: int = 20
    seed: int = -1
    cfg_scale: float = 2.5
    sampling_method: str = "euler"
    flow_shift: float = 3.0
    vae_tiling: bool = True
    diffusion_fa: bool = True
    offload_to_cpu: bool = True
    verbose: bool = False


def build_command(
    exe: str,
    components: Dict[str, str],
    params: BuildParams,
    output_path: str,
    extra_args: str = "",
    backend: str = "",
) -> List[str]:
    """Build the sd-cli argv for a Qwen-Image-2.1 GGUF txt2img run.

    ``backend`` is an optional sd-cli ``--backend`` placement string emitted
    before ``extra_args`` (which stay last so callers can still override).
    """
    cmd = [
        exe,
        "--diffusion-model", components["model"],
        "--vae", components["vae"],
        "--llm", components["text_encoder"],
        "-p", params.prompt,
        "-W", str(params.width),
        "-H", str(params.height),
        "--steps", str(params.steps),
        "--cfg-scale", f"{params.cfg_scale:.2f}",
        "--sampling-method", params.sampling_method,
        "--flow-shift", f"{params.flow_shift:.2f}",
        "-o", output_path,
    ]
    if params.seed >= 0:
        cmd += ["--seed", str(params.seed)]
    if params.vae_tiling:
        cmd.append("--vae-tiling")
    if params.diffusion_fa:
        cmd.append("--diffusion-fa")
    if params.offload_to_cpu:
        cmd.append("--offload-to-cpu")
    if params.verbose:
        cmd.append("-v")
    if backend:
        cmd += ["--backend", backend]
    if extra_args and extra_args.strip():
        cmd += shlex.split(extra_args)
    return cmd


class StableDiffusionCppBackend:
    """Drives the sd-cli subprocess. One process per generation (CLI mode)."""

    backend_name = "stable-diffusion.cpp (sd-cli)"

    def __init__(self, config: QwenImageConfig, executable: Optional[str] = None):
        self.config = config
        self.executable = executable or resolve_executable(config)
        self._device_info: Optional[Dict[str, object]] = None

    # ------------------------------------------------------------------
    def resolve_components(self) -> Dict[str, str]:
        """Model components for this backend's config (explicit or discovered)."""
        return resolve_components(self.config)

    # ------------------------------------------------------------------
    def ensure_executable(self) -> str:
        if not self.executable:
            raise ImageServiceError(
                ERROR_EXECUTABLE_MISSING,
                "stable-diffusion.cpp (sd-cli) is not installed or not on PATH. "
                "Install it and set FRIDAY_QWEN_SD_EXECUTABLE if needed.",
                {"backend": self.backend_name},
            )
        return self.executable

    def device_info(self) -> Dict[str, object]:
        if self._device_info is None:
            self._device_info = detect_device(self.config)
        return self._device_info

    def generate(self, params: BuildParams, output_path: str, request_id: str = "") -> Dict[str, object]:
        """Run one sd-cli generation into `output_path`; raise on failure."""
        exe = self.ensure_executable()
        components = resolve_components(self.config)
        device_info = self.device_info()
        device = device_info["device"]

        backend = text_encoder_backend(self.config, device_info, self.config.extra_args)
        if backend:
            logger.info(
                "[IMAGE] text encoder placed on CPU (--backend %s) to fit GPU VRAM=%s MiB",
                backend, device_info.get("vram_total_mb"),
            )

        logger.info(
            "[IMAGE] name=qwen-image action=GENERATE device=%s model=%r prompt_len=%d out=%s",
            device, Path(components["model"]).name, len(params.prompt), output_path,
        )

        cmd = build_command(
            exe, components, params, output_path,
            extra_args=self.config.extra_args, backend=backend,
        )
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError:
            raise ImageServiceError(
                ERROR_EXECUTABLE_MISSING,
                f"Runtime executable not found: {exe}",
                {"executable": exe},
            ) from None
        except subprocess.TimeoutExpired as e:
            tail = _diagnostic_tail(getattr(e, "stdout", None), getattr(e, "stderr", None))
            raise ImageServiceError(
                ERROR_TIMEOUT,
                f"Image generation timed out after {self.config.timeout:.0f}s.",
                {
                    "tail": tail,
                    "command": cmd,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                },
            ) from None

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if proc.returncode != 0:
            tail = _diagnostic_tail(proc.stdout, proc.stderr)
            logger.error(
                "[IMAGE] name=qwen-image action=GENERATE_FAILED returncode=%d device=%s "
                "elapsed_ms=%.1f diagnostics=%s",
                proc.returncode, device, elapsed_ms, " | ".join(tail[-6:]) or "(no output)",
            )
            raise ImageServiceError(
                ERROR_GENERATION_FAILED,
                "Image generation process failed.",
                {
                    "returncode": proc.returncode,
                    "tail": tail,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "command": cmd,
                },
            )

        logger.info(
            "[IMAGE] name=qwen-image action=GENERATED elapsed_ms=%.1f out=%s",
            elapsed_ms, output_path,
        )

        return {
            "returncode": proc.returncode,
            "elapsed_ms": elapsed_ms,
            "device": device,
            "gpu_name": self._device_info.get("gpu_name") if self._device_info else None,
        }