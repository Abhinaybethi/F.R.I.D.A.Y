"""Dashboard runtime: the single bridge between the web API and real services.

The runtime is deliberately lazy. Importing or starting the web app never loads
models or spawns an inference server; the assistant is constructed on the first
chat/voice request, image generation on the first image request, and research on
the first research request. Health, metrics, models, tools, and agents are
derived from configuration and live probes, never from sample data.
"""
import dataclasses
import json
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


def _http_probe(url: str, timeout: float = 2.0) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
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
        self._image_manager = None
        self._research_agent = None
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
        return self.config.get("reasoning", {}) or {}

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

                self._assistant = Friday(config_path=self.config_path, text_mode=True)
                self.state = "ready"
                return self._assistant
            except Exception as exc:
                self._assistant_error = str(exc)
                self.state = "degraded"
                raise

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
        models: List[Dict[str, Any]] = [
            {
                "id": f"reasoning:{provider}",
                "name": Path(model_path).name or model_path or provider,
                "family": "llama.cpp" if provider == "llamacpp" else "Ollama",
                "kind": "reasoning",
                "provider": provider,
                "path": model_path,
                "quantization": _quantization_hint(model_path),
                "active": True,
                "loaded": reasoning_loaded,
                "health": reasoning_health.get("status", "unknown"),
                "context_window": self._server_context_window(endpoint) if reasoning_loaded else None,
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
        return {
            "state": self.assistant_state()["state"],
            "capture_active": False,
            "microphone": mic,
            "pipeline": ["IDLE", "LISTENING", "PROCESSING", "EXECUTING", "RESPONDING"],
            "capture_supported": False,
            "reason": (
                "Live microphone capture is owned by the desktop voice runtime. "
                "This web dashboard shows real conversation state and supports typed chat."
            ),
        }

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
        assistant = self._assistant
        self._assistant = None
        if assistant is not None:
            try:
                assistant.shutdown()
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
