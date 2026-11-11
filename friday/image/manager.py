"""
QwenImageManager — lazy model lifecycle + generation facade.

The manager is intentionally lazy: constructing it never probes the runtime or
model files (nothing loads at assistant startup). The first ``generate()``
call performs load (executable + components + device + resources), runs one
generation through the backend, validates the produced PNG, and writes a
metadata sidecar.

CLI-mode note (honest reporting): with the default ``sd-cli`` backend, the
model is resident only inside each one-shot subprocess. ``_model_loaded``
therefore means "preflighted and ready to run a generation", which is exactly
what ``health()['loaded']`` reports. ``keep_loaded`` governs whether the
preflight state is retained between requests.
"""
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from friday.image.backend import (
    BuildParams,
    StableDiffusionCppBackend,
    gpu_compute_process_names,
    gpu_memory_mb,
)
from friday.image.config import QwenImageConfig
from friday.image.gpu_hooks import release_gpu_memory, restore_gpu_memory
from friday.image.output import (
    allocate_output_path,
    cleanup_if_failed,
    is_valid_png,
    write_metadata,
)
from friday.image.results import (
    ERROR_GENERATION_FAILED,
    ERROR_INVALID_PROMPT,
    ERROR_OUTPUT_DIR,
    ImageGenResult,
    ImageServiceError,
)
from friday.utils.logger import get_logger, request_id_var

logger = get_logger(__name__)

STATE_UNLOADED = "unloaded"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_GENERATING = "generating"
STATE_ERROR = "error"

# Below this much free VRAM the ~4 GB diffusion model cannot stay GPU-resident
# and sd-cli streams it from system RAM each step, roughly doubling the time.
_LOW_VRAM_MB = 5000


def _default_request_id() -> str:
    rid = request_id_var.get()
    if rid and rid != "-":
        return rid
    return uuid.uuid4().hex[:8]


class QwenImageManager:
    def __init__(
        self,
        config: Optional[QwenImageConfig] = None,
        backend: Optional[StableDiffusionCppBackend] = None,
        output_dir: Optional[str] = None,
        now: Optional[datetime] = None,
    ):
        self.config = config or QwenImageConfig.load()
        self.output_dir = Path(output_dir or self.config.output_dir).expanduser()
        self._now = now
        self.backend = backend or StableDiffusionCppBackend(self.config)
        self.state = STATE_UNLOADED
        self.last_error: Optional[ImageServiceError] = None

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------
    def load(self) -> bool:
        """Validate executable + model components + device/VRAM. No model is
        permanently resident in CLI mode; this marks the manager ready to run
        a generation. Idempotent; returns True when ready."""
        if self.state == STATE_READY:
            return True

        self.state = STATE_LOADING
        logger.info("[IMAGE] name=qwen-image action=MODEL_LOADING backend=%s", self.backend.backend_name)
        try:
            self.backend.ensure_executable()
            self.backend.resolve_components()
            info = self.backend.device_info()
            logger.info(
                "[IMAGE] name=qwen-image action=MODEL_LOADED device=%s gpu=%s vram_mb=%s",
                info["device"], info.get("gpu_name"), info.get("vram_total_mb"),
            )
            self.state = STATE_READY
            self.last_error = None
            return True
        except ImageServiceError as e:
            self.state = STATE_ERROR
            self.last_error = e
            logger.error("[IMAGE] name=qwen-image action=MODEL_LOAD_FAILED error_type=%s", e.error_type)
            return False

    def unload(self) -> None:
        if self.state == STATE_UNLOADED:
            return
        logger.info("[IMAGE] name=qwen-image action=MODEL_UNLOADED")
        self.state = STATE_UNLOADED

    def ensure_loaded(self) -> bool:
        if self.state != STATE_READY:
            return self.load()
        return True

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
        request_id: str = "",
    ) -> ImageGenResult:
        t0 = time.perf_counter()
        rid = request_id or _default_request_id()
        prompt = (prompt or "").strip()

        def _safe_device() -> str:
            try:
                return str(self.backend.device_info().get("device", "cpu"))
            except Exception:
                return "cpu"

        def fail(error_type: str, message: str, detail: Optional[dict] = None) -> ImageGenResult:
            return ImageGenResult(
                success=False,
                message=message,
                prompt=prompt,
                width=width or self.config.width,
                height=height or self.config.height,
                steps=steps or self.config.steps,
                seed=seed,
                provider=self.config.provider,
                device=_safe_device(),
                request_id=rid,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error_type=error_type,
                detail=dict(detail or {}),
            )

        if not prompt:
            return fail(ERROR_INVALID_PROMPT, "Image prompt must not be empty.")

        if not self.ensure_loaded():
            err = self.last_error
            return fail(
                err.error_type if err else ERROR_GENERATION_FAILED,
                err.message if err else "Image generation is not available.",
            )

        w = max(64, min(2048, int(width or self.config.width)))
        h = max(64, min(2048, int(height or self.config.height)))
        s = max(1, min(50, int(steps or self.config.steps)))

        self.state = STATE_GENERATING
        logger.info("[IMAGE] name=qwen-image action=GENERATION_STARTED request_id=%s", rid)

        params = BuildParams(
            prompt=prompt,
            width=w,
            height=h,
            steps=s,
            seed=seed if seed is not None and seed >= 0 else -1,
            cfg_scale=self.config.cfg_scale,
            sampling_method=self.config.sampling_method,
            flow_shift=self.config.flow_shift,
            vae_tiling=self.config.vae_tiling,
            diffusion_fa=self.config.diffusion_fa,
            offload_to_cpu=self.config.offload_to_cpu,
        )

        try:
            output_path = allocate_output_path(self.output_dir, now=self._now)
        except OSError as e:
            self.state = STATE_ERROR
            logger.error("[IMAGE] name=qwen-image action=GENERATION_FAILED reason=output_dir")
            return fail(
                ERROR_OUTPUT_DIR,
                f"Cannot create output directory: {e}",
            )

        restores = self._release_gpu()
        try:
            run = self.backend.generate(params, str(output_path), request_id=rid)
        except ImageServiceError as e:
            self.state = STATE_ERROR
            logger.error(
                "[IMAGE] name=qwen-image action=GENERATION_FAILED request_id=%s error_type=%s",
                rid, e.error_type,
            )
            if e.details.get("tail"):
                logger.error(
                    "[IMAGE] name=qwen-image action=GENERATION_DIAGNOSTICS request_id=%s %s",
                    rid, " | ".join(str(t) for t in e.details["tail"][-6:]),
                )
            cleanup_if_failed(output_path)
            result = fail(e.error_type, e.message, e.details)
            result.detail = dict(e.details)
            return self._finish(result, keep_ready=False)
        finally:
            restore_gpu_memory(restores)

        if not is_valid_png(output_path):
            logger.error(
                "[IMAGE] name=qwen-image action=GENERATION_FAILED request_id=%s reason=invalid_output",
                rid,
            )
            cleanup_if_failed(output_path)
            return self._finish(
                fail(ERROR_GENERATION_FAILED, "The image backend did not produce a valid PNG."),
                keep_ready=False,
            )

        day_dir = output_path.parent
        metadata = self._build_metadata(prompt, w, h, s, params.seed, rid, run.get("elapsed_ms", 0.0))
        write_metadata(day_dir, output_path.name, metadata)

        logger.info(
            "[IMAGE] name=qwen-image action=GENERATION_COMPLETED request_id=%s "
            "elapsed_ms=%.1f device=%s width=%d height=%d steps=%d seed=%s out=%s",
            rid,
            run.get("elapsed_ms", 0.0),
            run.get("device", "?"),
            w, h, s, params.seed if params.seed >= 0 else None,
            output_path,
        )

        result = ImageGenResult(
            success=True,
            message=f"Generated image saved to {self._relative(output_path)}",
            path=str(output_path),
            filename=output_path.name,
            prompt=prompt,
            width=w,
            height=h,
            steps=s,
            seed=params.seed if params.seed >= 0 else None,
            provider=self.config.provider,
            backend=self.backend.backend_name,
            device=str(run.get("device", "cpu")),
            request_id=rid,
            elapsed_ms=float(run.get("elapsed_ms", 0.0)),
            detail=metadata,
        )
        return self._finish(result)

    def _release_gpu(self) -> list:
        """Free GPU memory held by other F.R.I.D.A.Y. components before a
        generation, then warn if unrelated apps leave too little VRAM for the
        diffusion model to stay resident. Returns restore callables."""
        if not self.config.free_vram_before_generate:
            return []
        try:
            device = str(self.backend.device_info().get("device", "cpu"))
        except Exception:
            return []
        if device != "cuda":
            return []

        restores = release_gpu_memory()

        mem = gpu_memory_mb()
        if mem is None:
            return restores
        used, free = mem
        if free < _LOW_VRAM_MB:
            holders = gpu_compute_process_names()
            logger.warning(
                "[IMAGE] only %d MiB VRAM free (%d MiB used); the diffusion model "
                "may stream from RAM and run slowly. GPU processes: %s. Close "
                "unused GPU apps for faster generation.",
                free, used, ", ".join(holders) or "unknown",
            )
        else:
            logger.info("[IMAGE] %d MiB VRAM free before generation", free)
        return restores

    def _finish(self, result: ImageGenResult, keep_ready: bool = True) -> ImageGenResult:
        if self.state in (STATE_GENERATING, STATE_ERROR):
            self.state = STATE_READY if keep_ready else STATE_UNLOADED
        if not self.config.keep_loaded:
            self.unload()
        return result

    def _build_metadata(self, prompt, w, h, s, seed, rid, elapsed_ms) -> dict:
        return {
            "success": True,
            "request_id": rid,
            "provider": self.config.provider,
            "backend": self.backend.backend_name,
            "device": self.backend.device_info().get("device", "cpu"),
            "prompt": prompt,
            "width": w,
            "height": h,
            "steps": s,
            "seed": seed if seed >= 0 else None,
            "elapsed_ms": round(elapsed_ms, 1),
            "error_type": "",
        }

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(Path(".").resolve()))
        except (ValueError, OSError):
            return str(path)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self) -> dict:
        """Non-raising health snapshot: never probes the runtime when queried;
        each probe is best-effort and reported in its own flag."""
        executable = self.backend.executable or ""
        components = {"model": "", "text_encoder": "", "vae": ""}
        installed = bool(executable)
        configured = False
        try:
            components = self.backend.resolve_components()
            configured = bool(components["model"])
        except ImageServiceError:
            configured = False
        except Exception:
            configured = False

        device_info = {"device": "unknown", "gpu_name": None, "vram_total_mb": None}
        try:
            device_info = self.backend.device_info()
        except Exception:
            pass

        ready = installed and configured
        return {
            "provider": self.config.provider,
            "installed": installed,
            "configured": configured,
            "loaded": self.state == STATE_READY,
            "device": device_info["device"],
            "ready": ready,
            "executable": executable or None,
            "model_path": components.get("model") or None,
            "text_encoder_path": components.get("text_encoder") or None,
            "vae_path": components.get("vae") or None,
            "gpu_name": device_info.get("gpu_name"),
            "vram_total_mb": device_info.get("vram_total_mb"),
            "keep_loaded": self.config.keep_loaded,
            "backend": self.backend.backend_name,
            "state": self.state,
        }