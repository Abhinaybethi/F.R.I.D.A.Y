"""
UNIT TEST — Qwen-Image setup workflow
========================================
Tests the verified install manifest, plan validation, resumable download with
checksum verification, failure handling, disk-space checks, and the no-
overwrite policy. All network access is mocked (no bytes are ever downloaded).
"""
import hashlib
import io
import os
import sys
import types
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from friday.image import setup as image_setup
from friday.image.backend import StableDiffusionCppBackend, build_command, resolve_executable
from friday.image.backend import BuildParams
from friday.image.config import QwenImageConfig
from friday.image.setup import (
    DIFFUSION_QUANTS,
    MODEL_BASE_DIR,
    QWEN_LICENSED_KEYS,
    RUNTIME_ASSETS,
    RUNTIME_BIN_DIR,
    SD_CPP_COMMIT,
    SD_CPP_RELEASE_TAG,
    TEXT_ENCODER_RESOURCE,
    VAE_RESOURCE,
    Resource,
    SetupError,
    build_plan,
    describe_plan,
    download_file,
    plan_needs_license,
    run_plan,
    sha256_file,
)


class FakeResp:
    def __init__(self, data: bytes, status: int):
        self._bio = io.BytesIO(data)
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._bio.read(n)

    def close(self):
        pass


class RecordingOpener:
    """Serves per-URL payloads, honors Range, and records every request."""

    def __init__(self, by_url, range_status: int = 206):
        self.by_url = dict(by_url)
        self.requests = []
        self.range_status = range_status

    def __call__(self, url, headers):
        self.requests.append((url, dict(headers)))
        if url not in self.by_url:
            raise SetupError("http_error", f"no fixture for {url}")
        data = self.by_url[url]
        rang = headers.get("Range")
        if rang:
            if self.range_status == 206:
                start = int(rang.split("=")[1].split("-")[0])
                return FakeResp(data[start:], 206)
            return FakeResp(data, 200)
        return FakeResp(data, 200)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_resource(tmp_path, key="data", data=None, url=None):
    data = data if data is not None else bytes(range(256)) * 8  # 2048 bytes
    return Resource(
        key=key,
        description=key,
        kind="file",
        url=url or f"https://example.test/{key}",
        size=len(data),
        sha256=_sha(data),
        target=tmp_path / key,
    )


def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Verified manifest identity (recorded from upstream on 2026-10-12)
# --------------------------------------------------------------------------

def test_manifest_pinned_runtime_identity():
    assert SD_CPP_RELEASE_TAG == "master-956-1b0ba10"
    assert SD_CPP_COMMIT == "1b0ba10"
    assert RUNTIME_ASSETS["cpu"] == (
        ("sd-master-1b0ba10-bin-win-cpu-x64.zip", 17543461,
         "39c2ea1cc03f697864c858ad0b22b9b8ce62f945ba428e8596a814527e6db6fb"),
    )
    assert RUNTIME_ASSETS["vulkan"][0][0].endswith("win-vulkan-x64.zip")
    cuid = RUNTIME_ASSETS["cuda"]
    assert len(cuid) == 2  # build + runtime DLLs
    assert cuid[1][0] == "cudart-sd-bin-win-cu12-x64.zip"


def test_manifest_pinned_model_identity():
    assert DIFFUSION_QUANTS["q4_k"] == (
        "qwen_image_2.1-Q4_K.gguf", 4197494816,
        "29f9c83c249ff0292fb2943fceddfa2319b446601866c82a4f8be062abea72c2",
    )
    assert VAE_RESOURCE == (
        "vae/qwen_image_2.1_vae_bf16.safetensors", 675509688,
        "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9",
    )
    assert TEXT_ENCODER_RESOURCE == (
        "Qwen3VL-8B-Instruct-Q4_K_M.gguf", 5027784800,
        "67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2",
    )


def test_manifest_all_items_have_checksums_and_sizes():
    for quant, (name, size, digest) in DIFFUSION_QUANTS.items():
        assert name.endswith(".gguf") and file_size_positive(size), quant
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), quant
    for name, size, digest in VAE_RESOURCE, TEXT_ENCODER_RESOURCE:
        assert size > 0 and len(digest) == 64
    for backend, assets in RUNTIME_ASSETS.items():
        for name, size, digest in assets:
            assert size > 0 and len(digest) == 64, f"{backend}:{name}"


def file_size_positive(size: int) -> bool:
    return size > 0


def test_licensed_keys_exact():
    assert QWEN_LICENSED_KEYS == {"diffusion", "vae"}


# --------------------------------------------------------------------------
# Plan construction and validation
# --------------------------------------------------------------------------

def test_plan_layout_matches_package_discovery(tmp_path):
    plan = build_plan("cpu", "q4_k", ("all",), root=tmp_path)
    assert [r.key for r in plan] == ["executable", "diffusion", "vae", "text-encoder"]
    by_key = {r.key: r for r in plan}

    exe = by_key["executable"]
    assert exe.kind == "zip"
    assert exe.target.name == "sd-cli.exe"
    assert exe.archive == tmp_path / RUNTIME_BIN_DIR / "sd-master-1b0ba10-bin-win-cpu-x64.zip"

    diff = by_key["diffusion"]
    assert diff.target == tmp_path / MODEL_BASE_DIR / "diffusion" / "qwen_image_2.1-Q4_K.gguf"
    vae = by_key["vae"]
    assert vae.target == tmp_path / MODEL_BASE_DIR / "vae" / "qwen_image_2.1_vae_bf16.safetensors"
    te = by_key["text-encoder"]
    assert te.target == tmp_path / MODEL_BASE_DIR / "text_encoder" / "Qwen3VL-8B-Instruct-Q4_K_M.gguf"

    assert diff.url.startswith("https://huggingface.co/leejet/Qwen-Image-2.1-GGUF/resolve/main/")
    assert vae.url.startswith("https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/main/")
    assert te.url.startswith("https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/")
    assert exe.url.startswith(
        "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-956-1b0ba10/"
    )
    assert plan_needs_license(plan) is True
    assert by_key["diffusion"].license == "qwen-research"
    assert by_key["vae"].license == "qwen-research"
    assert by_key["text-encoder"].license is None


def test_plan_components_partial_and_no_license(tmp_path):
    plan = build_plan("cpu", "q4_k", ("text-encoder", "executable"), root=tmp_path)
    assert [r.key for r in plan] == ["executable", "text-encoder"]
    assert plan_needs_license(plan) is False


def test_plan_cuda_has_two_distinct_archives(tmp_path):
    plan = build_plan("cuda", "q4_k", ("executable",), root=tmp_path)
    assert len(plan) == 2
    a = {p.archive for p in plan}
    assert len(a) == 2  # build zip + cudart zip, no .part collision


@pytest.mark.parametrize("bad", [
    dict(backend="hip"),
    dict(quant="q9_k"),
    dict(components=("wat",)),
    dict(components=()),
])
def test_plan_rejects_unknown_inputs(tmp_path, bad):
    kinds = {"backend": "cpu", "quant": "q4_k", "components": ("all",)}
    kinds.update(bad)
    with pytest.raises(SetupError) as ei:
        build_plan(kinds["backend"], kinds["quant"], kinds["components"], root=tmp_path)
    assert ei.value.code == "invalid_config"


def test_describe_plan_is_network_free(tmp_path):
    plan = build_plan("cpu", "q4_k", ("all",), root=tmp_path)
    lines = describe_plan(plan)
    joined = "\n".join(lines)
    assert "9," in joined or "MB" in joined
    assert SD_CPP_COMMIT in joined


# --------------------------------------------------------------------------
# Resumable download + verification
# --------------------------------------------------------------------------

def test_download_success_verified(tmp_path):
    data = bytes(range(256)) * 8
    res = _file_resource(tmp_path, data=data)
    opener = RecordingOpener({res.url: data})
    download_file(res, open_func=opener)
    assert res.target.read_bytes() == data
    assert not Path(str(res.target) + ".part").exists()
    assert len(opener.requests) == 1
    assert "Range" not in opener.requests[0][1]


def test_download_resumes_with_range(tmp_path):
    data = bytes(range(256)) * 512  # 128 KiB
    res = _file_resource(tmp_path, data=data)
    half = len(data) // 2
    part = Path(str(res.target) + ".part")
    part.write_bytes(data[:half])
    opener = RecordingOpener({res.url: data})
    download_file(res, open_func=opener)
    assert res.target.read_bytes() == data
    url, headers = opener.requests[0]
    assert headers["Range"] == f"bytes={half}-"


def test_download_http_404_structured_error(tmp_path):
    res = _file_resource(tmp_path)
    def failing(url, headers):
        raise urllib_error_404(url)
    with pytest.raises(SetupError) as ei:
        download_file(res, open_func=failing)
    assert ei.value.code == "http_error"
    assert not res.target.exists()
    assert not Path(str(res.target) + ".part").exists()


def urllib_error_404(url):
    import urllib.error
    return urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO())


def test_download_checksum_mismatch_removes_partial(tmp_path):
    good = bytes(range(256)) * 8
    res = _file_resource(tmp_path, data=good)
    wrong = b"\x00" * len(good)  # same size, different content
    opener = RecordingOpener({res.url: wrong})
    with pytest.raises(SetupError) as ei:
        download_file(res, open_func=opener)
    assert ei.value.code == "checksum_mismatch"
    assert not res.target.exists()
    assert not Path(str(res.target) + ".part").exists()


# --------------------------------------------------------------------------
# Overwrite protection
# --------------------------------------------------------------------------

def test_run_plan_skips_verified_existing_file(tmp_path):
    data = bytes(range(256)) * 8
    res = _file_resource(tmp_path, data=data)
    res.target.write_bytes(data)
    opener = RecordingOpener({res.url: data})
    summary = run_plan([res], root=tmp_path, verify_binary=False, open_func=opener)
    assert opener.requests == []
    assert summary["skipped"] == ["data"]


def test_run_plan_requires_force_to_replace(tmp_path):
    data = bytes(range(256)) * 8
    res = _file_resource(tmp_path, data=data)
    res.target.write_bytes(b"old bytes that do not match")  # invalid existing
    opener = RecordingOpener({res.url: data})
    summary = run_plan([res], root=tmp_path, verify_binary=False, open_func=opener)
    assert opener.requests == []
    assert summary["skipped"] == ["data"]
    assert res.target.read_bytes() != data  # untouched without --force

    opener2 = RecordingOpener({res.url: data})
    summary2 = run_plan([res], root=tmp_path, verify_binary=False, force=True, open_func=opener2)
    assert len(opener2.requests) == 1
    assert summary2["replaced"] == ["data"]
    assert res.target.read_bytes() == data


def test_run_plan_force_replaces_verified_file(tmp_path):
    data = bytes(range(256)) * 8
    res = _file_resource(tmp_path, data=data)
    res.target.write_bytes(data)
    opener2 = RecordingOpener({res.url: data})
    summary = run_plan([res], root=tmp_path, verify_binary=False, force=True, open_func=opener2)
    assert summary["replaced"] == ["data"]
    assert len(opener2.requests) == 1


def test_run_plan_disk_full_blocks_before_download(tmp_path, monkeypatch):
    data = bytes(range(256)) * 8
    res = _file_resource(tmp_path, data=data)
    monkeypatch.setattr(image_setup.shutil, "disk_usage", lambda _p: types.SimpleNamespace(free=10))
    opener = RecordingOpener({res.url: data})
    with pytest.raises(SetupError) as ei:
        run_plan([res], root=tmp_path, verify_binary=False, open_func=opener)
    assert ei.value.code == "disk_full"
    assert opener.requests == []


# --------------------------------------------------------------------------
# Zip (runtime) resources
# --------------------------------------------------------------------------

def test_zip_resource_extracts_into_bin(tmp_path):
    zip_data = _zip_bytes({"sd-cli.exe": b"MZ-fake-binary", "ggml.dll": b"dll"})
    res = Resource(
        key="executable",
        description="runtime",
        kind="zip",
        url="https://github.example/x.zip",
        size=len(zip_data),
        sha256=_sha(zip_data),
        target=tmp_path / RUNTIME_BIN_DIR / "sd-cli.exe",
        archive=tmp_path / RUNTIME_BIN_DIR / "asset.zip",
    )
    opener = RecordingOpener({res.url: zip_data})
    summary = run_plan([res], root=tmp_path, verify_binary=False, open_func=opener)
    assert (tmp_path / RUNTIME_BIN_DIR / "sd-cli.exe").read_bytes() == b"MZ-fake-binary"
    assert (tmp_path / RUNTIME_BIN_DIR / "ggml.dll").exists()
    assert not res.archive.exists()          # staged zip cleaned up
    assert not Path(str(res.archive) + ".part").exists()
    assert summary["ok"] == ["executable"]


def test_zip_archive_present_skipped_without_force(tmp_path):
    zip_data = _zip_bytes({"sd-cli.exe": b"MZ-fake-binary"})
    res = Resource(
        key="executable", description="runtime", kind="zip",
        url="https://github.example/x.zip", size=len(zip_data), sha256=_sha(zip_data),
        target=tmp_path / RUNTIME_BIN_DIR / "sd-cli.exe",
        archive=tmp_path / RUNTIME_BIN_DIR / "asset.zip",
    )
    res.archive.parent.mkdir(parents=True)
    res.archive.write_bytes(zip_data)
    opener = RecordingOpener({res.url: zip_data})
    summary = run_plan([res], root=tmp_path, verify_binary=False, open_func=opener)
    assert opener.requests == []
    assert summary["skipped"] == ["executable"]
    assert not res.target.exists()  # not extracted without --force


# --------------------------------------------------------------------------
# Backend/config integrations (extra args + local exe discovery)
# --------------------------------------------------------------------------

def test_build_command_appends_extra_args():
    cmd = build_command(
        "sd-cli",
        {"model": "m.gguf", "text_encoder": "t.gguf", "vae": "v.safetensors"},
        BuildParams(prompt="a cat", seed=-1),
        "out.png",
        extra_args='--backend "diffusion=vulkan1,vae=vulkan1,llm=cpu"',
    )
    assert cmd[-2:] == ["--backend", "diffusion=vulkan1,vae=vulkan1,llm=cpu"]


def test_config_extra_args_from_mapping_and_env():
    cfg = QwenImageConfig.from_mapping(
        mapping={"extra_args": "--model-args qwen_image_2_1_prefix_cache_type=q4_0"},
        env={},
    )
    assert cfg.extra_args == "--model-args qwen_image_2_1_prefix_cache_type=q4_0"
    cfg2 = QwenImageConfig.from_mapping(
        mapping={"extra_args": "--x 1"},
        env={"FRIDAY_QWEN_EXTRA_ARGS": "--backend vulkan1 --fa"},
    )
    assert cfg2.extra_args == "--backend vulkan1 --fa"


def test_resolve_executable_finds_local_exe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exe = tmp_path / "models" / "bin" / "sd-cli.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    found = resolve_executable(QwenImageConfig(executable="sd-cli"))
    assert found and found.replace("/", os.sep).endswith(os.path.join("models", "bin", "sd-cli.exe"))


def test_sha256_file_matches_hashing_lib(tmp_path):
    target = tmp_path / "f.bin"
    target.write_bytes(b"hello world")
    assert sha256_file(target) == hashlib.sha256(b"hello world").hexdigest()


def test_backend_resolve_components_discovers_installed_layout(tmp_path, monkeypatch):
    """The manager calls backend.resolve_components() (it is not module-level
    only); a real installed layout must be discovered so health reports it."""
    base = tmp_path / "models" / "qwen-image"
    (base / "diffusion").mkdir(parents=True)
    (base / "text_encoder").mkdir()
    (base / "vae").mkdir()
    (base / "diffusion" / "qwen_image_2.1-Q4_K.gguf").write_bytes(b"m")
    (base / "text_encoder" / "Qwen3VL-8B-Instruct-Q4_K_M.gguf").write_bytes(b"t")
    (base / "vae" / "qwen_image_2.1_vae_bf16.safetensors").write_bytes(b"v")
    monkeypatch.chdir(tmp_path)

    backend = StableDiffusionCppBackend(QwenImageConfig())
    comps = backend.resolve_components()
    assert "models" in comps["model"]
    assert comps["text_encoder"].endswith(".gguf")
    assert comps["vae"].endswith(".safetensors")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])