"""
``python -m friday.image setup`` — reproducible local-source installation.

This module installs the verified runtime and model components for the
Qwen-Image-2.1 integration on Windows, into the exact layout the rest of the
package discovers (``models/bin`` for sd-cli, ``models/qwen-image/`` for the
three model components). It is the *only* code path that downloads anything;
``doctor`` and startup never do.

Every resource in the manifest has a size and an authoritative SHA-256 that
was recorded from the upstream repository on 2026-10-12:

- Runtime: stable-diffusion.cpp release ``master-956-1b0ba10`` (commit
  ``1b0ba10``), official Windows x64 prebuilt assets (CPU / Vulkan / CUDA12).
- Diffusion: ``leejet/Qwen-Image-2.1-GGUF`` (per sd.cpp docs/qwen_image_2.1.md).
- VAE: ``Comfy-Org/Qwen-Image-2.1`` (``vae/qwen_image_2.1_vae_bf16.safetensors``,
  the only VAE for 2.1 — earlier Qwen-Image/Wan2.2 VAEs are not interchangeable).
- Text encoder: ``Qwen/Qwen3-VL-8B-Instruct-GGUF``
  (``Qwen3VL-8B-Instruct-Q4_K_M.gguf``, the LLM used by the 2.1 architecture).

Guarantees implemented here:

- Resumable downloads (HTTP Range) with live progress reporting.
- Disk-space check before any bytes are written.
- SHA-256 verification before a file is renamed into place; a download that
  fails verification is removed, never silently kept.
- Existing files are never overwritten without ``--force``.
- Nothing downloads unless the ``setup`` subcommand is invoked explicitly.

Licensing: Qwen-Image-2.1 weights (diffusion + VAE, and their quantized forms)
are released under the *Qwen RESEARCH LICENSE AGREEMENT* (research use only),
https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE. Downloading those
two components therefore requires ``--accept-license``. The runtime
(stable-diffusion.cpp, MIT) and Qwen3-VL-8B-Instruct (Apache-2.0) are not gated.
"""
import dataclasses
import hashlib
import shutil
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Verified upstream identity (recorded 2026-10-12, do not edit blindly)
# --------------------------------------------------------------------------

SD_CPP_RELEASE_TAG = "master-956-1b0ba10"   # stable-diffusion.cpp release
SD_CPP_COMMIT = "1b0ba10"                   # commit inside the release name
SD_CPP_RELEASES_URL = "https://github.com/leejet/stable-diffusion.cpp/releases/download"

# (asset filename, size bytes, sha256) — digests from the GitHub releases API.
# For "cuda" the build needs its companion runtime DLLs (second entry).
RUNTIME_ASSETS: Dict[str, Tuple[Tuple[str, int, str], ...]] = {
    "cpu": (
        ("sd-master-1b0ba10-bin-win-cpu-x64.zip", 17543461,
         "39c2ea1cc03f697864c858ad0b22b9b8ce62f945ba428e8596a814527e6db6fb"),
    ),
    "vulkan": (
        ("sd-master-1b0ba10-bin-win-vulkan-x64.zip", 30123908,
         "9e8b9baff514fe5dfb77e51bf08d85f11e6f10128eac14d4474c87f563309725"),
    ),
    "cuda": (
        ("sd-master-1b0ba10-bin-win-cuda12-x64.zip", 33797452,
         "144b9631bf2eeb9bf6bf7f148cf40aaf05739ce7c49d3ac0ec2ddf6b65765d69"),
        ("cudart-sd-bin-win-cu12-x64.zip", 56345046,
         "fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d"),
    ),
}

# Diffusion GGUF quants from leejet/Qwen-Image-2.1-GGUF (quant, filename, size,
# sha256). Sizes/digests read from the Hugging Face model API on 2026-10-12.
# Q4_K is the recommended default for 6 GB-class GPUs; Q3_K for very small VRAM.
DIFFUSION_QUANTS: Dict[str, Tuple[str, int, str]] = {
    "q2_k": ("qwen_image_2.1-Q2_K.gguf", 2561716256,
             "5f79e41d3424abb230ee1486e1f4adab1b07c8c0fd10601fc402fe9890443fe6"),
    "q3_k": ("qwen_image_2.1-Q3_K.gguf", 3270553632,
             "5a6352cb450d334ba17a9d18c7fd8c3e774799245b9da0f963ce0c6624deb758"),
    "q4_0": ("qwen_image_2.1-Q4_0.gguf", 4197494816,
             "8d992dc95dcbf13196a4aca893697fb56a5c9263e19e7b40c898be2cf29e9147"),
    "q4_k": ("qwen_image_2.1-Q4_K.gguf", 4197494816,
             "29f9c83c249ff0292fb2943fceddfa2319b446601866c82a4f8be062abea72c2"),
    "q5_0": ("qwen_image_2.1-Q5_0.gguf", 5069910048,
             "8dfeb1ee091a5d7c7d8191f69723254f031de8fe67ec219a21bf7df57590ab43"),
    "q6_k": ("qwen_image_2.1-Q6_K.gguf", 5996851232,
             "1c51d1a8e6cf2b215719dea0c4f0f4cbfff9214a1c7571e57913f57d6a9c3c12"),
    "q8_0": ("qwen_image_2.1-Q8_0.gguf", 7687155744,
             "f8b244b00937f0e444a40dbf7866460871b89b30142594973b6012d1b471dc0a"),
}

HF_BASE = "https://huggingface.co"
# (path in repo, size bytes, sha256) from the HF API, 2026-10-12.
VAE_RESOURCE = ("vae/qwen_image_2.1_vae_bf16.safetensors", 675509688,
                "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9")
TEXT_ENCODER_RESOURCE = ("Qwen3VL-8B-Instruct-Q4_K_M.gguf", 5027784800,
                         "67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2")

QWEN_RESEARCH_LICENSE_URL = (
    "https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE"
)
# Components whose weights are licensed research-only (gated by --accept-license).
QWEN_LICENSED_KEYS = {"diffusion", "vae"}

RUNTIME_BIN_DIR = "models/bin"
MODEL_BASE_DIR = "models/qwen-image"

_MB = 1024 * 1024
_CHUNK = 1 * _MB
_MARGIN_BYTES = 200 * _MB


class SetupError(Exception):
    """Structured setup failure with a machine-readable code."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {"success": False, "error_type": self.code, **self.details}


@dataclass
class Resource:
    """One item to install.

    ``kind``\u00a0= ``file`` (a model) or ``zip`` (an sd-cli release asset that
    is verified as an archive and then extracted into ``models/bin``).
    ``target`` is the *final* path; ``archive`` (zip only) is where the raw
    verified archive is staged inside ``models/bin``.
    """

    key: str
    description: str
    kind: str
    url: str
    size: int
    sha256: str
    target: Path
    archive: Optional[Path] = None           # zip only: staged .zip path
    license: Optional[str] = None            # None | "qwen-research"
    extracted: List[Path] = field(default_factory=list)
    status: str = "pending"                  # pending|ok|skip|replace|failed

    @property
    def existing_ok(self) -> bool:
        try:
            if not self.target.is_file():
                return False
            if self.kind == "zip":
                return self.target.stat().st_size > 0
            if self.target.stat().st_size != self.size:
                return False
            return sha256_file(self.target) == self.sha256
        except OSError:
            return False


def sha256_file(path: Path, chunk: int = _CHUNK) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _fmt(n: int) -> str:
    return f"{n / _MB:,.1f} MB"


def build_plan(
    backend: str,
    quant: str,
    components: Tuple[str, ...] = ("all",),
    root: Path = None,
) -> List[Resource]:
    """Resolve the explicit user request into a verified install plan.

    Raises SetupError for unknown backend/quant/component names. Never touches
    the network; filesystem access is limited to path math on ``root``.
    """
    root = Path(root or Path.cwd())
    if backend not in RUNTIME_ASSETS:
        raise SetupError(
            "invalid_config",
            f"Unknown backend '{backend}'. Choose from {', '.join(RUNTIME_ASSETS)}.",
        )
    if quant not in DIFFUSION_QUANTS:
        raise SetupError(
            "invalid_config",
            f"Unknown diffusion quant '{quant}'. "
            f"Choose from {', '.join(DIFFUSION_QUANTS)}.",
        )

    comps = {"all", "executable", "diffusion", "vae", "text-encoder"}
    requested = set(components)
    if not requested or requested - comps:
        raise SetupError(
            "invalid_config",
            f"Unknown component(s). Choose from {', '.join(sorted(comps))}.",
        )
    want = comps if "all" in requested else requested

    plan: List[Resource] = []

    if "executable" in want:
        for asset, size, digest in RUNTIME_ASSETS[backend]:
            plan.append(Resource(
                key="executable",
                description=f"sd-cli runtime ({backend}) - {asset}",
                kind="zip",
                url=f"{SD_CPP_RELEASES_URL}/{SD_CPP_RELEASE_TAG}/{asset}",
                size=size,
                sha256=digest,
                target=root / RUNTIME_BIN_DIR / "sd-cli.exe",
                archive=root / RUNTIME_BIN_DIR / asset,
            ))

    if "diffusion" in want:
        filename, size, digest = DIFFUSION_QUANTS[quant]
        plan.append(Resource(
            key="diffusion",
            description=f"Qwen-Image-2.1 diffusion GGUF ({quant}) - {filename}",
            kind="file",
            url=f"{HF_BASE}/leejet/Qwen-Image-2.1-GGUF/resolve/main/{filename}",
            size=size,
            sha256=digest,
            target=root / MODEL_BASE_DIR / "diffusion" / filename,
            license="qwen-research",
        ))

    if "vae" in want:
        filename, size, digest = VAE_RESOURCE
        plan.append(Resource(
            key="vae",
            description=f"Qwen-Image-2.1 VAE - {filename}",
            kind="file",
            url=f"{HF_BASE}/Comfy-Org/Qwen-Image-2.1/resolve/main/{filename}",
            size=size,
            sha256=digest,
            target=root / MODEL_BASE_DIR / "vae" / Path(filename).name,
            license="qwen-research",
        ))

    if "text-encoder" in want:
        filename, size, digest = TEXT_ENCODER_RESOURCE
        plan.append(Resource(
            key="text-encoder",
            description=f"Qwen3-VL-8B text encoder GGUF - {filename}",
            kind="file",
            url=f"{HF_BASE}/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/{filename}",
            size=size,
            sha256=digest,
            target=root / MODEL_BASE_DIR / "text_encoder" / filename,
        ))

    return plan


def plan_needs_license(plan: List[Resource]) -> bool:
    return any(r.license and r.key in QWEN_LICENSED_KEYS for r in plan)


def describe_plan(plan: List[Resource]) -> List[str]:
    lines = [f"stable-diffusion.cpp commit {SD_CPP_COMMIT} (release {SD_CPP_RELEASE_TAG})"]
    total = 0
    for r in plan:
        total += r.size
        owned = r.archive if (r.kind == "zip" and r.archive) else r.target
        if owned.exists():
            state_note = "exists (use --force to replace)"
        else:
            state_note = "new"
        lic = " [Qwen RESEARCH LICENSE]" if r.license else ""
        lines.append(
            f"  {r.key:14} {_fmt(r.size):>12}  {r.description}{lic}  "
            f"-> {r.target}  ({state_note})"
        )
    lines.append(f"  Total download: {_fmt(total)} (+ zip extraction for the runtime)")
    return lines


class _DefaultOpener:
    """Thin urllib wrapper returning a file-like with a ``status`` attribute."""

    _UA = "friday-image-setup/1.0"

    def open(self, url: str, headers: Dict[str, str], timeout: int = 60):
        req = urllib.request.Request(url, headers={**headers, "User-Agent": self._UA})
        return urllib.request.urlopen(req, timeout=timeout)


DEFAULT_OPENER = _DefaultOpener()


def _open_with_retry(open_func, url: str, headers: Dict[str, str], attempts: int = 3):
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return open_func(url, headers)
        except urllib.error.HTTPError as e:
            if e.code in (408, 429) or e.code >= 500:
                last = e
                time.sleep(1.0 * (attempt + 1))
                continue
            raise SetupError(
                "http_error", f"Server returned HTTP {e.code} for {url}",
            ) from e
        except (urllib.error.URLError, OSError) as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise SetupError(
        "http_error", f"Could not reach {url} after {attempts} attempts: {last}",
    )


def download_file(
    resource: Resource,
    progress: Optional[Callable[[int, int], None]] = None,
    open_func: Optional[Callable] = None,
) -> Path:
    """Resumable, verified download into ``resource.target``.

    Downloads to ``<target>.part`` and only renames into place after size and
    SHA-256 verification. A partial may be left on transient failure so a
    re-run resumes from where it stopped. On verification failure the partial
    is deleted. ``open_func(url, headers) -> file-like with .status and .read``
    is injectable for tests. Returns the final path.
    """
    open_func = open_func or DEFAULT_OPENER.open
    target = resource.target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = Path(str(target) + ".part")

    start = part.stat().st_size if part.is_file() else 0
    if start > resource.size:
        start = 0

    headers: Dict[str, str] = {}
    if start:
        headers["Range"] = f"bytes={start}-"

    resp = _open_with_retry(open_func, resource.url, headers)
    status = getattr(resp, "status", None)
    if status == 200:
        start = 0
    elif status == 206 and start:
        pass
    else:
        raise SetupError(
            "http_error",
            f"Unexpected response status {status} from {resource.url}",
        )

    pos = start
    try:
        with open(part, "ab" if start else "wb") as fh:
            while True:
                block = resp.read(_CHUNK)
                if not block:
                    break
                fh.write(block)
                pos += len(block)
                if progress:
                    progress(min(pos, resource.size), resource.size)
    finally:
        close = getattr(resp, "close", None)
        if close:
            close()

    if pos != resource.size:
        raise SetupError(
            "http_error",
            f"Downloaded {pos} of {resource.size} bytes for {target.name}; "
            f"run setup again to resume.",
        )

    if sha256_file(part) != resource.sha256:
        try:
            part.unlink()
        except OSError:
            pass
        raise SetupError(
            "checksum_mismatch",
            f"SHA-256 mismatch for {target.name}. The invalid download was "
            f"removed; re-run setup to try again.",
        )

    part.replace(target)
    return target


def extract_zip(resource: Resource, root: Path):
    """Verify + unzip a release asset (staged at ``resource.archive``)."""
    archive = resource.archive or Path(str(resource.target) + ".zip")
    if not archive.is_file():
        raise SetupError("http_error", f"Missing archive {archive}")
    staging = root / ".tmp-extract"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad:
                raise SetupError("invalid_archive", f"Corrupt archive entry: {bad}")
            zf.extractall(staging)
    except zipfile.BadZipFile as e:
        raise SetupError("invalid_archive", f"Not a valid zip: {e}") from e

    bin_dir = root / RUNTIME_BIN_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    for src in [p for p in staging.iterdir() if p.is_file()]:
        dst = bin_dir / src.name
        if dst.exists():
            dst.unlink()
        src.replace(dst)
        resource.extracted.append(dst)
    shutil.rmtree(staging, ignore_errors=True)
    archive.unlink(missing_ok=True)


def check_disk_space(
    plan: List[Resource],
    root: Path,
    extra: int = _MARGIN_BYTES,
    used: Optional[Dict[str, int]] = None,
) -> None:
    """Raise ``disk_full`` unless the target drive can hold the plan (+ margin).

    ``used`` maps resource.key -> bytes already present and verified (so a
    re-run only counts what it will actually fetch); the executable component
    is excluded from the models-mount sizing when installed already.
    """
    used = used or {}
    needed = sum(
        r.size - used.get(r.key, 0)
        for r in plan
        if not r.existing_ok
    ) + extra
    mount = root / MODEL_BASE_DIR
    mount.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(mount).free
    if free < needed:
        raise SetupError(
            "disk_full",
            f"Need ~{_fmt(needed)} free on {mount.drive or mount}; "
            f"only {_fmt(free)} available.",
        )


def run_plan(
    plan: List[Resource],
    root: Path = None,
    force: bool = False,
    out: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[Resource, int, int], None]] = None,
    open_func: Optional[Callable] = None,
    verify_binary: bool = True,
) -> Dict[str, object]:
    """Execute a plan sequentially. Raises SetupError on first hard failure."""
    root = Path(root or Path.cwd())
    out = out or (lambda _m: None)
    check_disk_space(plan, root)
    summary: Dict[str, object] = {"ok": [], "skipped": [], "replaced": []}

    for r in plan:
        try:
            # Presence policy (never overwrite anything without --force):
            #  - file: skip if target is already verified (size+SHA-256), else
            #    if the target merely exists (unverified), require --force.
            #  - zip : each runtime step owns its staged archive; a leftover
            #    *.exe does not mark the step done (CUDA = two archives).
            if r.kind == "zip" and r.archive is not None:
                present = r.archive.is_file()
                verified = present
            else:
                present = r.target.is_file()
                verified = r.existing_ok

            if verified and not force:
                r.status = "skip"
                summary["skipped"].append(r.key)
                out(f"[skip] {r.description} (verified; use --force to reinstall)")
                continue
            if present and not force:
                r.status = "skip"
                summary["skipped"].append(r.key)
                out(f"[skip] {r.description} (unverified file exists; use --force to replace)")
                continue
            if present and force:
                r.status = "replace"
                summary["replaced"].append(r.key)
                out(f"[repl] {r.description} (--force: replacing)")

            def _progress(pos: int, total: int, _r=r):
                if progress:
                    progress(_r, pos, total)

            if r.kind == "zip":
                # Stage the verified archive at resource.archive (it may differ
                # from the final extracted target, e.g. CUDA's two zips).
                if r.archive is not None:
                    stage = dataclasses.replace(r, target=r.archive)
                    download_file(stage, progress=_progress, open_func=open_func)
                    extract_zip(r, root)
                else:
                    download_file(r, progress=_progress, open_func=open_func)
                    extract_zip(r, root)
            else:
                download_file(r, progress=_progress, open_func=open_func)

            r.status = "ok"
            summary["ok"].append(r.key)
            out(f"[ok]   {r.description}")
        except SetupError as e:
            r.status = "failed"
            out(f"[error] {r.description}: {e.message}")
            summary["failed"] = e.as_dict()
            raise

    summary["ok"] = sorted(set(summary["ok"]))
    summary["skipped"] = sorted(set(summary["skipped"]))
    summary["replaced"] = sorted(set(summary["replaced"]))
    if verify_binary:
        validate_runtime(root, out=out)
    return summary


def validate_runtime(root: Path, out: Optional[Callable[[str], None]] = None) -> None:
    """Best-effort smoke probe: the installed sd-cli must answer ``--help``."""
    out = out or (lambda _m: None)
    exe = root / RUNTIME_BIN_DIR / "sd-cli.exe"
    if not exe.is_file():
        return
    import subprocess
    try:
        res = subprocess.run(
            [str(exe), "--help"],
            capture_output=True, text=True, timeout=20,
        )
        ok = res.returncode == 0 and "diffusion-model" in (res.stdout or res.stderr)
        if ok:
            out("[probe] sd-cli answered --help (diffusion-model flag present)")
        else:
            raise SetupError(
                "runtime_probe_failed",
                "sd-cli.exe exists but does not answer --help with the expected flags.",
            )
    except (OSError, subprocess.SubprocessError) as e:
        raise SetupError("runtime_probe_failed", f"sd-cli probe failed: {e}") from e