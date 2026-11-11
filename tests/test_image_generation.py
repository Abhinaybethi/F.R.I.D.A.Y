"""
UNIT TEST — Qwen-Image Generation Integration
================================================
Tests router classification, tool contract, permissions, config resolution,
output allocation, and manager generation (with a fake backend — no sd.cpp,
no model files, no GPU required). All deterministic.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.image.config import QwenImageConfig
from friday.image.output import allocate_output_path, is_valid_png, write_metadata
from friday.image.manager import QwenImageManager, STATE_UNLOADED, STATE_READY
from friday.image.results import ERROR_EXECUTABLE_MISSING
from friday.intent.models import Action
from friday.intent.router import route
from friday.tools import registry
from friday.tools.image_gen import generate_image
from friday.verification.models import FinalStatus

_ALL_ENABLED = {
    "open_app": True, "close_app": True, "open_folder": True,
    "open_website": True, "search_web": True, "get_time": True,
    "find_file": True, "open_file": True, "generate_image": True,
    "read_website": True, "play_video": True, "greeting": True,
}

_DENY_IMAGE = {**{k: True for k in _ALL_ENABLED}, "generate_image": False}


def _tiny_png_bytes() -> bytes:
    try:
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (128, 64, 32)).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FakeBackend:
    """Stands in for StableDiffusionCppBackend: writes a real PNG on generate."""

    backend_name = "fake-backend (test)"

    def __init__(self, executable="sd-cli", data: bytes = None):
        self.executable = executable
        self._data = data if data is not None else _tiny_png_bytes()
        self.request_ids = []

    def ensure_executable(self) -> str:
        return self.executable

    def resolve_components(self):
        return {"model": "m.gguf", "text_encoder": "t.gguf", "vae": "v.safetensors"}

    def device_info(self):
        return {"device": "cuda", "gpu_name": "Test GPU", "vram_total_mb": 8192}

    def generate(self, params, output_path: str, request_id: str = ""):
        self.request_ids.append(request_id)
        Path(output_path).write_bytes(self._data)
        return {"elapsed_ms": 12.5, "device": "cuda"}


class MissingBackend(FakeBackend):
    def __init__(self):
        super().__init__(executable=None)

    def ensure_executable(self) -> str:
        from friday.image.results import ImageServiceError
        raise ImageServiceError(ERROR_EXECUTABLE_MISSING, "sd-cli not found (test)")


def _make_manager(tmp_path, backend=None, fixed: datetime | None = None):
    cfg = QwenImageConfig(
        keep_loaded=False,
        output_dir=str(tmp_path),
        executable="sd-cli",
    )
    return QwenImageManager(
        config=cfg,
        backend=backend or FakeBackend(),
        output_dir=str(tmp_path),
        now=fixed or datetime(2026, 1, 2, 3, 4, 5),
    )


@pytest.fixture(autouse=True)
def _hermetic_gpu_probe(monkeypatch):
    """Keep unit tests off the real GPU: stub nvidia-smi probes and reset hooks."""
    from friday.image import manager as manager_module
    from friday.image.gpu_hooks import clear_gpu_release_hooks

    clear_gpu_release_hooks()
    monkeypatch.setattr(manager_module, "gpu_memory_mb", lambda: (1200, 8000))
    monkeypatch.setattr(manager_module, "gpu_compute_process_names", lambda: [])
    yield
    clear_gpu_release_hooks()


# --------------------------------------------------------------------------
# Router classification
# --------------------------------------------------------------------------

def test_route_generate_image():
    assert route("generate an image of a cat").action is Action.IMAGE_GENERATION
    assert route("generate an image of a cat").target == "a cat"


def test_route_create_picture():
    i = route("create a picture of the Eiffel Tower")
    assert i.action is Action.IMAGE_GENERATION
    assert i.target == "the eiffel tower"  # router normalizes to lowercase


def test_route_search_phrase_image():
    i = route("search for a picture of a sunset")
    assert i.action is Action.IMAGE_GENERATION
    assert i.target == "a sunset"


def test_route_find_phrase_photo():
    i = route("find an image of an airplane")
    assert i.action is Action.IMAGE_GENERATION
    assert i.target == "an airplane"


def test_route_show_me_photo():
    i = route("show me a photo of the ocean")
    assert i.action is Action.IMAGE_GENERATION
    assert i.target == "the ocean"


def test_route_draw_bare():
    i = route("draw a dragon")
    assert i.action is Action.IMAGE_GENERATION
    assert i.target == "a dragon"


def test_route_conversational_prefix():
    i = route("can you draw a cat")
    assert i.action is Action.IMAGE_GENERATION
    assert i.target == "a cat"


def test_route_non_image_searches_still_route():
    assert route("search the latest airplane news").action is Action.SEARCH_WEB
    assert route("find my resume").action is Action.FIND_FILE
    assert route("search for python tutorials on chrome").action is Action.SEARCH_WEB


# --------------------------------------------------------------------------
# Tool contract & permissions
# --------------------------------------------------------------------------

def test_generate_image_dry_run_contract():
    res = generate_image("a cat", dry_run=True)
    assert res["success"] is True
    assert "[DRY RUN]" in res["message"]
    assert res["event"] == "image_generated"
    assert res["dry_run"] is True


def test_registry_dispatch_dry_run():
    outcome = registry.execute(
        intent=__import__("friday.intent.models", fromlist=["Intent"]).Intent(
            action=Action.IMAGE_GENERATION, target="a cat"
        ),
        dry_run=True,
        permissions=_ALL_ENABLED,
    )
    assert outcome.execution.status.name == "SUCCESS"
    assert outcome.final_status == FinalStatus.DRY_RUN


def test_registry_denied_permission():
    outcome = registry.execute(
        intent=__import__("friday.intent.models", fromlist=["Intent"]).Intent(
            action=Action.IMAGE_GENERATION, target="a cat"
        ),
        dry_run=False,
        permissions=_DENY_IMAGE,
    )
    assert outcome.final_status == FinalStatus.BLOCKED


def test_generate_image_real_with_fake_backend(tmp_path):
    data = _tiny_png_bytes()
    mgr = _make_manager(tmp_path, backend=FakeBackend(data=data))
    res = generate_image("a test cat", dry_run=False, manager=mgr)
    assert res["success"] is True
    assert res["event"] == "image_generated"
    assert res["path"] and Path(res["path"]).exists()
    assert len(mgr.backend.request_ids) == 1


# --------------------------------------------------------------------------
# Output allocation & metadata
# --------------------------------------------------------------------------

def test_allocate_never_overwrites(tmp_path):
    output_dir = tmp_path / "gen"
    first = allocate_output_path(output_dir, now=datetime(2026, 1, 2))
    second = allocate_output_path(output_dir, now=datetime(2026, 1, 2))
    assert first.name == "image_001.png"
    assert second.name == "image_002.png"
    assert first.parent.name == "2026-01-02"


def test_write_metadata_sidecar(tmp_path):
    day = tmp_path / "2026-01-02"
    day.mkdir(parents=True)
    path = write_metadata(day, "image_001.png", {"prompt": "x", "seed": 7})
    assert path and Path(path).exists()
    import json
    assert json.loads(Path(path).read_text(encoding="utf-8"))["seed"] == 7


def test_is_valid_png(tmp_path):
    good = tmp_path / "ok.png"
    good.write_bytes(_tiny_png_bytes())
    assert is_valid_png(good) is True
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png at all")
    assert is_valid_png(bad) is False


# --------------------------------------------------------------------------
# Manager lifecycle + generation with fake backend
# --------------------------------------------------------------------------

def test_manager_generates_and_becomes_ready(tmp_path):
    mgr = _make_manager(tmp_path)
    assert mgr.state == STATE_UNLOADED
    result = mgr.generate("a sunset", request_id="r1")
    assert result.success is True
    assert result.request_id == "r1"
    assert Path(result.path).exists()
    meta = Path(result.path).with_suffix(".json")
    assert meta.exists()
    assert result.metadata_payload()["prompt"] == "a sunset"
    # keep_loaded=False (CLI-style single-shot backend) → preflight released
    assert mgr.state == STATE_UNLOADED


def test_manager_keep_loaded_retains_preflight(tmp_path):
    cfg = QwenImageConfig(keep_loaded=True, output_dir=str(tmp_path))
    mgr = QwenImageManager(config=cfg, backend=FakeBackend(), output_dir=str(tmp_path))
    result = mgr.generate("a cat")
    assert result.success is True
    assert mgr.state == STATE_READY


def test_manager_generates_with_style_params(tmp_path):
    mgr = _make_manager(tmp_path)
    result = mgr.generate("a cat", width=512, height=768, steps=8, seed=42)
    assert result.success is True
    assert result.width == 512
    assert result.height == 768
    assert result.steps == 8
    assert result.seed == 42


def test_manager_missing_backend_structured_failure(tmp_path):
    mgr = _make_manager(tmp_path, backend=MissingBackend())
    result = mgr.generate("a cat")
    assert result.success is False
    assert result.error_type == ERROR_EXECUTABLE_MISSING
    assert not result.path


def test_manager_empty_prompt_fails(tmp_path):
    mgr = _make_manager(tmp_path)
    result = mgr.generate("   ")
    assert result.success is False
    assert result.error_type == "invalid_prompt"


def test_manager_health_snapshot(tmp_path):
    mgr = _make_manager(tmp_path)
    h = mgr.health()
    assert h["provider"] == "qwen-image"
    assert h["installed"] is True
    assert h["configured"] is True
    assert h["ready"] is True
    assert h["device"] == "cuda"


# --------------------------------------------------------------------------
# Config resolution
# --------------------------------------------------------------------------

def test_config_env_override():
    cfg = QwenImageConfig.from_mapping(
        mapping={"width": 512, "height": 512, "steps": 8},
        env={"FRIDAY_QWEN_WIDTH": "768", "FRIDAY_QWEN_TIMEOUT": "120"},
    )
    assert cfg.width == 768
    assert cfg.steps == 8
    assert cfg.timeout == 120.0


def test_config_env_disabled():
    cfg = QwenImageConfig.from_mapping(env={"FRIDAY_IMAGE_ENABLED": "false"})
    assert cfg.enabled is False


def test_health_reports_missing_executable(tmp_path):
    mgr = QwenImageManager(
        config=QwenImageConfig(output_dir=str(tmp_path)),
        backend=MissingBackend(),
        output_dir=str(tmp_path),
    )
    h = mgr.health()
    assert h["installed"] is False
    assert h["ready"] is False


# --------------------------------------------------------------------------
# Regression: text-encoder placement (root cause) + diagnostics retention
#
# Failure mode reproduced on an RTX 3050 6GB: sd-cli stages the ~4.3GB
# Qwen3-VL-8B text encoder onto the GPU; under VRAM pressure the encoder's
# compute-workspace allocation fails ("qwen3vl ... workspace capacity check"),
# sd-cli exits non-zero, F.R.I.D.A.Y. reported a bare generation_failed and
# discarded stderr. Fix: place the encoder on CPU when the GPU is small, and
# retain the full diagnostic tail.
# --------------------------------------------------------------------------

import friday.image.backend as backend_module
from friday.image.backend import (
    BuildParams,
    StableDiffusionCppBackend,
    build_command,
    text_encoder_backend,
)
from friday.image.results import ERROR_GENERATION_FAILED, ImageServiceError


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _backend(vram_mb, device="cuda"):
    b = StableDiffusionCppBackend(QwenImageConfig(), executable="sd-cli")
    b.device_info = lambda: {"device": device, "gpu_name": "Test GPU", "vram_total_mb": vram_mb}
    return b


def test_text_encoder_backend_auto_on_small_gpu():
    assert text_encoder_backend(QwenImageConfig(), {"device": "cuda", "vram_total_mb": 6144}) == "llm=cpu"


def test_text_encoder_backend_auto_on_large_gpu():
    assert text_encoder_backend(QwenImageConfig(), {"device": "cuda", "vram_total_mb": 24576}) == ""


def test_text_encoder_backend_not_forced_on_cpu_device():
    assert text_encoder_backend(QwenImageConfig(), {"device": "cpu", "vram_total_mb": None}) == ""


def test_text_encoder_backend_explicit_modes():
    assert text_encoder_backend(
        QwenImageConfig(text_encoder_device="cpu"), {"device": "cuda", "vram_total_mb": 99999}
    ) == "llm=cpu"
    assert text_encoder_backend(
        QwenImageConfig(text_encoder_device="gpu"), {"device": "cuda", "vram_total_mb": 2048}
    ) == ""


def test_text_encoder_backend_respects_explicit_extra_args():
    assert text_encoder_backend(
        QwenImageConfig(),
        {"device": "cuda", "vram_total_mb": 6144},
        extra_args='--backend "diffusion=vulkan1,llm=gpu"',
    ) == ""


def test_config_text_encoder_device_mapping_and_env():
    assert QwenImageConfig().text_encoder_device == "auto"
    assert QwenImageConfig.from_mapping(
        mapping={"text_encoder_device": "cpu"}, env={}
    ).text_encoder_device == "cpu"
    assert QwenImageConfig.from_mapping(
        env={"FRIDAY_QWEN_TEXT_ENCODER_DEVICE": "gpu"}
    ).text_encoder_device == "gpu"


def test_build_command_emits_backend_before_extra_args():
    cmd = build_command(
        "sd-cli",
        {"model": "m.gguf", "text_encoder": "t.gguf", "vae": "v.safetensors"},
        BuildParams(prompt="a cat", seed=-1),
        "out.png",
        backend="llm=cpu",
    )
    assert cmd[-2:] == ["--backend", "llm=cpu"]


def test_backend_generate_forces_llm_cpu_on_6gb(tmp_path, monkeypatch):
    b = _backend(6144)
    monkeypatch.setattr(backend_module, "resolve_components", lambda cfg: {"model": "m", "text_encoder": "t", "vae": "v"})
    seen = {}
    monkeypatch.setattr(
        backend_module.subprocess, "run",
        lambda cmd, **kw: (seen.__setitem__("cmd", cmd) or _Proc()),
    )
    b.generate(BuildParams(prompt="x", width=512, height=512, steps=4), str(tmp_path / "o.png"))
    assert seen["cmd"][seen["cmd"].index("--backend") + 1] == "llm=cpu"


def test_backend_generate_no_backend_on_large_gpu(tmp_path, monkeypatch):
    b = _backend(24576)
    monkeypatch.setattr(backend_module, "resolve_components", lambda cfg: {"model": "m", "text_encoder": "t", "vae": "v"})
    seen = {}
    monkeypatch.setattr(
        backend_module.subprocess, "run",
        lambda cmd, **kw: (seen.__setitem__("cmd", cmd) or _Proc()),
    )
    b.generate(BuildParams(prompt="x"), str(tmp_path / "o.png"))
    assert "--backend" not in seen["cmd"]


def test_backend_generate_preserves_root_cause_line(tmp_path, monkeypatch):
    b = _backend(6144)
    monkeypatch.setattr(backend_module, "resolve_components", lambda cfg: {"model": "m", "text_encoder": "t", "vae": "v"})
    stderr = "\n".join(f"[I] noise line {i}" for i in range(30)) + (
        "\n[E] qwen3vl segment 1/1 (graph) failed during workspace capacity check"
        "\n[E] generate failed"
    )
    monkeypatch.setattr(backend_module.subprocess, "run", lambda cmd, **kw: _Proc(returncode=1, stderr=stderr))
    with pytest.raises(ImageServiceError) as exc:
        b.generate(BuildParams(prompt="x"), str(tmp_path / "o.png"))
    details = exc.value.details
    assert details["returncode"] == 1
    assert any("workspace capacity check" in line for line in details["tail"])
    assert "--backend" in details["command"]


class FailingBackend(FakeBackend):
    def generate(self, params, output_path, request_id=""):
        raise ImageServiceError(
            ERROR_GENERATION_FAILED,
            "Image generation process failed.",
            {"returncode": 1, "tail": ["[E] qwen3vl ... workspace capacity check"]},
        )


def test_manager_surfaces_failure_detail_in_to_dict(tmp_path):
    mgr = _make_manager(tmp_path, backend=FailingBackend())
    result = mgr.generate("a cat")
    assert result.success is False
    assert result.error_type == ERROR_GENERATION_FAILED
    payload = result.to_dict()
    assert payload["detail"]["returncode"] == 1
    assert any("workspace capacity check" in line for line in payload["detail"]["tail"])


def test_is_valid_png_rejects_truncated(tmp_path):
    pytest.importorskip("PIL")
    bad = tmp_path / "trunc.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    assert is_valid_png(bad) is False


# --------------------------------------------------------------------------
# Free VRAM before generation (release hooks + reasoner handoff)
# --------------------------------------------------------------------------

def _manager_with_flag(tmp_path, flag=True):
    cfg = QwenImageConfig(
        keep_loaded=False,
        output_dir=str(tmp_path),
        executable="sd-cli",
        free_vram_before_generate=flag,
    )
    return QwenImageManager(
        config=cfg,
        backend=FakeBackend(),
        output_dir=str(tmp_path),
        now=datetime(2026, 1, 2, 3, 4, 5),
    )


def test_gpu_hooks_release_then_restore_in_reverse_order():
    from friday.image.gpu_hooks import (
        register_gpu_release_hook,
        release_gpu_memory,
        restore_gpu_memory,
    )

    calls = []

    def hook_a():
        calls.append("a")
        return lambda: calls.append("ra")

    def hook_b():
        calls.append("b")
        return lambda: calls.append("rb")

    register_gpu_release_hook(hook_a)
    register_gpu_release_hook(hook_b)
    restores = release_gpu_memory()
    assert calls == ["a", "b"]
    restore_gpu_memory(restores)
    assert calls == ["a", "b", "rb", "ra"]


def test_gpu_hooks_skip_failing_hook():
    from friday.image.gpu_hooks import register_gpu_release_hook, release_gpu_memory

    def boom():
        raise RuntimeError("nope")

    register_gpu_release_hook(boom)
    register_gpu_release_hook(lambda: None)
    assert release_gpu_memory() == []


def test_manager_releases_before_and_restores_after_generation(tmp_path):
    from friday.image.gpu_hooks import register_gpu_release_hook

    events = []

    class RecordingBackend(FakeBackend):
        def generate(self, params, output_path, request_id=""):
            events.append("generate")
            return super().generate(params, output_path, request_id)

    def hook():
        events.append("release")
        return lambda: events.append("restore")

    register_gpu_release_hook(hook)
    mgr = _manager_with_flag(tmp_path, flag=True)
    mgr.backend = RecordingBackend()
    assert mgr.generate("a cat").success is True
    assert events == ["release", "generate", "restore"]


def test_manager_skips_release_when_disabled(tmp_path):
    from friday.image.gpu_hooks import register_gpu_release_hook

    called = []

    def hook():
        called.append("release")
        return None

    register_gpu_release_hook(hook)
    assert _manager_with_flag(tmp_path, flag=False).generate("a cat").success is True
    assert called == []


def test_manager_warns_when_vram_low(tmp_path, monkeypatch):
    from friday.image import manager as manager_module

    monkeypatch.setattr(manager_module, "gpu_memory_mb", lambda: (4134, 1881))
    monkeypatch.setattr(
        manager_module, "gpu_compute_process_names", lambda: ["brave.exe", "ollama.exe"]
    )
    captured = []
    monkeypatch.setattr(
        manager_module.logger, "warning",
        lambda msg, *a, **k: captured.append(msg % a if a else msg),
    )
    assert _manager_with_flag(tmp_path, flag=True).generate("a cat").success is True
    text = "\n".join(captured)
    assert "1881 MiB VRAM free" in text
    assert "brave.exe" in text and "ollama.exe" in text


def test_config_free_vram_flag_mapping_and_env():
    assert QwenImageConfig.from_mapping(env={"FRIDAY_QWEN_FREE_VRAM": "false"}).free_vram_before_generate is False
    assert QwenImageConfig.from_mapping(mapping={"free_vram_before_generate": False}, env={}).free_vram_before_generate is False
    assert QwenImageConfig.from_mapping(env={}).free_vram_before_generate is True


def test_free_reasoner_gpu_stops_owned_server_and_restarts():
    import logging
    import types

    assistant_mod = pytest.importorskip("friday.core.assistant")

    class _SM:
        def __init__(self, owned):
            self.owned = owned
            self.stopped = 0
            self.started = 0

        def is_owned(self):
            return self.owned

        def stop(self):
            self.stopped += 1

        def start(self):
            self.started += 1
            return True

    dummy = types.SimpleNamespace(server_manager=_SM(True), logger=logging.getLogger("test"))
    restore = assistant_mod.Friday._free_reasoner_gpu(dummy)
    assert dummy.server_manager.stopped == 1
    assert callable(restore)
    restore()
    assert dummy.server_manager.started == 1


def test_free_reasoner_gpu_leaves_external_server_untouched():
    import logging
    import types

    assistant_mod = pytest.importorskip("friday.core.assistant")

    class _SM:
        def __init__(self):
            self.stopped = 0

        def is_owned(self):
            return False

        def stop(self):
            self.stopped += 1

    dummy = types.SimpleNamespace(server_manager=_SM(), logger=logging.getLogger("test"))
    assert assistant_mod.Friday._free_reasoner_gpu(dummy) is None
    assert dummy.server_manager.stopped == 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])