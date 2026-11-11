"""Dashboard runtime: the single bridge between the web API and real services.

The runtime is deliberately lazy. Importing or starting the web app never loads
models or spawns an inference server; the assistant is constructed on the first
chat/voice request, image generation on the first image request, and research on
the first research request. Health, metrics, models, tools, and agents are
derived from configuration and live probes, never from sample data.
"""
import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from friday.utils.config_validator import validate_config
from friday.utils.logger import get_logger
from friday.voice.audio_hub import get_audio_hub
from friday.web.activity import (
    KIND_CHAT,
    KIND_IMAGE,
    KIND_RESEARCH,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    ActivityStore,
)
from friday.web.events import bus, make_event
from friday.web.metrics import prime_cpu, system_metrics

DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_ACTIVITY_PATH = "data/dashboard/activity.json"

logger = get_logger(__name__)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _truncate(text: str, limit: int = 120) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _http_probe(
    url: str,
    timeout: float = 2.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET", headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(65536).decode("utf-8", "replace")
            status = getattr(response, "status", 200)
        parsed: Any = body
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            pass
        return {"reachable": 200 <= status < 400, "status": status, "body": parsed}
    except urllib.error.HTTPError as exc:
        return {"reachable": False, "status": exc.code, "body": None, "error": str(exc)}
    except Exception as exc:
        return {"reachable": False, "status": None, "body": None, "error": str(exc)}


def _quantization_hint(name: str) -> str:
    for token in ("Q8_0", "Q6_K", "Q5_K_M", "Q5_K_S", "Q4_K_M", "Q4_K_S", "Q4_0", "Q3_K_M", "Q2_K", "IQ4_XS", "IQ2"):
        if token.lower() in (name or "").lower():
            return token
    return ""


class DashboardRuntime:
    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        activity_path: str = DEFAULT_ACTIVITY_PATH,
    ) -> None:
        self.config_path = config_path
        self.activity = ActivityStore(activity_path)
        self.started_at = time.time()
        self.prime_metrics()
        self._lock = threading.RLock()
        self._chat_lock = threading.Lock()
        self._assistant = None
        self._assistant_error = ""
        self._stt = None
        self._stt_error = ""
        self._tts = None
        self._tts_error = ""
        self._capture_lock = threading.Lock()
        self._capture_stream = None
        self._capture_token: Optional[int] = None
        self._capture_chunks: List[Any] = []
        self._capture_started = 0.0
        self._handsfree = None
        self._handsfree_lock = threading.Lock()
        self._handsfree_error = ""
        self._handsfree_heard = ""
        self._handsfree_ack_index = 0
        self._image_manager = None
        self._research_agent = None
        self._memory_service = None
        self.state = "starting"
        self.raw_config: Dict[str, Any] = {}
        self.config: Dict[str, Any] = {}
        self.warnings: List[str] = []
        self.reload_config()
        self.state = "ready"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def reload_config(self) -> None:
        raw: Dict[str, Any] = {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        except Exception as exc:
            self.warnings = [f"Config could not be loaded: {exc}"]
        try:
            valid, cfg, warnings = validate_config(raw)
        except Exception as exc:
            valid, cfg, warnings = False, raw, [f"Config validation failed: {exc}"]
        self.raw_config = raw
        self.config = cfg
        self.warnings = list(warnings or [])
        self.state = "ready" if valid else "degraded"

    @staticmethod
    def prime_metrics() -> None:
        prime_cpu()

    def identity(self) -> Dict[str, Any]:
        from friday import __version__

        return {
            "name": "F.R.I.D.A.Y",
            "version": __version__,
            "platform": sys.platform,
            "uptime_seconds": int(time.time() - self.started_at),
        }

    def reasoning_config(self) -> Dict[str, Any]:
        """Effective reasoning settings (env > config.yaml, secrets excluded)."""
        cfg = dict(self.config.get("reasoning", {}) or {})
        env_provider = os.environ.get("FRIDAY_REASONING_PROVIDER", "").strip().lower()
        if env_provider:
            cfg["provider"] = env_provider
        if str(cfg.get("provider", "llamacpp")).lower() == "nvidia":
            # Env vars override config.yaml for model/base URL, matching the
            # provider itself. The API key is never exposed here.
            try:
                from friday.reasoning.nvidia_reasoner import resolve_settings

                nvidia_cfg = dict(cfg.get("nvidia", {}) or {})
                settings = resolve_settings(nvidia_cfg)
                cfg["model"] = settings["model"]
                cfg["base_url"] = settings["base_url"]
                cfg["endpoint"] = settings["base_url"]
                cfg["timeout"] = nvidia_cfg.get(
                    "timeout", cfg.get("timeout", 30)
                )
                cfg["fallback_to_local"] = bool(
                    nvidia_cfg.get("fallback_to_local", True)
                )
            except Exception as exc:  # keep the dashboard alive
                logger.debug("[DASHBOARD] NVIDIA settings unavailable: %s", exc)
        return cfg

    def tools_config(self) -> Dict[str, Any]:
        return self.config.get("tools", {}) or {}

    # ------------------------------------------------------------------
    # Lazy service construction
    # ------------------------------------------------------------------
    def ensure_assistant(self):
        with self._lock:
            if self._assistant is not None:
                return self._assistant
            if self._assistant_error:
                raise RuntimeError(self._assistant_error)
            try:
                from friday.core.assistant import Friday

                self._assistant = Friday(
                    config_path=self.config_path,
                    text_mode=True,
                    memory_service=self.memory_service(),
                    source="chat",
                )
                self.state = "ready"
                return self._assistant
            except Exception as exc:
                self._assistant_error = str(exc)
                self.state = "degraded"
                raise

    def memory_service(self):
        """Process-wide persistent memory service (also exposed to the API)."""
        with self._lock:
            if self._memory_service is None:
                from friday.memory import MemoryService

                self._memory_service = MemoryService.from_config(
                    self.config.get("memory", {}) or {}, source="chat"
                )
            return self._memory_service

    def assistant_state(self) -> Dict[str, Any]:
        assistant = self._assistant
        if assistant is None:
            return {
                "initialized": False,
                "state": "IDLE",
                "error": self._assistant_error,
                "ready": bool(self.config),
            }
        try:
            state = assistant.conversation_manager.state.name
        except Exception:
            state = "UNKNOWN"
        return {"initialized": True, "state": state, "error": "", "ready": True}

    def image_manager(self):
        with self._lock:
            if self._image_manager is None:
                from friday.image.config import QwenImageConfig
                from friday.image.manager import QwenImageManager

                self._image_manager = QwenImageManager(
                    config=QwenImageConfig.load(self.config_path)
                )
            return self._image_manager

    def research_agent(self):
        with self._lock:
            if self._research_agent is None:
                from friday.research.agent import ResearchAgent

                self._research_agent = ResearchAgent()
            return self._research_agent

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def _reasoning_health(self) -> Dict[str, Any]:
        rcfg = self.reasoning_config()
        provider = str(rcfg.get("provider", "llamacpp")).lower()
        endpoint = str(rcfg.get("endpoint", "") or "").rstrip("/")
        if provider == "ollama":
            base = endpoint.split("/api/")[0] if endpoint else "http://localhost:11434"
            probe = _http_probe(f"{base}/api/tags", timeout=2.0)
        elif provider == "nvidia":
            from friday.reasoning.nvidia_reasoner import has_credentials

            if not has_credentials():
                return {
                    "status": "offline",
                    "detail": (
                        "NVIDIA API key not configured "
                        "(set NVIDIA_API_KEY or FRIDAY_NVIDIA_API_KEY)"
                    ),
                    "provider": provider,
                    "endpoint": endpoint,
                }
            api_key = (
                os.environ.get("NVIDIA_API_KEY")
                or os.environ.get("FRIDAY_NVIDIA_API_KEY")
                or ""
            ).strip()
            probe = _http_probe(
                f"{endpoint}/models",
                timeout=3.0,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        else:
            probe = _http_probe(f"{endpoint}/health", timeout=2.0)
        if not probe.get("reachable"):
            return {
                "status": "offline",
                "detail": probe.get("error") or f"{provider} unreachable at {endpoint}",
                "provider": provider,
                "endpoint": endpoint,
            }
        status = "healthy"
        body = probe.get("body")
        if isinstance(body, dict) and body.get("status") not in (None, "ok"):
            status = "degraded"
        return {
            "status": status,
            "detail": f"{provider} reachable at {endpoint}",
            "provider": provider,
            "endpoint": endpoint,
        }

    def _image_health(self) -> Dict[str, Any]:
        try:
            health = self.image_manager().health()
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}
        if not health.get("installed"):
            return {"status": "unavailable", "detail": "sd-cli runtime not installed"}
        if not health.get("configured"):
            return {"status": "unavailable", "detail": "Qwen image model files missing"}
        return {
            "status": "healthy",
            "detail": f"{health.get('device')} · {health.get('gpu_name') or 'unknown GPU'}",
            "device": health.get("device"),
            "vram_total_mb": health.get("vram_total_mb"),
        }

    def _module_health(self, module: str, detail: str, model_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        try:
            __import__(module)
        except Exception as exc:
            return {"status": "error", "detail": f"{module} import failed: {exc}"}
        if model_paths:
            missing = [p for p in model_paths if p and not Path(p).exists()]
            if missing:
                return {"status": "degraded", "detail": f"model files missing: {', '.join(missing)}"}
        return {"status": "healthy", "detail": detail}

    def health(self) -> Dict[str, Any]:
        components: Dict[str, Any] = {}
        components["backend"] = {
            "status": "healthy",
            "detail": f"FastAPI process alive · {self.identity()['version']}",
        }
        components["config"] = {
            "status": "healthy" if not self.warnings else "degraded",
            "detail": "configuration valid" if not self.warnings else "; ".join(self.warnings[:3]),
        }
        components["reasoning"] = self._reasoning_health()
        components["image"] = self._image_health()

        research_cfg = self.config.get("research", {}) or {}
        components["research"] = {
            "status": "healthy" if research_cfg.get("enabled") else "unavailable",
            "detail": (
                f"provider={research_cfg.get('provider', 'duckduckgo')}"
                if research_cfg.get("enabled")
                else "web research disabled in config"
            ),
        }

        rag_cfg = self.config.get("rag", {}) or {}
        components["rag"] = {
            "status": "healthy" if rag_cfg.get("enabled") else "unavailable",
            "detail": (
                f"collection={rag_cfg.get('collection', 'friday_knowledge')}"
                if rag_cfg.get("enabled")
                else "RAG disabled in config"
            ),
        }

        voice_cfg = self.config.get("voice", {}) or {}
        tts_cfg = voice_cfg.get("tts", {}) or {}
        components["stt"] = self._module_health(
            "faster_whisper",
            f"faster-whisper · {(voice_cfg.get('stt', {}) or {}).get('model', 'small.en')}",
        )
        components["tts"] = self._module_health(
            "piper",
            f"{tts_cfg.get('engine', 'piper')} engine",
        )
        components["websocket"] = {
            "status": "healthy",
            "detail": f"{bus.subscriber_count} dashboard client(s) connected",
            "clients": bus.subscriber_count,
        }
        try:
            import sounddevice

            inputs = [
                d for d in sounddevice.query_devices()
                if int(d.get("max_input_channels") or 0) > 0
            ]
            components["microphone"] = {
                "status": "healthy" if inputs else "unavailable",
                "detail": f"{len(inputs)} input device(s)" if inputs else "no microphone detected",
            }
        except Exception as exc:
            components["microphone"] = {"status": "unavailable", "detail": f"audio unavailable: {exc}"}

        required = ("backend", "config", "reasoning")
        healthy_count = sum(1 for c in components.values() if c.get("status") == "healthy")
        if any(components[name].get("status") != "healthy" for name in required):
            overall = "degraded"
        elif healthy_count == len(components):
            overall = "healthy"
        else:
            overall = "degraded"
        return {"overall": overall, "components": components, "timestamp": datetime.now().astimezone().isoformat()}

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------
    def _server_context_window(self, endpoint: str) -> Optional[int]:
        if not endpoint:
            return None
        probe = _http_probe(f"{endpoint.rstrip('/')}/props", timeout=2.0)
        body = probe.get("body")
        if not isinstance(body, dict):
            return None
        settings = body.get("default_generation_settings") or {}
        for key in ("n_ctx", "n_ctx_train"):
            value = settings.get(key) if isinstance(settings, dict) else None
            if isinstance(value, int):
                return value
        value = body.get("n_ctx")
        return value if isinstance(value, int) else None

    def models(self) -> List[Dict[str, Any]]:
        rcfg = self.reasoning_config()
        provider = str(rcfg.get("provider", "llamacpp")).lower()
        model_path = str(rcfg.get("model", "") or "")
        endpoint = str(rcfg.get("endpoint", "") or "")
        reasoning_health = self._reasoning_health()
        reasoning_loaded = reasoning_health.get("status") == "healthy"
        is_nvidia = provider == "nvidia"
        if is_nvidia:
            family = "NVIDIA API Catalog"
            display_name = model_path or provider
            context_window = None
            quantization = ""
        else:
            family = "llama.cpp" if provider == "llamacpp" else "Ollama"
            display_name = Path(model_path).name or model_path or provider
            context_window = (
                self._server_context_window(endpoint) if reasoning_loaded else None
            )
            quantization = _quantization_hint(model_path)
        models: List[Dict[str, Any]] = [
            {
                "id": f"reasoning:{provider}",
                "name": display_name,
                "family": family,
                "kind": "reasoning",
                "provider": provider,
                "path": model_path,
                "quantization": quantization,
                "active": True,
                "loaded": reasoning_loaded,
                "health": reasoning_health.get("status", "unknown"),
                "context_window": context_window,
                "endpoint": endpoint,
                "error": "" if reasoning_loaded else reasoning_health.get("detail", ""),
            }
        ]
        try:
            image_health = self.image_manager().health()
            components = {
                "diffusion": Path(image_health.get("model_path") or "").name,
                "text_encoder": Path(image_health.get("text_encoder_path") or "").name,
                "vae": Path(image_health.get("vae_path") or "").name,
            }
            models.append(
                {
                    "id": "image:qwen-image-2.1",
                    "name": "Qwen-Image-2.1",
                    "family": "stable-diffusion.cpp",
                    "kind": "image",
                    "provider": "qwen-image",
                    "path": image_health.get("model_path") or "",
                    "quantization": _quantization_hint(image_health.get("model_path") or ""),
                    "active": False,
                    "loaded": bool(image_health.get("loaded")),
                    "health": "ready" if image_health.get("ready") else "unavailable",
                    "context_window": None,
                    "components": components,
                    "device": image_health.get("device"),
                    "error": "" if image_health.get("ready") else "runtime or model files missing",
                }
            )
        except Exception as exc:
            models.append(
                {
                    "id": "image:qwen-image-2.1",
                    "name": "Qwen-Image-2.1",
                    "family": "stable-diffusion.cpp",
                    "kind": "image",
                    "provider": "qwen-image",
                    "active": False,
                    "loaded": False,
                    "health": "error",
                    "error": str(exc),
                }
            )
        brain = self.config.get("brain", {}) or {}
        if brain.get("ollama_model"):
            models.append(
                {
                    "id": f"ollama:{brain.get('ollama_model')}",
                    "name": str(brain.get("ollama_model")),
                    "family": "Ollama",
                    "kind": "chat",
                    "provider": "ollama",
                    "active": False,
                    "loaded": None,
                    "health": "unknown",
                    "endpoint": brain.get("ollama_url", ""),
                    "error": "not verified in this session",
                }
            )
        return models

    def active_model(self) -> Optional[Dict[str, Any]]:
        for model in self.models():
            if model.get("active"):
                return model
        return None

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def tools(self) -> List[Dict[str, Any]]:
        from friday.intent.models import Action
        from friday.safety.permissions import _ACTION_PERMISSION_KEY

        perms = self.tools_config().get("permissions", {}) or {}
        tc = self.tools_config()
        result: List[Dict[str, Any]] = []
        for action in Action:
            if action.name == "UNKNOWN":
                continue
            key = _ACTION_PERMISSION_KEY.get(action)
            allowed = bool(perms.get(key, False)) if key else action.name.startswith("SYSTEM_")
            result.append(
                {
                    "name": action.name,
                    "id": action.name.lower(),
                    "permission_key": key,
                    "allowed": allowed,
                    "dry_run": bool(tc.get("dry_run", True)),
                    "requires_confirmation": action.name in ("CLOSE_APP", "FORGET"),
                    "available": allowed and not bool(tc.get("dry_run", True)),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Agents (derived from real subsystems + live activity)
    # ------------------------------------------------------------------
    def _running_for(self, source: str) -> Optional[Dict[str, Any]]:
        for item in self.activity.list(status=STATUS_RUNNING, limit=20)["items"]:
            if item.get("source") == source:
                return item
        return None

    def agents(self) -> List[Dict[str, Any]]:
        reasoning_health = self._reasoning_health()
        research_cfg = self.config.get("research", {}) or {}
        rag_cfg = self.config.get("rag", {}) or {}
        image_health = self._image_health()

        def status_for(source: str, available: bool) -> str:
            running = self._running_for(source)
            if running:
                return "working"
            return "idle" if available else "offline"

        def last_for(source: str) -> Optional[Dict[str, Any]]:
            for item in self.activity.list(source=source, limit=1)["items"]:
                return item
            return None

        def build(agent_id, name, description, source, available, capabilities, extra=None):
            running = self._running_for(source)
            last = last_for(source)
            payload = {
                "id": agent_id,
                "name": name,
                "description": description,
                "source": source,
                "status": status_for(source, available),
                "current_task": (running or {}).get("title"),
                "current_task_id": (running or {}).get("id"),
                "last_activity": (last or {}).get("updated_at"),
                "last_status": (last or {}).get("status"),
                "last_error": (last or {}).get("error") or "",
                "capabilities": capabilities,
            }
            if extra:
                payload.update(extra)
            return payload

        return [
            build(
                "reasoner",
                "Local Reasoner",
                "Routes and answers requests with the configured local model.",
                "chat",
                reasoning_health.get("status") == "healthy",
                ["chat", "intent routing", "planning"],
                {"provider": reasoning_health.get("provider"), "endpoint": reasoning_health.get("endpoint")},
            ),
            build(
                "research",
                "Research Agent",
                "Runs live web research and returns real sources.",
                "research",
                bool(research_cfg.get("enabled")),
                ["web search", "source summarization"],
                {"provider": research_cfg.get("provider", "duckduckgo")},
            ),
            build(
                "image",
                "Image Generator",
                "Generates images locally with Qwen-Image-2.1 via sd-cli.",
                "image",
                image_health.get("status") == "healthy",
                ["text-to-image", "local generation"],
                {"device": image_health.get("device")},
            ),
            build(
                "rag",
                "Knowledge Retrieval",
                "Retrieves locally indexed documents for grounded answers.",
                "rag",
                bool(rag_cfg.get("enabled")),
                ["document retrieval", "context grounding"],
                {"collection": rag_cfg.get("collection", "friday_knowledge")},
            ),
            build(
                "tools",
                "Tool Executor",
                "Runs permitted local actions through the tool registry.",
                "tool",
                True,
                ["app control", "files", "system", "web"],
            ),
        ]

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def submit_chat(self, message: str) -> Dict[str, Any]:
        item = self.activity.add(
            KIND_CHAT,
            _truncate(message),
            source="chat",
            status=STATUS_RUNNING,
            message="Processing request",
        )
        bus.publish_threadsafe(
            make_event("task.created", source="chat", task_id=item["id"], status="running",
                       message="Processing request", data={"prompt": message})
        )
        try:
            assistant = self.ensure_assistant()
            with self._chat_lock:
                response, keep_running = assistant.conversation_manager.handle_transcript(message)
        except Exception as exc:
            self.activity.update(item["id"], status=STATUS_FAILED, error=str(exc), message=str(exc))
            bus.publish_threadsafe(
                make_event("task.failed", source="chat", task_id=item["id"], status="failed", message=str(exc))
            )
            raise
        assistant = self._assistant
        try:
            state = assistant.conversation_manager.state.name if assistant else "IDLE"
        except Exception:
            state = "UNKNOWN"
        self.activity.update(
            item["id"],
            status=STATUS_COMPLETED,
            message=_truncate(response, 240),
            meta={"response": response, "keep_running": bool(keep_running)},
        )
        bus.publish_threadsafe(
            make_event("task.completed", source="chat", task_id=item["id"], status="completed",
                       message=_truncate(response, 240))
        )
        bus.publish_threadsafe(make_event("voice.state", source="assistant", status=state))
        return {
            "task_id": item["id"],
            "response": response,
            "keep_running": bool(keep_running),
            "state": state,
            "model": self.active_model(),
            "timestamp": datetime.now().astimezone().isoformat(),
        }

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------
    def generate_image(
        self,
        prompt: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        item = self.activity.add(
            KIND_IMAGE, _truncate(prompt), source="image", status=STATUS_RUNNING,
            message="Generating image",
        )
        bus.publish_threadsafe(
            make_event("image.started", source="image", task_id=item["id"], status="running",
                       message="Generating image", data={"prompt": prompt})
        )
        try:
            manager = self.image_manager()
            result = manager.generate(prompt=prompt, width=width, height=height, steps=steps, seed=seed)
        except Exception as exc:
            self.activity.update(item["id"], status=STATUS_FAILED, error=str(exc), message=str(exc))
            bus.publish_threadsafe(
                make_event("image.failed", source="image", task_id=item["id"], status="failed", message=str(exc))
            )
            raise
        payload = result.to_dict()
        if result.success:
            self.activity.update(
                item["id"], status=STATUS_COMPLETED, message=f"Saved {result.filename}",
                meta={"path": str(result.path), "width": result.width, "height": result.height,
                      "steps": result.steps, "seed": result.seed, "elapsed_ms": result.elapsed_ms},
            )
            bus.publish_threadsafe(
                make_event("image.completed", source="image", task_id=item["id"], status="completed",
                           message=f"Saved {result.filename}", data={"path": str(result.path)})
            )
        else:
            self.activity.update(
                item["id"], status=STATUS_FAILED, error=result.error_type or "generation_failed",
                message=result.message, meta={"detail": _jsonable(result.detail)},
            )
            bus.publish_threadsafe(
                make_event("image.failed", source="image", task_id=item["id"], status="failed",
                           message=result.message, data={"error_type": result.error_type})
            )
        payload["task_id"] = item["id"]
        payload["url"] = self.image_url(result.path) if result.success else None
        return payload

    def image_url(self, path: str) -> str:
        from urllib.parse import quote

        return f"/api/image/file?path={quote(str(path))}"

    # ------------------------------------------------------------------
    # Research
    # ------------------------------------------------------------------
    def run_research(self, query: str) -> Dict[str, Any]:
        item = self.activity.add(
            KIND_RESEARCH, _truncate(query), source="research", status=STATUS_RUNNING,
            message="Researching",
        )
        bus.publish_threadsafe(
            make_event("research.started", source="research", task_id=item["id"], status="running",
                       message="Researching", data={"query": query})
        )
        try:
            agent = self.research_agent()
            response = agent.research(query)
        except Exception as exc:
            self.activity.update(item["id"], status=STATUS_FAILED, error=str(exc), message=str(exc))
            bus.publish_threadsafe(
                make_event("task.failed", source="research", task_id=item["id"], status="failed", message=str(exc))
            )
            raise
        payload = _jsonable(response)
        results = payload.get("results") or []
        success = bool(payload.get("success"))
        if success:
            self.activity.update(
                item["id"], status=STATUS_COMPLETED,
                message=f"{len(results)} source(s)", meta={"sources": len(results)},
            )
            bus.publish_threadsafe(
                make_event("research.completed", source="research", task_id=item["id"], status="completed",
                           message=f"{len(results)} source(s)", data={"sources": len(results)})
            )
        else:
            error = payload.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error or "research failed")
            self.activity.update(item["id"], status=STATUS_FAILED, error=message or "research_failed", message=message or "")
            bus.publish_threadsafe(
                make_event("task.failed", source="research", task_id=item["id"], status="failed",
                           message=message or "research failed")
            )
        payload["task_id"] = item["id"]
        return payload

    # ------------------------------------------------------------------
    # Voice / conversation state
    # ------------------------------------------------------------------
    def voice_state(self) -> Dict[str, Any]:
        mic = {"available": False, "detail": "audio subsystem unavailable"}
        try:
            import sounddevice

            inputs = [d for d in sounddevice.query_devices() if int(d.get("max_input_channels") or 0) > 0]
            mic = {
                "available": bool(inputs),
                "detail": f"{len(inputs)} input device(s)" if inputs else "no microphone detected",
            }
        except Exception as exc:
            mic = {"available": False, "detail": f"audio unavailable: {exc}"}
        with self._capture_lock:
            recording = self._capture_stream is not None
        hands_free = self.handsfree_state()
        # Hands-free runs the machine microphone continuously, so it is a real
        # capture path even when the browser-recording stream is not open.
        capture_active = recording or bool(hands_free.get("active"))
        return {
            "state": self.assistant_state()["state"],
            "capture_active": capture_active,
            "microphone": mic,
            "pipeline": ["IDLE", "LISTENING", "PROCESSING", "EXECUTING", "RESPONDING"],
            "capture_supported": bool(mic["available"]),
            "hands_free": hands_free,
            "hands_free_active": bool(self._handsfree and self._handsfree.active),
            "hands_free_state": self._handsfree.state if self._handsfree else "STOPPED",
            "audio_hub": get_audio_hub().state(),
            "wake_word": self._wake_word(),
            "reason": (
                "Say \u201cHey Friday\u201d to talk. Audio is captured from the machine microphone, "
                "transcribed locally by faster-whisper, and answered by the same conversation "
                "pipeline as typed chat."
                if mic["available"]
                else "No microphone was detected, so hands-free and browser recording are "
                "unavailable. Typed chat still works."
            ),
        }

    # ------------------------------------------------------------------
    # Voice capture / synthesis (browser audio)
    # ------------------------------------------------------------------
    def _voice_config(self) -> Dict[str, Any]:
        return self.config.get("voice", {}) or {}

    def _get_stt(self):
        with self._lock:
            if self._stt is not None:
                return self._stt
            if self._stt_error:
                raise RuntimeError(self._stt_error)
            cfg = self._voice_config().get("stt", {}) or {}
            try:
                from friday.voice.speech_to_text import SpeechToText

                self._stt = SpeechToText(
                    model_size=cfg.get("model", "small.en"),
                    device=cfg.get("device", "cpu"),
                    compute_type=cfg.get("compute_type", "int8"),
                    language=cfg.get("language", "en"),
                )
                return self._stt
            except Exception as exc:
                self._stt_error = str(exc)
                raise

    def _get_tts(self):
        with self._lock:
            if self._tts is not None:
                return self._tts
            if self._tts_error:
                raise RuntimeError(self._tts_error)
            cfg = self._voice_config().get("tts", {}) or {}
            try:
                from friday.voice.text_to_speech import TextToSpeech

                self._tts = TextToSpeech(
                    engine=cfg.get("engine", "piper"),
                    fallback_engine=cfg.get("fallback_engine", "kokoro"),
                    voice=cfg.get("voice", "af_heart"),
                    speed=float(cfg.get("speed", 1.0) or 1.0),
                    device=cfg.get("device", "auto"),
                )
                return self._tts
            except Exception as exc:
                self._tts_error = str(exc)
                raise

    def transcribe_audio(self, wav_bytes: bytes) -> Dict[str, Any]:
        """Transcribe a 16-bit PCM WAV payload recorded by the browser."""
        import io
        import wave

        import numpy as np

        if not wav_bytes:
            raise ValueError("Audio payload is empty.")

        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
                channels = wav_file.getnchannels()
                width = wav_file.getsampwidth()
                rate = wav_file.getframerate()
                frames = wav_file.readframes(wav_file.getnframes())
        except wave.Error as exc:
            raise ValueError(f"Unsupported WAV payload: {exc}") from exc

        if width != 2:
            raise ValueError("Only 16-bit PCM WAV audio is supported.")

        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        if rate != 16000 and samples.size:
            target = max(1, int(len(samples) / rate * 16000))
            samples = np.interp(
                np.linspace(0.0, 1.0, num=target, endpoint=False),
                np.linspace(0.0, 1.0, num=len(samples), endpoint=False),
                samples,
            ).astype(np.float32)

        duration = float(len(samples)) / 16000.0
        if duration < 0.25:
            raise ValueError("Recording is too short to transcribe.")

        return self._transcribe_samples(samples)

    def _transcribe_samples(self, samples, detailed: bool = False, publish: bool = True) -> Dict[str, Any]:
        duration = float(len(samples)) / 16000.0
        stt = self._get_stt()
        meta = None
        if detailed:
            text, rtf, meta = stt.transcribe_detailed(samples)
        else:
            text, rtf = stt.transcribe(samples)
        if publish:
            bus.publish_threadsafe(
                make_event(
                    "voice.transcribed",
                    source="voice",
                    status="completed",
                    message=_truncate(text, 160),
                    data={"text": text, "duration_seconds": round(duration, 2)},
                )
            )
        result = {
            "text": text,
            "duration_seconds": round(duration, 2),
            "rtf": round(float(rtf), 3),
            "device": getattr(stt, "active_device", ""),
            "model": getattr(stt, "model_size", ""),
        }
        if meta is not None:
            result["quality_ok"] = bool(getattr(meta, "quality_ok", True))
            result["avg_logprob"] = getattr(meta, "avg_logprob", None)
            result["no_speech_prob"] = getattr(meta, "no_speech_prob", None)
        return result

    def start_capture(self) -> Dict[str, Any]:
        """Start recording the machine microphone (fallback when the browser refuses)."""
        import numpy as np
        import sounddevice as sd

        with self._capture_lock:
            if self._capture_stream is not None:
                raise ValueError("A recording is already in progress.")
            try:
                device_name = str(sd.query_devices(kind="input").get("name", ""))
            except Exception:
                device_name = ""
            chunks: List[Any] = []
            self._capture_chunks = chunks

            hub = get_audio_hub()
            try:
                hub.acquire("capture", blocksize=1600)
            except RuntimeError as exc:
                raise ValueError(
                    f"The microphone is in use ({exc}). Stop hands-free listening first."
                ) from exc
            self._capture_token = hub.subscribe(
                lambda frame: chunks.append(np.asarray(frame, dtype=np.float32).reshape(-1, 1))
            )
            self._capture_stream = hub.stream or object()
            self._capture_started = time.time()

        return {"recording": True, "sample_rate": 16000, "device": device_name}

    def stop_capture(self) -> Dict[str, Any]:
        """Stop the machine-microphone recording and transcribe it."""
        import numpy as np

        with self._capture_lock:
            stream = self._capture_stream
            if stream is None:
                raise ValueError("No recording is in progress.")
            self._capture_stream = None
            token = self._capture_token
            self._capture_token = None
            hub = get_audio_hub()
            try:
                if token is not None:
                    hub.unsubscribe(token)
                hub.release("capture")
            except Exception:
                pass
            chunks = self._capture_chunks or []
            self._capture_chunks = []

        if not chunks:
            raise ValueError("No audio was captured. Check the microphone and try again.")

        samples = np.concatenate(chunks, axis=0).reshape(-1).astype(np.float32)
        if float(len(samples)) / 16000.0 < 0.25:
            raise ValueError("Recording is too short to transcribe.")
        return self._transcribe_samples(samples)

    def synthesize_speech(self, text: str) -> bytes:
        """Render text to WAV bytes locally (browser playback)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("Text must not be blank.")
        tts = self._get_tts()
        return tts.synthesize_wav(text[:2000])

    # ------------------------------------------------------------------
    # Hands-free wake-word listening (machine microphone)
    # ------------------------------------------------------------------
    def _wake_word(self) -> str:
        raw = self._voice_config().get("hands_free")
        if isinstance(raw, dict) and raw.get("wake_word"):
            return str(raw["wake_word"]).strip() or "friday"
        return str(self.config.get("wake_word") or "friday").strip() or "friday"

    def _handsfree_settings(self) -> tuple[bool, Dict[str, Any]]:
        raw = self._voice_config().get("hands_free", True)
        if isinstance(raw, dict):
            options = dict(raw)
            enabled = bool(options.pop("enabled", True))
        else:
            options = {}
            enabled = bool(raw)
        allowed = {
            "sample_rate",
            "block_ms",
            "silence_ms",
            "min_speech_ms",
            "max_utterance_ms",
            "pre_roll_ms",
            "command_timeout_seconds",
            "session_timeout_seconds",
            "flush_timeout_seconds",
            "rms_floor",
            "speech_ratio",
        }
        options = {k: v for k, v in options.items() if k in allowed and v is not None}
        return enabled, options

    def _acknowledgement_phrases(self) -> List[str]:
        """Spoken replies used after a bare wake word.

        ``voice.hands_free.acknowledgement`` accepts one phrase or a list; a
        list is cycled so repeated wakes do not sound robotic. ``false``,
        null, or an empty list disables the spoken acknowledgement.
        """
        raw = self._voice_config().get("hands_free")
        if not isinstance(raw, dict):
            return []
        value = raw.get("acknowledgement")
        if value is None or value is False:
            return []
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple)):
            values = [str(item) for item in value]
        else:
            return []
        return [item.strip() for item in values if item.strip()]

    def handsfree_state(self) -> Dict[str, Any]:
        listener = self._handsfree
        enabled, _options = self._handsfree_settings()
        return {
            "enabled": enabled,
            "active": bool(listener and listener.active),
            "state": listener.state if listener else "STOPPED",
            "wake_word": listener.wake_word if listener else self._wake_word(),
            "error": self._handsfree_error,
            "heard": self._handsfree_heard,
        }

    def _publish_handsfree(self, status: Optional[str] = None) -> None:
        state = self.handsfree_state()
        if status:
            state["state"] = status
            state["active"] = status not in ("STOPPED", "ERROR")
        bus.publish_threadsafe(
            make_event(
                "voice.handsfree",
                source="voice",
                status=state["state"],
                message=self._handsfree_error if state["state"] == "ERROR" else "",
                data=state,
            )
        )

    def _handsfree_on_state(self, state: str) -> None:
        logger.info("[WAKE] state -> %s", state)
        self._publish_handsfree(state)

    def _handsfree_on_wake(self, text: str) -> None:
        self._handsfree_heard = text.strip()
        # Start an active conversation session so follow-up utterances do not
        # need the wake word until the user says "stop listening".
        try:
            assistant = self.ensure_assistant()
            assistant.conversation_manager.session.start()
            assistant.conversation_manager.start_session()
        except Exception as exc:
            logger.debug("[WAKE] session start failed: %s", exc)
        self._publish_handsfree("COMMAND_LISTENING")

    def _handsfree_on_acknowledge(self) -> None:
        """Speak a short reply after a bare wake word ("Yes Abhi" / "Yes boss")."""
        phrases = self._acknowledgement_phrases()
        if not phrases:
            return
        index = self._handsfree_ack_index % len(phrases)
        self._handsfree_ack_index = (index + 1) % len(phrases)
        phrase = phrases[index]
        logger.info("[WAKE] Acknowledging wake word: %r", phrase)
        self._publish_handsfree("RESPONDING")
        try:
            self._get_tts().speak(phrase)
        except Exception as exc:
            self._handsfree_error = f"speech playback failed: {exc}"
            logger.warning("[WAKE] %s", self._handsfree_error)
        finally:
            self._publish_handsfree("COMMAND_LISTENING")

    def _handsfree_on_error(self, message: str) -> None:
        self._handsfree_error = str(message or "hands-free listener failed")
        logger.warning("[WAKE] %s", self._handsfree_error)
        self._publish_handsfree("ERROR")

    def _handsfree_on_session_end(self) -> None:
        """Close the conversation session when the hands-free session ends.

        The listener owns wake/session timing; the assistant owns conversation
        memory. Ending one must end the other, otherwise a later wake inherits
        topics and pronouns from a conversation the user already closed
        ``stop_session`` replaces the context wholesale (history included).
        """
        assistant = self._assistant  # never spin up an assistant just to reset
        if assistant is None:
            return
        try:
            assistant.conversation_manager.stop_session()
        except Exception as exc:
            logger.debug("[WAKE] conversation reset failed: %s", exc)

    def _handsfree_on_command(self, command: str) -> None:
        """Run one spoken command and speak the reply (listener is paused)."""
        command = (command or "").strip()
        if not command:
            return
        bus.publish_threadsafe(
            make_event(
                "transcript.updated",
                source="voice",
                status="completed",
                message=_truncate(command, 240),
                data={"role": "user", "text": command, "source": "handsfree"},
            )
        )
        try:
            payload = self.submit_chat(command)
            response_text = str(payload.get("response") or "").strip()
        except Exception as exc:
            response_text = f"I couldn't process that request: {exc}"
            logger.warning("[WAKE] command failed: %s", exc)
        if not response_text:
            return
        bus.publish_threadsafe(
            make_event(
                "transcript.updated",
                source="voice",
                status="completed",
                message=_truncate(response_text, 240),
                data={"role": "assistant", "text": response_text, "source": "handsfree"},
            )
        )
        try:
            self._publish_handsfree("RESPONDING")
            self._get_tts().speak(response_text)
        except Exception as exc:
            self._handsfree_error = f"speech playback failed: {exc}"
            logger.warning("[WAKE] %s", self._handsfree_error)

    def _transcribe_handsfree(self, samples) -> str:
        peak = 0.0
        try:
            import numpy as np

            from friday.voice.speech_evidence import analyse_utterance

            audio = np.asarray(samples, dtype=np.float32).reshape(-1)
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0

            # Root-cause gate: loud transients (desk knocks, mouse clicks,
            # keyboard taps, thuds) can satisfy the energy/VAD gate and make
            # Whisper hallucinate "boom." / "tell me.". Reject an utterance
            # that has no sustained speech-shaped audio *before* STT runs, so
            # the hallucinated text is never published or acted on.
            evidence = analyse_utterance(audio)
            if not evidence.is_speech:
                logger.info(
                    "[WAKE] rejected non-speech (reason=%s peak=%.4f frames=%d/%d "
                    "speech=%.2f)",
                    evidence.reason,
                    peak,
                    evidence.speech_frames,
                    evidence.active_frames,
                    evidence.speech_ratio,
                )
                return ""

            # Microphones on laptops often deliver speech at a very low level.
            # Normalise to a comfortable peak before recognition so quiet
            # speech is not transcribed as silence.
            if peak > 0.002:
                audio = audio * min(24.0, 0.9 / peak)
            result = self._transcribe_samples(audio, detailed=True, publish=False)
            text = str(result.get("text") or "")
            if text and result.get("quality_ok") is False:
                logger.info(
                    "[WAKE] rejected low-quality transcript (no_speech=%s "
                    "avg_logprob=%s): %r",
                    result.get("no_speech_prob"),
                    result.get("avg_logprob"),
                    text[:160],
                )
                return ""
            if text:
                bus.publish_threadsafe(
                    make_event(
                        "voice.transcribed",
                        source="voice",
                        status="completed",
                        message=_truncate(text, 160),
                        data={
                            "text": text,
                            "duration_seconds": result.get("duration_seconds"),
                        },
                    )
                )
        except Exception as exc:
            logger.warning("[WAKE] transcription failed: %s", exc)
            return ""
        logger.info("[WAKE] captured peak %.4f -> %r", peak, text[:160])
        if text:
            logger.info("[WAKE] heard %r", text[:160])
        return text

    def start_handsfree(self) -> Dict[str, Any]:
        """Start always-on wake-word listening on the machine microphone."""
        with self._handsfree_lock:
            listener = self._handsfree
            if listener is not None and listener.active:
                return self.handsfree_state()

            enabled, options = self._handsfree_settings()
            if not enabled:
                raise ValueError(
                    "Hands-free listening is disabled. Set voice.hands_free: true in config.yaml."
                )

            try:
                import sounddevice as sd

                inputs = [
                    d for d in sd.query_devices() if int(d.get("max_input_channels") or 0) > 0
                ]
            except Exception as exc:
                raise RuntimeError(f"Audio subsystem unavailable: {exc}") from exc
            if not inputs:
                raise RuntimeError("No microphone was detected, so hands-free listening cannot start.")

            from friday.web.handsfree import HandsFreeConfig, HandsFreeListener

            vad_cfg = self._voice_config().get("vad", {})
            vad_enabled = bool(vad_cfg.get("enabled", True)) if isinstance(vad_cfg, dict) else True
            self._handsfree_error = ""
            self._handsfree_heard = ""
            listener = HandsFreeListener(
                transcribe=self._transcribe_handsfree,
                on_command=self._handsfree_on_command,
                on_state=self._handsfree_on_state,
                on_wake=self._handsfree_on_wake,
                on_acknowledge=self._handsfree_on_acknowledge,
                on_error=self._handsfree_on_error,
                on_session_end=self._handsfree_on_session_end,
                interrupt=lambda: self._get_tts().stop(),
                config=HandsFreeConfig(wake_word=self._wake_word(), **options),
                vad=None if vad_enabled else False,
            )
            self._handsfree = listener
            listener.start()

            # Give the capture thread a moment to open the microphone so the
            # returned state reflects reality instead of a stale STOPPED.
            deadline = time.monotonic() + 1.0
            while listener.active and listener.state == "STOPPED" and time.monotonic() < deadline:
                time.sleep(0.01)
            initial_state = listener.state if listener.state != "STOPPED" else "WAKE_LISTENING"

        self._publish_handsfree(initial_state)
        return self.handsfree_state()

    def stop_handsfree(self) -> Dict[str, Any]:
        """Stop wake-word listening and release the microphone."""
        with self._handsfree_lock:
            listener = self._handsfree
            self._handsfree = None
            if listener is not None:
                try:
                    listener.stop()
                except Exception as exc:
                    logger.debug("[WAKE] stop failed: %s", exc)
        # The listener may have been already dead, so reset explicitly: a
        # stopped voice console must not leave an active conversation session.
        self._handsfree_on_session_end()
        self._publish_handsfree("STOPPED")
        return self.handsfree_state()

    # ------------------------------------------------------------------
    # Settings (redacted)
    # ------------------------------------------------------------------
    def settings(self) -> Dict[str, Any]:
        reasoning = dict(self.reasoning_config())
        voice = self.config.get("voice", {}) or {}
        image_cfg = self.config.get("image", {}) or {}
        research_cfg = dict(self.config.get("research", {}) or {})
        research_cfg.pop("api_key", None)
        return {
            "identity": self.identity(),
            "backend_url": "http://127.0.0.1:8420",
            "mode": "local-first",
            "state": self.state,
            "warnings": self.warnings,
            "security": {
                "dry_run": bool(self.tools_config().get("dry_run", True)),
                "allow_real_execution": bool(self.tools_config().get("allow_real_execution", False)),
            },
            "reasoning": {
                "provider": reasoning.get("provider"),
                "model": reasoning.get("model"),
                "endpoint": reasoning.get("endpoint"),
                "timeout": reasoning.get("timeout"),
            },
            "image": {
                "provider": image_cfg.get("provider"),
                "width": image_cfg.get("width"),
                "height": image_cfg.get("height"),
                "steps": image_cfg.get("steps"),
                "device": image_cfg.get("device"),
                "timeout": image_cfg.get("timeout"),
            },
            "voice": {
                "offline_only": voice.get("offline_only"),
                "wake_word_required": voice.get("wake_word_required"),
                "stt_model": (voice.get("stt", {}) or {}).get("model"),
                "tts_engine": (voice.get("tts", {}) or {}).get("engine"),
            },
            "research": {
                "enabled": research_cfg.get("enabled"),
                "provider": research_cfg.get("provider"),
                "max_results": research_cfg.get("max_results"),
            },
            "monitoring": {"refresh_interval_ms": 1500},
        }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def metrics(self) -> Dict[str, Any]:
        return system_metrics()

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    def overview(self) -> Dict[str, Any]:
        return {
            "identity": self.identity(),
            "state": self.state,
            "metrics": self.metrics(),
            "health": self.health(),
            "active_model": self.active_model(),
            "agents": self.agents(),
            "activity": self.activity.recent(limit=12),
            "counts": self.activity.counts(),
            "warnings": self.warnings,
            "timestamp": datetime.now().astimezone().isoformat(),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        try:
            self.stop_handsfree()
        except Exception:
            pass
        assistant = self._assistant
        self._assistant = None
        if assistant is not None:
            try:
                assistant.shutdown()
            except Exception:
                pass
        if self._memory_service is not None:
            try:
                self._memory_service.close()
            except Exception:
                pass
        if self._image_manager is not None:
            try:
                self._image_manager.unload()
            except Exception:
                pass


_runtime: Optional[DashboardRuntime] = None
_runtime_lock = threading.Lock()


def get_runtime() -> DashboardRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = DashboardRuntime()
        return _runtime


def reset_runtime(runtime: Optional[DashboardRuntime] = None) -> None:
    global _runtime
    with _runtime_lock:
        _runtime = runtime
