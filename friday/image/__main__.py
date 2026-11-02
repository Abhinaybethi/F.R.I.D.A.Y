"""
``python -m friday.image`` — CLI for the Qwen-Image subsystem.

Subcommands:
  doctor     - print health snapshot (no inference, no downloads)
  setup      - download verified runtime + model components (explicit only)
  generate   - run one txt2img generation
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

from friday.image.manager import QwenImageManager
from friday.image.setup import (
    DIFFUSION_QUANTS,
    RUNTIME_ASSETS,
    SetupError,
    build_plan,
    describe_plan,
    plan_needs_license,
    run_plan,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m friday.image",
        description="Local Qwen-Image GGUF generation via stable-diffusion.cpp.",
    )
    parser.add_argument(
        "sub",
        choices=("doctor", "setup", "generate"),
        nargs="?",
        default="doctor",
        help="doctor: health snapshot; setup: download components (explicit only); "
             "generate: run one generation.",
    )
    parser.add_argument("--prompt", "-p", default="", help="Prompt for 'generate'.")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None, help="Deterministic seed (>=0).")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Print result as JSON.")
    g = parser.add_argument_group("setup")
    g.add_argument(
        "--backend", choices=tuple(RUNTIME_ASSETS), default="cpu",
        help="sd-cli runtime build to install (default: cpu).",
    )
    g.add_argument(
        "--diffusion-quant", choices=tuple(DIFFUSION_QUANTS), default="q4_k",
        help="Diffusion GGUF quantization (default: q4_k, recommended for 6 GB VRAM).",
    )
    g.add_argument(
        "--components", default="all",
        help="Comma-separated: all,executable,diffusion,vae,text-encoder.",
    )
    g.add_argument(
        "--force", action="store_true",
        help="Overwrite existing files instead of skipping them.",
    )
    g.add_argument(
        "--accept-license", action="store_true",
        help="Accept the Qwen RESEARCH LICENSE for the Qwen-Image-2.1 weights "
             "(diffusion + VAE; required to download them).",
    )
    g.add_argument(
        "--dry-run", action="store_true",
        help="Print the install plan (sizes, URLs, licensing) without downloading.",
    )
    return parser


def _print_json(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _cmd_doctor(args: argparse.Namespace, manager: QwenImageManager) -> int:
    health = manager.health()
    if args.as_json:
        _print_json(health)
        return 0
    print("Qwen image generation - health")
    for key in ("provider", "backend", "state", "installed", "configured",
                "loaded", "ready", "device", "executable", "model_path",
                "text_encoder_path", "vae_path", "gpu_name", "vram_total_mb",
                "keep_loaded"):
        print(f"  {key:18} {health.get(key) if health.get(key) not in (None, '') else '(none)'}")
    if not health.get("installed"):
        print("\n  stable-diffusion.cpp (sd-cli) was not found. Install it and set")
        print("  FRIDAY_QWEN_SD_EXECUTABLE if it is not on PATH.")
        print("  One command installs a verified build into models/bin/ and")
        print("  downloads the model components:  python -m friday.image setup")
    if not health.get("configured"):
        print("\n  Qwen image components missing. Place them under models/qwen-image/")
        print("  (diffusion/*.gguf, text_encoder/*.gguf, vae/*.safetensors) or set the")
        print("  FRIDAY_QWEN_*_PATH environment variables.")
        print("  Or run:  python -m friday.image setup")
    return 0


def _cmd_setup(args: argparse.Namespace, manager: QwenImageManager) -> int:
    from friday.image.setup import QWEN_RESEARCH_LICENSE_URL

    components = tuple(c.strip() for c in args.components.split(",") if c.strip())
    try:
        plan = build_plan(
            backend=args.backend,
            quant=args.diffusion_quant,
            components=components,
            root=_PROJECT_ROOT,
        )
    except SetupError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return (2 if e.code == "invalid_config" else 1)

    needs_license = plan_needs_license(plan)
    for line in describe_plan(plan):
        print(line)
    if needs_license:
        print()
        print("  The Qwen-Image-2.1 model weights (diffusion + VAE) are released under")
        print(f"  the Qwen RESEARCH LICENSE AGREEMENT (research use only):")
        print(f"    {QWEN_RESEARCH_LICENSE_URL}")
        print("  Pass --accept-license to confirm you may use them for research.")

    if args.dry_run:
        return 0
    if needs_license and not args.accept_license:
        print("error: --accept-license is required to download the Qwen-Image-2.1 weights.",
              file=sys.stderr)
        return 2

    def out(msg: str) -> None:
        print(msg)

    def progress(res, pos: int, total: int) -> None:
        _last = getattr(progress, "_last", -1.0)
        if pos < total and pos - _last < 4 * 1024 * 1024:
            return
        progress._last = pos
        _pct = 100.0 * pos / total if total else 0.0
        print(
            f"\r[{res.key:14}] {pos / (1024 * 1024):8.1f} / "
            f"{total / (1024 * 1024):8.1f} MB  ({_pct:5.1f}%)",
            end="", file=sys.stderr, flush=True,
        )
        if pos >= total:
            print(file=sys.stderr)

    t0 = time.perf_counter()
    try:
        summary = run_plan(
            plan,
            root=_PROJECT_ROOT,
            force=args.force,
            out=out,
            progress=progress,
        )
    except SetupError as e:
        print(f"\nerror: {e.message}", file=sys.stderr)
        if e.code == "http_error":
            print("  Re-run the same command to resume from where it stopped.",
                  file=sys.stderr)
        if args.as_json:
            _print_json(e.as_dict())
        return 1

    elapsed = time.perf_counter() - t0
    print(f"setup finished in {elapsed:.1f}s.", file=sys.stderr)
    if args.as_json:
        _print_json({
            "success": True,
            "backend": args.backend,
            "diffusion_quant": args.diffusion_quant,
            "ok": summary["ok"],
            "skipped": summary["skipped"],
            "replaced": summary["replaced"],
            "install_root": str(_PROJECT_ROOT),
            "elapsed_s": round(elapsed, 1),
        })
    else:
        if summary["ok"]:
            print(f"Installed: {', '.join(summary['ok'])}")
        if summary["skipped"]:
            print(f"Skipped (already present or needs --force): {', '.join(summary['skipped'])}")
    return 0


def _cmd_generate(args: argparse.Namespace, manager: QwenImageManager) -> int:
    if not args.prompt.strip():
        print("error: --prompt is required for 'generate'", file=sys.stderr)
        return 2
    result = manager.generate(
        prompt=args.prompt,
        width=args.width,
        height=args.height,
        steps=args.steps,
        seed=args.seed,
    )
    if args.as_json:
        _print_json(result.to_dict())
        return 0 if result.success else 1
    if result.success:
        print(result.message)
        print(f"  path: {result.path}")
        print(f"  prompt: {result.prompt}")
        print(f"  {result.width}x{result.height}  steps={result.steps}  seed={result.seed}")
        print(f"  device: {result.device}  elapsed: {result.elapsed_ms:.0f} ms")
        return 0
    print(f"error: {result.message}", file=sys.stderr)
    if result.error_type:
        print(f"  type: {result.error_type}", file=sys.stderr)
    if result.detail.get("tail"):
        tail = " | ".join(str(t) for t in result.detail["tail"])
        print(f"  stderr tail: {tail}", file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    manager = QwenImageManager()
    if args.sub == "doctor":
        return _cmd_doctor(args, manager)
    if args.sub == "setup":
        return _cmd_setup(args, manager)
    return _cmd_generate(args, manager)


if __name__ == "__main__":
    sys.exit(main())