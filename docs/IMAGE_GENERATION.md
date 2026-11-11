# Local Qwen-Image Generation

F.R.I.D.A.Y. can generate images entirely locally with
[Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) GGUF weights driven
by [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)
(`sd-cli`).

This page covers:

1. What works today (honest status)
2. Hardware expectations
3. Install the runtime + models (one command, verified, resumable)
4. Doctor — verify everything before the first real run
5. Usage (`python -m friday.image`, voice, tool contract)
6. Outputs and metadata
7. Configuration reference
8. Troubleshooting

---

## 1. Status — what is implemented

| Capability | Status |
| --- | --- |
| Router: "generate / create / make an image of X", "draw X", "search for an image of X" | Done, deterministic (no reasoner round-trip) |
| Permission gate: `tools.permissions.generate_image` (default `true`) | Done |
| Lazy load — nothing loads at assistant startup | Done |
| `python -m friday.image doctor` health snapshot | Done |
| `python -m friday.image setup` — verified, resumable installer | Done |
| `python -m friday.image generate --prompt "..."` CLI | Done |
| Real txt2img inference via stable-diffusion.cpp (`sd-cli`) | Done (after §3) |
| Output to `output/generated_images/YYYY-MM-DD/image_NNN.png` + `.json` sidecar | Done |
| Voice progress phrases and structured errors | Done |
| Persistent resident server (`sd-server` keep-loaded mode) | **Not implemented** — the CLI (`sd-cli`) backend launches one process per generation, which guarantees the model is genuinely released after each request. `keep_loaded` currently governs whether the manager retains its ready (preflight) state between requests. |

### What is NOT done (honest)

- **Nothing downloads at startup or in `doctor`.** Downloads happen only when
  you run `python -m friday.image setup` (or a missing file is reported with a
  pointer to that command).
- Persistent server mode (§ above).
- UI overlay — text/voice output only (see README §Overlay note).

## 2. Hardware expectations

Qwen-Image at 1024×1024 is a diffusion transformer. On this machine the verified
GPU path is **Vulkan** (the prebuilt CUDA binary is blocked by the driver/GPU
combination — see §8):

- **6 GB VRAM (e.g. RTX 3050 6GB Laptop):** use the **Q4_K** diffusion GGUF
  (≈4.0 GB), keep the low-VRAM flags enabled (`--vae-tiling`,
  `--diffusion-fa`, `--offload-to-cpu`) — the defaults in `config.yaml`. A
  full 1024×1024 run with this stack has not been benchmarked on 6 GB yet.
- **8 GB and up:** Q8_0 (≈7.7 GB) fits with offload-to-cpu; 12 GB+ can disable
  `offload_to_cpu`.
- **CPU only:** works but very slow for 1024×1024. Acceptable for a first
  smoke test; add a `--backend "diffusion=cpu,vae=cpu,llm=cpu"` extra if needed.

`doctor` reports the detected GPU and VRAM if `nvidia-smi` is available.

## 3. Install the runtime + models (automated, verified)

> The Qwen-Image-2.1 model weights (**diffusion + VAE**) are released under the
> **Qwen RESEARCH LICENSE AGREEMENT** (research use only). The installer prints
> the license and requires `--accept-license` before downloading those two
> components. The text encoder (Qwen3-VL-8B) is Apache-2.0; `sd-cli` is MIT.

Install everything with one command (points at
stable-diffusion.cpp `1b0ba10`, release `master-956-1b0ba10`):

```powershell
python -m friday.image setup --backend vulkan --accept-license
```

What it does:

- Resumes interrupted downloads (HTTP `Range`, `.part` files kept on transient
  failure).
- Verifies every SHA-256 before a file is renamed into place; an invalid
  download is deleted and reported.
- Checks free disk space (download + 200 MB margin) before writing.
- Never overwrites an existing file without `--force`.
- Downloads nothing at startup/doctor — only on explicit `setup`.

Other options:

```powershell
python -m friday.image setup --dry-run                 # plan + sizes, no download
python -m friday.image setup --backend cpu             # CPU-only build
python -m friday.image setup --backend cuda            # CUDA build (+ CUDA 12.x runtime DLLs)
python -m friday.image setup --diffusion-quant q4_k    # q2_k|q3_k|q4_0|q4_k|q5_0|q6_k|q8_0
python -m friday.image setup --components text-encoder # install a subset
python -m friday.image setup --force                   # re-download and replace
```

Default download ≈ **9.5 GB** (Q4_K). Resulting layout:

```
models/bin/                                  # sd-cli.exe + DLLs (runtime)
  sd-cli.exe
  ggml-vulkan.dll, ggml-cpu.dll, ggml.dll, stable-diffusion.dll, …
models/qwen-image/
  diffusion/qwen_image_2.1-Q4_K.gguf         # Qwen-Image-2.1 diffusion GGUF
  text_encoder/Qwen3VL-8B-Instruct-Q4_K_M.gguf  # Qwen3-VL-8B text encoder
  vae/qwen_image_2.1_vae_bf16.safetensors    # Qwen-Image-2.1 VAE (version-specific)
```

### Verified sources (recorded 2026-10-12)

| Component | Source | File | Size | SHA-256 (verified) |
| --- | --- | --- | --- | --- |
| Diffusion (q4_k) | `leejet/Qwen-Image-2.1-GGUF` | `qwen_image_2.1-Q4_K.gguf` | 4,197,494,816 | `29f9c83c249ff0292fb2943fceddfa2319b446601866c82a4f8be062abea72c2` |
| VAE | `Comfy-Org/Qwen-Image-2.1` | `vae/qwen_image_2.1_vae_bf16.safetensors` | 675,509,688 | `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9` |
| Text encoder | `Qwen/Qwen3-VL-8B-Instruct-GGUF` | `Qwen3VL-8B-Instruct-Q4_K_M.gguf` | 5,027,784,800 | `67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2` |
| Runtime (vulkan) | sd.cpp release `master-956-1b0ba10` | `sd-master-1b0ba10-bin-win-vulkan-x64.zip` | 30,123,908 | `9e8b9baff514fe5dfb77e51bf08d85f11e6f10128eac14d4474c87f563309725` |
| Runtime (cpu) | " | `sd-master-1b0ba10-bin-win-cpu-x64.zip` | 17,543,461 | `39c2ea1cc03f697864c858ad0b22b9b8ce62f945ba428e8596a814527e6db6fb` |
| Runtime (cuda) | " | `sd-master-1b0ba10-bin-win-cuda12-x64.zip` | 33,797,452 | `144b9631bf2eeb9bf6bf7f148cf40aaf05739ce7c49d3ac0ec2ddf6b65765d69` |
| CUDA 12 runtime DLLs | " | `cudart-sd-bin-win-cu12-x64.zip` | 56,345,046 | `fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d` |

Keyed by exact stable-diffusion.cpp commit `1b0ba10` (release
`master-956-1b0ba10`, published 2026-10-10) which added Day-0 Qwen-Image-2.1
support (see `docs/qwen_image_2.1.md` in the sd.cpp repo). The Qwen-Image-2.1
stack uses its **own VAE** (`qwen_image_2.1_vae_bf16.safetensors`) and the
**Qwen3-VL-8B-Instruct** text encoder — these are not interchangeable with the
Qwen-Image 2.0 components.

## 4. Doctor — verify everything before the first real run

```powershell
python -m friday.image doctor
```

Sample (with everything installed):

```
Qwen image generation — health
  provider          qwen-image
  backend           stable-diffusion.cpp (sd-cli)
  installed         True
  configured        True
  loaded            False
  ready             True
  device            auto
  model_path        models/qwen-image/diffusion/qwen_image_2.1-Q4_K.gguf
  ...
```

Any `installed`/`configured` false is reported explicitly with the fix
hint (pointing at `python -m friday.image setup`).

## 5. Usage

### CLI

```powershell
python -m friday.image generate --prompt "a watercolor of a lighthouse at dusk"
python -m friday.image generate --prompt "an oil painting of a cat astronaut" --width 768 --height 768 --seed 42 --json
```

### Voice / text assistant

Say (or type) any of:

- "generate an image of a sunset"
- "make a picture of a cat"
- "draw a dragon"
- "search for an image of the Eiffel Tower"
- "show me a photo of the ocean"

The router maps these deterministically to the image tool (they do **not** go
through the reasoning model). With real execution enabled the assistant first
says *"Generating the image now."*, then *"Done. I've generated the image."*
and (text mode) prints the saved path. In dry-run mode it announces what it
*would* have done.

### Structured tool result

On success the tool result exposes `event: "image_generated"` plus a
self-describing `metadata` payload and the saved `path`. Failures are
structured errors (`error_type`, clean message, no tracebacks).

## 6. Outputs and metadata

- Save location: `output/generated_images/YYYY-MM-DD/image_001.png`
- Filenames are allocated to **never overwrite**: `image_002`, `image_003`, …
- Every image has a sibling `image_001.json` sidecar with prompt, dimensions,
  steps, seed, device, backend, request id, and elapsed time.

## 7. Configuration reference

All settings come from the `image:` block in `config.yaml`; every value is
overridable with a `FRIDAY_*` env var:

| Key | Env override | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | `FRIDAY_IMAGE_ENABLED` | `true` | kill switch |
| `provider` | `FRIDAY_IMAGE_PROVIDER` | `qwen-image` | |
| `executable` | `FRIDAY_QWEN_SD_EXECUTABLE` | `sd-cli` | also searched as `sd`, `models/bin/sd-cli` (`+ .exe` on Windows) |
| `model_path` | `FRIDAY_QWEN_IMAGE_MODEL_PATH` | empty → discovery | `models/qwen-image/diffusion/*.gguf` |
| `text_encoder_path` | `FRIDAY_QWEN_TEXT_ENCODER_PATH` | empty → discovery | `models/qwen-image/text_encoder/*.{gguf,safetensors}` |
| `vae_path` | `FRIDAY_QWEN_VAE_PATH` | empty → discovery | `models/qwen-image/vae/*.{safetensors,gguf}` |
| `output_dir` | `FRIDAY_QWEN_OUTPUT_DIR` | `output/generated_images` | |
| `device` | `FRIDAY_QWEN_DEVICE` | `auto` | `auto` \| `cuda` \| `cpu`; explicit `cuda` with no usable GPU fails loudly |
| `text_encoder_device` | `FRIDAY_QWEN_TEXT_ENCODER_DEVICE` | `auto` | `auto` \| `cpu` \| `gpu`; keeps the ~4.3 GB text encoder off small GPUs (see §8) |
| `keep_loaded` | `FRIDAY_QWEN_KEEP_LOADED` | `true` | retains ready/preflight state between requests (CLI backend) |
| `prompt_enhancement` | `FRIDAY_QWEN_PROMPT_ENHANCEMENT` | `false` | optional prompt augmentation |
| `width` / `height` | `FRIDAY_QWEN_WIDTH/HEIGHT` | `768` | 64–2048; each doubling ≈ 4× slower |
| `steps` | `FRIDAY_QWEN_STEPS` | `8` | 1–50 |
| `cfg_scale` | `FRIDAY_QWEN_CFG_SCALE` | `2.5` | 1–20 |
| `sampling_method` | — | `euler` | |
| `flow_shift` | — | `3.0` | Qwen-Image recommended |
| `vae_tiling` | — | `true` | low-VRAM |
| `diffusion_fa` | — | `true` | flash attention |
| `offload_to_cpu` | — | `true` | low-VRAM |
| `free_vram_before_generate` | `FRIDAY_QWEN_FREE_VRAM` | `true` | stop F.R.I.D.A.Y.'s own reasoner server for the duration of a generation (see below) |
| `extra_args` | `FRIDAY_QWEN_EXTRA_ARGS` | `""` | extra tokens appended to every `sd-cli` run (see below) |
| `timeout` | `FRIDAY_QWEN_TIMEOUT` | `900` | seconds, generation cap. On a 6 GB GPU with the text encoder on CPU, 768² @ 8 steps takes ~5 min; raise this (and/or lower `width`/`steps`) for larger runs |

### Freeing VRAM before generation

Image speed is dominated by **free VRAM**, not resolution or step count: when
~5 GB is free `sd-cli` keeps the ~4 GB diffusion model GPU-resident, but when
only ~1.8 GB is free it streams the weights from system RAM every step and the
same image takes roughly **twice as long**.

The biggest controllable consumer is F.R.I.D.A.Y.'s own llama.cpp reasoner
(`reasoning.server.auto_start`). With `free_vram_before_generate: true` the
assistant registers a release hook (`friday/image/gpu_hooks.py`); before each
generation the image manager stops the reasoner server F.R.I.D.A.Y. started and
restarts it afterwards. Background apps such as a browser or Ollama keep their
VRAM — the manager logs a warning naming them so you can close them for the
fastest runs. Set it to `false` to keep the reasoner resident (slower, but no
server restart).


| `timeout` | `FRIDAY_QWEN_TIMEOUT` | `900` | seconds, generation cap. On a 6 GB GPU with the text encoder on CPU, 768² @ 8 steps takes ~5 min; raise this (and/or lower `width`/`steps`) for larger runs |

### Text-encoder placement

Qwen-Image-2.1's text encoder is Qwen3-VL-8B (~4.3 GB). `sd-cli` stages it onto
the compute GPU, so on a 6 GB GPU (or one shared with other GPU apps) it leaves
no room for the encoder's compute workspace and `sd-cli` aborts the run with
`qwen3vl ... failed during workspace capacity check` → `generate_failed`.

`text_encoder_device` controls this: `auto` (default) sends `--backend llm=cpu`
when the resolved device is CUDA with **< 10 GB VRAM**, keeping the encoder in
host RAM while diffusion/VAE stay on the GPU; `cpu` forces it; `gpu` leaves the
choice to `sd-cli`'s auto-fit. An explicit `--backend` in `extra_args` overrides
this entirely.

### `extra_args`

Arbitrary extra tokens appended to the `sd-cli` command line (shell-split), for
cases the named settings don't cover. Overrides `text_encoder_device` when it
contains `--backend`, e.g. pin a specific GPU explicitly:

```powershell
$env:FRIDAY_QWEN_EXTRA_ARGS='--backend "diffusion=vulkan1,vae=vulkan1,llm=cpu"'
```

Low-VRAM prefix-cache tuning for Qwen-Image-2.1 (see the sd.cpp 2.1 doc):

```yaml
extra_args: "--model-args qwen_image_2_1_prefix_cache_type=q4_0"
```

## 8. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `executable_not_found` | Run `python -m friday.image setup --backend <cpu\|vulkan\|cuda>` (installs to `models/bin`), or set `FRIDAY_QWEN_SD_EXECUTABLE` |
| `component_missing` | Run `python -m friday.image setup` or `--components <vae\|text-encoder\|diffusion>` — `doctor` prints exactly which folder is empty |
| `device_unavailable` | `FRIDAY_QWEN_DEVICE=cuda` with no usable CUDA device. Set `auto`/`cpu` |
| CUDA build: `ggml_cuda_init: failed to initialize CUDA: device kernel image is invalid` | This prebuilt CUDA binary is incompatible with *this* GPU/driver pair (observed on an RTX 3050 6GB with driver 537.53). Switch to the Vulkan build: `python -m friday.image setup --backend vulkan` (a stock CUDA build on the exact driver it was compiled for is unaffected) |
| Wrong GPU picked under Vulkan | Laptops expose `vulkan0` (Intel iGPU) and `vulkan1` (NVIDIA dGPU). Pin: `FRIDAY_QWEN_EXTRA_ARGS='--backend "diffusion=vulkan1,vae=vulkan1,llm=cpu"'` |
| `generation_failed` with `qwen3vl ... workspace capacity check` on a 6 GB GPU | The ~4.3 GB text encoder + its workspace don't fit. `text_encoder_device: auto` (default) already keeps it on CPU for CUDA VRAM < 10 GB; force `cpu` if a large GPU is still shared. Free GPU memory held by other apps if needed |
| `invalid_output` (no valid PNG) | Backend crashed mid-write; check `output/generated_images/...` for a partial file (auto-cleaned) and re-run with `timeout` raised |
| Very slow / OOM on 6 GB | Free VRAM first: keep `free_vram_before_generate` on and close other GPU apps (the manager logs their names). Also use a Q4_K quant; keep `offload_to_cpu`, `vae_tiling`, `diffusion_fa` on; add `--model-args qwen_image_2_1_prefix_cache_type=q4_0` for the 2.1 text encoder |
| `timeout` | Qwen-Image on CPU at 1024² is slow; raise `FRIDAY_QWEN_TIMEOUT` or drop width/height |
| `setup` interrupted | Re-run the same command — downloads resume from `.part` |

> **Qwen-Image on llama.cpp:** not supported. The llama.cpp text/vl server's
> image flags are vision (VLM **ingest**) only — it cannot run the Qwen-Image
> diffusion *generator*. That is why stable-diffusion.cpp is the runtime.