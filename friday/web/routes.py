"""HTTP API for the dashboard.

Every route is a thin, validated adapter over :class:`DashboardRuntime`, which in
turn delegates to the real F.R.I.D.A.Y services. Nothing here fabricates state:
when a service is unreachable the response says so.

Long-running work (chat inference, image generation, web research, tool
execution) is dispatched to the threadpool so the event loop, the metrics
polling, and the WebSocket broadcaster stay responsive.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from friday.web.activity import (
    KIND_AGENT,
    KIND_CODE,
    KIND_IMAGE,
    KIND_RESEARCH,
    KIND_TOOL,
    KIND_VOICE,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
)
from friday.web.events import bus, event_types, make_event
from friday.web.runtime import DashboardRuntime, get_runtime

router = APIRouter(prefix="/api")

_MAX_PROMPT = 2000
_MAX_MESSAGE = 8000


# ----------------------------------------------------------------------
# Request models
# ----------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE)


class ImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=_MAX_PROMPT)
    width: Optional[int] = Field(default=None, ge=256, le=2048)
    height: Optional[int] = Field(default=None, ge=256, le=2048)
    steps: Optional[int] = Field(default=None, ge=1, le=60)
    seed: Optional[int] = Field(default=None, ge=0, le=2**32 - 1)


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=_MAX_PROMPT)


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class ToolExecuteRequest(BaseModel):
    target: str = Field(default="", max_length=2000)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    confirm: bool = Field(
        default=False,
        description="Explicit acknowledgement for actions that mutate the system.",
    )


class MemoryFactRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    predicate: str = Field(..., min_length=1, max_length=200)
    object: str = Field(..., min_length=1, max_length=2000)
    category: str = Field(default="general", max_length=64)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_message_id: Optional[str] = Field(default=None, max_length=200)


class MemoryFactUpdateRequest(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=200)
    predicate: Optional[str] = Field(default=None, max_length=200)
    object: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=64)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)


class MemoryTaskRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000)
    source_session_id: Optional[str] = Field(default=None, max_length=200)
    meta: Dict[str, Any] = Field(default_factory=dict)


class MemoryTaskStepRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=200)
    target: str = Field(default="", max_length=2000)
    idempotency_key: Optional[str] = Field(default=None, max_length=200)
    status: str = Field(default="pending", max_length=32)


class MemoryTaskStepUpdateRequest(BaseModel):
    status: Optional[str] = Field(default=None, max_length=32)
    result: Optional[Dict[str, Any]] = None
    verification_status: Optional[str] = Field(default=None, max_length=64)
    error: Optional[str] = Field(default=None, max_length=2000)


class MemoryPruneRequest(BaseModel):
    dry_run: bool = True
    retention_days: Optional[int] = Field(default=None, ge=0, le=36500)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _runtime() -> DashboardRuntime:
    return get_runtime()


def _error(status_code: int, message: str, error_type: str = "request_failed", **extra: Any) -> HTTPException:
    payload = {"error": {"type": error_type, "message": message, **extra}}
    return HTTPException(status_code=status_code, detail=payload)


def _task_or_404(task_id: str) -> Dict[str, Any]:
    item = _runtime().activity.get(task_id)
    if item is None:
        raise _error(404, f"No task with id {task_id!r}.", "task_not_found")
    return item


def _publish(event: Dict[str, Any]) -> None:
    """Publish from a sync context (threadpool)."""
    bus.publish_threadsafe(event)


def _image_output_dir() -> Path:
    try:
        from friday.image.config import QwenImageConfig

        return Path(QwenImageConfig.load(_runtime().config_path).output_dir).resolve()
    except Exception:
        return Path("output/generated_images").resolve()


# ----------------------------------------------------------------------
# Identity / health
# ----------------------------------------------------------------------
@router.get("/health", summary="Liveness probe for the dashboard backend")
def api_health() -> Dict[str, Any]:
    runtime = _runtime()
    return {
        "ok": True,
        "state": runtime.state,
        "identity": runtime.identity(),
        "warnings": runtime.warnings,
    }


@router.get("/system/metrics", summary="Real CPU/RAM/disk/GPU telemetry")
def system_metrics_route() -> Dict[str, Any]:
    return _runtime().metrics()


@router.get("/system/health", summary="Per-service health checks")
def system_health_route() -> Dict[str, Any]:
    return _runtime().health()


@router.get("/dashboard/overview", summary="Bootstrap payload for the dashboard")
def overview_route() -> Dict[str, Any]:
    return _runtime().overview()


# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------
@router.get("/models")
def models_route() -> Dict[str, Any]:
    runtime = _runtime()
    models = runtime.models()
    return {"models": models, "active": runtime.active_model(), "count": len(models)}


@router.get("/models/active")
def active_model_route() -> Dict[str, Any]:
    return {"active": _runtime().active_model()}


# ----------------------------------------------------------------------
# Agents
# ----------------------------------------------------------------------
@router.get("/agents")
def agents_route() -> Dict[str, Any]:
    agents = _runtime().agents()
    return {"agents": agents, "count": len(agents)}


@router.get("/agents/{agent_id}")
def agent_route(agent_id: str) -> Dict[str, Any]:
    for agent in _runtime().agents():
        if agent.get("id") == agent_id:
            history = _runtime().activity.list(
                source=agent.get("source"), limit=25
            )["items"]
            return {"agent": agent, "history": history}
    raise _error(404, f"No agent with id {agent_id!r}.", "agent_not_found")


# ----------------------------------------------------------------------
# Tasks / activity
# ----------------------------------------------------------------------
@router.get("/tasks")
def tasks_route(
    kind: Optional[str] = Query(default=None, max_length=32),
    status: Optional[str] = Query(default=None, max_length=32),
    source: Optional[str] = Query(default=None, max_length=64),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    return _runtime().activity.list(
        kind=kind, status=status, source=source, search=search, limit=limit, offset=offset
    )


@router.get("/tasks/{task_id}")
def task_route(task_id: str) -> Dict[str, Any]:
    return _task_or_404(task_id)


@router.get("/activity")
def activity_route(
    kind: Optional[str] = Query(default=None, max_length=32),
    status: Optional[str] = Query(default=None, max_length=32),
    source: Optional[str] = Query(default=None, max_length=64),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    runtime = _runtime()
    payload = runtime.activity.list(
        kind=kind, status=status, source=source, search=search, limit=limit, offset=offset
    )
    payload["counts"] = runtime.activity.counts()
    return payload


@router.get("/events/types")
def events_types_route() -> Dict[str, Any]:
    return {"types": event_types(), "schema_version": 1}


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------
@router.get("/tools")
def tools_route() -> Dict[str, Any]:
    tools = _runtime().tools()
    return {
        "tools": tools,
        "count": len(tools),
        "enabled": sum(1 for t in tools if t.get("allowed")),
    }


@router.post("/tools/{action_name}/execute", summary="Invoke a tool through the existing registry")
def execute_tool_route(action_name: str, body: ToolExecuteRequest) -> Dict[str, Any]:
    from friday.intent.models import Action, Intent

    runtime = _runtime()
    action = None
    for candidate in Action:
        if candidate.name.lower() == action_name.lower():
            action = candidate
            break
    if action is None or action is Action.UNKNOWN:
        raise _error(404, f"Unknown tool {action_name!r}.", "tool_not_found")

    descriptor = next(
        (t for t in runtime.tools() if t["id"] == action.name.lower()), None
    )
    if descriptor is None:
        raise _error(404, f"Tool {action_name!r} is not exposed.", "tool_not_found")

    if action is Action.IMAGE_GENERATION:
        raise _error(
            400,
            "Use POST /api/image/generate for image generation.",
            "unsupported_route",
        )

    if not descriptor.get("allowed"):
        raise _error(
            403,
            f"Tool {action.name} is disabled by the permissions policy "
            f"({descriptor.get('permission_key')!r}).",
            "permission_denied",
        )

    if descriptor.get("requires_confirmation") and not body.confirm:
        raise _error(
            409,
            f"Tool {action.name} requires explicit confirmation.",
            "confirmation_required",
        )

    intent = Intent(
        action=action,
        target=body.target,
        arguments=body.arguments or {},
        intent_confidence=1.0,
        target_confidence=1.0,
        raw_text=f"dashboard:{action.name}",
    )

    record = runtime.activity.add(
        KIND_TOOL,
        action.name,
        source="tool",
        status=STATUS_RUNNING,
        message=f"target={body.target!r}",
        meta={"arguments": body.arguments or {}},
    )
    _publish(
        make_event(
            "tool.started",
            source="tool",
            task_id=record["id"],
            status="running",
            message=f"{action.name} started",
            data={"action": action.name, "target": body.target},
        )
    )

    try:
        from friday.tools import registry

        tools_cfg = runtime.tools_config()
        outcome = registry.execute(
            intent,
            dry_run=bool(tools_cfg.get("dry_run", True)),
            allow_real_execution=bool(tools_cfg.get("allow_real_execution", False)),
            permissions=tools_cfg.get("permissions") or {},
        )
    except Exception as exc:  # tool crash must be surfaced, never hidden
        runtime.activity.update(
            record["id"], status=STATUS_FAILED, error=str(exc), message=str(exc)
        )
        _publish(
            make_event(
                "tool.failed",
                source="tool",
                task_id=record["id"],
                status="failed",
                message=str(exc),
                data={"action": action.name},
            )
        )
        raise _error(500, str(exc), "tool_execution_failed", action=action.name) from exc

    execution = outcome.execution
    final_status = outcome.final_status.value
    payload = {
        "task_id": record["id"],
        "action": action.name,
        "target": execution.target,
        "status": execution.status.value,
        "final_status": final_status,
        "verification": outcome.verification.status.value,
        "message": outcome.user_message,
        "spoken_message": outcome.spoken_message,
        "blocked": bool(execution.blocked),
        "latency_ms": round(execution.execution_latency_ms, 1),
        "tool_result": execution.raw_tool_result or {},
    }

    if outcome.is_success:
        runtime.activity.update(
            record["id"],
            status=STATUS_COMPLETED,
            message=outcome.user_message[:240],
            meta={"final_status": final_status, "latency_ms": payload["latency_ms"]},
        )
        _publish(
            make_event(
                "tool.completed",
                source="tool",
                task_id=record["id"],
                status="completed",
                message=outcome.user_message[:240],
                data={"action": action.name},
            )
        )
    elif execution.blocked:
        runtime.activity.update(
            record["id"],
            status=STATUS_BLOCKED,
            error=outcome.user_message,
            message=outcome.user_message[:240],
        )
        _publish(
            make_event(
                "tool.failed",
                source="tool",
                task_id=record["id"],
                status="blocked",
                message=outcome.user_message[:240],
                data={"action": action.name},
            )
        )
    else:
        runtime.activity.update(
            record["id"],
            status=STATUS_FAILED,
            error=outcome.user_message,
            message=outcome.user_message[:240],
        )
        _publish(
            make_event(
                "tool.failed",
                source="tool",
                task_id=record["id"],
                status="failed",
                message=outcome.user_message[:240],
                data={"action": action.name},
            )
        )
    return payload


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------
@router.post("/chat", summary="Send a turn through the real conversation manager")
async def chat_route(body: ChatRequest) -> Dict[str, Any]:
    message = body.message.strip()
    if not message:
        raise _error(422, "Message must not be blank.", "invalid_input")
    try:
        return await run_in_threadpool(_runtime().submit_chat, message)
    except Exception as exc:
        raise _error(503, str(exc), "chat_failed") from exc


# ----------------------------------------------------------------------
# Voice
# ----------------------------------------------------------------------
@router.get("/voice/state")
def voice_state_route() -> Dict[str, Any]:
    return _runtime().voice_state()


@router.post("/voice/transcribe", summary="Transcribe a browser-recorded WAV payload")
async def voice_transcribe_route(request: Request) -> Dict[str, Any]:
    body = await request.body()
    if not body:
        raise _error(422, "Audio payload must not be empty.", "invalid_input")
    if len(body) > 25 * 1024 * 1024:
        raise _error(413, "Audio payload is too large.", "payload_too_large")
    try:
        return await run_in_threadpool(_runtime().transcribe_audio, body)
    except ValueError as exc:
        raise _error(422, str(exc), "invalid_audio") from exc
    except Exception as exc:
        raise _error(503, str(exc), "transcription_failed") from exc


@router.post("/voice/speak", summary="Synthesize a spoken reply as WAV")
async def voice_speak_route(body: SpeakRequest) -> Response:
    text = body.text.strip()
    if not text:
        raise _error(422, "Text must not be blank.", "invalid_input")
    try:
        audio = await run_in_threadpool(_runtime().synthesize_speech, text)
    except ValueError as exc:
        raise _error(422, str(exc), "invalid_input") from exc
    except Exception as exc:
        raise _error(503, str(exc), "tts_failed") from exc
    return Response(content=audio, media_type="audio/wav")


@router.post("/voice/capture/start", summary="Start backend microphone capture")
async def voice_capture_start_route() -> Dict[str, Any]:
    try:
        return await run_in_threadpool(_runtime().start_capture)
    except ValueError as exc:
        raise _error(409, str(exc), "capture_conflict") from exc
    except Exception as exc:
        raise _error(503, str(exc), "capture_failed") from exc


@router.post("/voice/capture/stop", summary="Stop backend capture and transcribe it")
async def voice_capture_stop_route() -> Dict[str, Any]:
    try:
        return await run_in_threadpool(_runtime().stop_capture)
    except ValueError as exc:
        raise _error(422, str(exc), "invalid_audio") from exc
    except Exception as exc:
        raise _error(503, str(exc), "transcription_failed") from exc


@router.post("/voice/wake/start", summary="Start always-on hands-free wake-word listening")
async def voice_wake_start_route() -> Dict[str, Any]:
    try:
        return await run_in_threadpool(_runtime().start_handsfree)
    except ValueError as exc:
        raise _error(409, str(exc), "handsfree_disabled") from exc
    except RuntimeError as exc:
        raise _error(503, str(exc), "handsfree_unavailable") from exc
    except Exception as exc:
        raise _error(503, str(exc), "handsfree_failed") from exc


@router.post("/voice/wake/stop", summary="Stop hands-free wake-word listening")
async def voice_wake_stop_route() -> Dict[str, Any]:
    try:
        return await run_in_threadpool(_runtime().stop_handsfree)
    except Exception as exc:
        raise _error(503, str(exc), "handsfree_failed") from exc


# ----------------------------------------------------------------------
# Image generation
# ----------------------------------------------------------------------
@router.post("/image/generate", summary="Run the existing Qwen-Image pipeline")
async def image_generate_route(body: ImageRequest) -> Dict[str, Any]:
    prompt = body.prompt.strip()
    if not prompt:
        raise _error(422, "Prompt must not be blank.", "invalid_input")
    try:
        return await run_in_threadpool(
            _runtime().generate_image,
            prompt,
            body.width,
            body.height,
            body.steps,
            body.seed,
        )
    except Exception as exc:
        raise _error(503, str(exc), "image_generation_failed") from exc


@router.get("/image/history")
def image_history_route(limit: int = Query(default=24, ge=1, le=200)) -> Dict[str, Any]:
    root = _image_output_dir()
    items: List[Dict[str, Any]] = []
    if not root.is_dir():
        return {"items": [], "count": 0, "root": str(root), "available": False}
    try:
        files = sorted(
            root.rglob("image_*.png"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:limit]
    except OSError as exc:
        return {"items": [], "count": 0, "root": str(root), "available": False, "error": str(exc)}

    for path in files:
        metadata: Dict[str, Any] = {}
        sidecar = path.with_suffix(".json")
        if sidecar.is_file():
            try:
                loaded = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    metadata = loaded
            except (OSError, ValueError):
                metadata = {}
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "filename": path.name,
                "path": str(path),
                "url": f"/api/image/file?path={quote(str(path))}",
                "created_at": stat.st_mtime,
                "size_bytes": stat.st_size,
                "metadata": metadata,
            }
        )
    return {"items": items, "count": len(items), "root": str(root), "available": True}


@router.get("/image/file", summary="Serve a generated image from the output directory")
def image_file_route(path: str = Query(..., min_length=1, max_length=4096)) -> FileResponse:
    root = _image_output_dir()
    try:
        candidate = Path(path).resolve()
    except (OSError, ValueError) as exc:
        raise _error(400, "Invalid image path.", "invalid_path") from exc

    try:
        candidate.relative_to(root)
    except ValueError:
        raise _error(403, "Requested file is outside the image output directory.", "path_denied")

    if not candidate.is_file() or candidate.suffix.lower() != ".png":
        raise _error(404, "Image not found.", "image_not_found")
    return FileResponse(candidate, media_type="image/png", filename=candidate.name)


# ----------------------------------------------------------------------
# Research
# ----------------------------------------------------------------------
@router.post("/research", summary="Run live web research through the existing agent")
async def research_route(body: ResearchRequest) -> Dict[str, Any]:
    query = body.query.strip()
    if not query:
        raise _error(422, "Query must not be blank.", "invalid_input")
    try:
        return await run_in_threadpool(_runtime().run_research, query)
    except Exception as exc:
        raise _error(503, str(exc), "research_failed") from exc


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
@router.get("/settings", summary="Redacted runtime configuration")
def settings_route() -> Dict[str, Any]:
    return _runtime().settings()


# ----------------------------------------------------------------------
# Workspace: real project surfaces only
# ----------------------------------------------------------------------
@router.get("/workspace")
def workspace_route() -> Dict[str, Any]:
    """Projects/documents that genuinely exist on disk and in config.

    The dashboard never invents filesystem entries: this reports the repository
    root, the configured knowledge documents, and generated output directories
    that actually exist.
    """
    runtime = _runtime()
    root = Path.cwd().resolve()
    rag_cfg = runtime.config.get("rag", {}) or {}
    documents_dir = Path(str(rag_cfg.get("documents_dir") or rag_cfg.get("index_dir") or "docs"))
    generated = _image_output_dir()

    def _exists(path: Path) -> Optional[Dict[str, Any]]:
        try:
            if not path.exists():
                return None
            stat = path.stat()
            return {
                "path": str(path),
                "name": path.name,
                "is_dir": path.is_dir(),
                "size_bytes": None if path.is_dir() else stat.st_size,
                "modified_at": stat.st_mtime,
            }
        except OSError:
            return None

    project_root = _exists(root) or {}
    return {
        "root": project_root,
        "projects": [
            {
                "id": "friday-v2",
                "name": "F.R.I.D.A.Y v2",
                "path": str(root),
                "status": "active",
                "kind": "repository",
                "detail": "Local AI assistant workspace",
            }
        ],
        "directories": [
            entry
            for entry in (
                _exists(documents_dir),
                _exists(generated),
                _exists(Path("data")),
                _exists(Path("logs")),
            )
            if entry
        ],
        "documents_dir": str(documents_dir),
        "rag": {
            "enabled": bool(rag_cfg.get("enabled")),
            "collection": rag_cfg.get("collection"),
        },
        "note": "Only paths that exist on disk are listed; no synthetic entries.",
    }


# ----------------------------------------------------------------------
# Knowledge (local RAG surface)
# ----------------------------------------------------------------------
_KNOWLEDGE_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".pdf", ".json", ".yaml", ".yml"}
_KNOWLEDGE_SKIP_DIRS = {".git", ".pytest_cache", ".ruff_cache", "node_modules", "models", "output", "logs", "data", ".data", "debug_audio", "frontend"}


@router.get("/knowledge/documents", summary="Files the local RAG index can actually see")
def knowledge_documents_route(limit: int = Query(default=100, ge=1, le=500)) -> Dict[str, Any]:
    runtime = _runtime()
    rag_cfg = runtime.config.get("rag", {}) or {}
    enabled = bool(rag_cfg.get("enabled"))
    source_dirs = [str(d) for d in (rag_cfg.get("source_dirs") or ["docs"])]
    documents: List[Dict[str, Any]] = []
    scanned: List[str] = []
    errors: List[str] = []

    for source in source_dirs[:10]:
        base = Path(source)
        if not base.exists():
            continue
        scanned.append(str(base.resolve()))
        try:
            if base.is_file():
                candidates = [base]
            else:
                candidates = []
                for path in base.rglob("*"):
                    if len(documents) >= limit:
                        break
                    if not path.is_file() or path.suffix.lower() not in _KNOWLEDGE_SUFFIXES:
                        continue
                    if any(part in _KNOWLEDGE_SKIP_DIRS for part in path.parts):
                        continue
                    candidates.append(path)
        except OSError as exc:
            errors.append(f"{source}: {exc}")
            continue
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            documents.append(
                {
                    "name": path.name,
                    "path": str(path.resolve()),
                    "suffix": path.suffix.lower(),
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
            if len(documents) >= limit:
                break
        if len(documents) >= limit:
            break

    documents.sort(key=lambda d: d["modified_at"], reverse=True)
    return {
        "enabled": enabled,
        "collection": rag_cfg.get("collection"),
        "source_dirs": scanned,
        "documents": documents,
        "count": len(documents),
        "errors": errors,
        "note": (
            "Files listed are visible to the local index. Retrieval still requires the "
            "RAG service to be reachable; no content is returned here."
        ),
    }


# ----------------------------------------------------------------------
# Persistent memory (Phase 2) — read-first, explicit mutation
# ----------------------------------------------------------------------
def _memory():
    return _runtime().memory_service()


@router.get("/memory/stats", summary="Persistent memory size and record counts")
def memory_stats_route() -> Dict[str, Any]:
    return _memory().stats()


@router.get("/memory/sessions", summary="List recent conversation sessions")
def memory_sessions_route(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source: Optional[str] = Query(default=None, max_length=32),
    from_ts: Optional[str] = Query(default=None, alias="from", max_length=40),
    to_ts: Optional[str] = Query(default=None, alias="to", max_length=40),
) -> Dict[str, Any]:
    return _memory().list_sessions(
        limit=limit, offset=offset, source=source, from_ts=from_ts, to_ts=to_ts
    )


@router.get("/memory/sessions/{session_id}", summary="Raw turns for one session")
def memory_session_route(session_id: str) -> Dict[str, Any]:
    payload = _memory().get_session(session_id)
    if payload is None:
        raise _error(404, f"No memory session {session_id!r}.", "memory_session_not_found")
    return payload


@router.delete("/memory/sessions/{session_id}", summary="Delete a session and its turns")
def memory_session_delete_route(session_id: str) -> Dict[str, Any]:
    result = _memory().delete_session(session_id)
    if not result.get("deleted"):
        raise _error(404, f"No memory session {session_id!r}.", "memory_session_not_found")
    return result


@router.get("/memory/search", summary="Search stored turns by keyword, meaning or date")
def memory_search_route(
    q: str = Query(default="", max_length=400),
    mode: str = Query(default="hybrid", max_length=16),
    from_ts: Optional[str] = Query(default=None, alias="from", max_length=40),
    to_ts: Optional[str] = Query(default=None, alias="to", max_length=40),
    topic: Optional[str] = Query(default=None, max_length=120),
    session_id: Optional[str] = Query(default=None, max_length=200),
    source: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=200),
) -> Dict[str, Any]:
    if mode not in ("hybrid", "keyword", "semantic"):
        raise _error(422, f"Unknown search mode {mode!r}.", "invalid_mode")
    return _memory().search(
        q,
        mode=mode,
        from_ts=from_ts,
        to_ts=to_ts,
        topic=topic,
        session_id=session_id,
        source=source,
        limit=limit,
    )


@router.get("/memory/facts", summary="List stored facts")
def memory_facts_route(
    q: str = Query(default="", max_length=200),
    category: Optional[str] = Query(default=None, max_length=64),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    return _memory().list_facts(
        q,
        category=category,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )


@router.post("/memory/facts", summary="Create or update a fact")
def memory_fact_create_route(body: MemoryFactRequest) -> Dict[str, Any]:
    record = _memory().upsert_fact(
        body.subject,
        body.predicate,
        body.object,
        category=body.category,
        confidence=body.confidence,
        source_message_id=body.source_message_id,
    )
    if record is None:
        raise _error(
            422,
            "Fact was not stored (blank fields or sensitive content).",
            "memory_fact_rejected",
        )
    return record.to_dict()


@router.get("/memory/facts/{fact_id}", summary="Read one fact with its revision history")
def memory_fact_route(fact_id: str) -> Dict[str, Any]:
    payload = _memory().get_fact(fact_id)
    if payload is None:
        raise _error(404, f"No fact {fact_id!r}.", "memory_fact_not_found")
    return payload


@router.post("/memory/facts/{fact_id}/correct", summary="Correct a fact (audited)")
def memory_fact_correct_route(fact_id: str, body: MemoryFactUpdateRequest) -> Dict[str, Any]:
    try:
        record = _memory().correct_fact(
            fact_id,
            subject=body.subject,
            predicate=body.predicate,
            object_value=body.object,
            category=body.category,
            confidence=body.confidence,
            reason=body.reason,
        )
    except ValueError as exc:
        raise _error(422, str(exc), "memory_fact_rejected") from exc
    if record is None:
        raise _error(404, f"No fact {fact_id!r}.", "memory_fact_not_found")
    return record.to_dict()


@router.delete("/memory/facts/{fact_id}", summary="Soft-delete a fact (or hard-delete)")
def memory_fact_delete_route(
    fact_id: str, hard: bool = Query(default=False)
) -> Dict[str, Any]:
    deleted = _memory().delete_fact(fact_id, hard=hard)
    if not deleted:
        raise _error(404, f"No fact {fact_id!r}.", "memory_fact_not_found")
    return {"deleted": True, "fact_id": fact_id, "hard": hard}


@router.post("/memory/facts/{fact_id}/restore", summary="Restore a soft-deleted fact")
def memory_fact_restore_route(fact_id: str) -> Dict[str, Any]:
    restored = _memory().restore_fact(fact_id)
    if not restored:
        raise _error(404, f"No fact {fact_id!r}.", "memory_fact_not_found")
    return {"restored": True, "fact_id": fact_id}


@router.get("/memory/tasks", summary="List resumable tasks")
def memory_tasks_route(
    state: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    records = _memory().list_tasks(state=state, limit=limit, offset=offset)
    return {"tasks": [record.to_dict() for record in records], "count": len(records)}


@router.post("/memory/tasks", summary="Create a resumable task record")
def memory_task_create_route(body: MemoryTaskRequest) -> Dict[str, Any]:
    record = _memory().create_task(
        body.goal,
        source_session_id=body.source_session_id,
        meta=body.meta or None,
    )
    if record is None:
        raise _error(422, "Task goal must not be blank.", "memory_task_rejected")
    return record.to_dict()


@router.get("/memory/tasks/{task_id}", summary="Read one task and its steps")
def memory_task_route(task_id: str) -> Dict[str, Any]:
    record = _memory().get_task(task_id)
    if record is None:
        raise _error(404, f"No task {task_id!r}.", "memory_task_not_found")
    return record.to_dict()


@router.post("/memory/tasks/{task_id}/cancel", summary="Cancel a resumable task")
def memory_task_cancel_route(task_id: str) -> Dict[str, Any]:
    record = _memory().cancel_task(task_id)
    if record is None:
        raise _error(404, f"No task {task_id!r}.", "memory_task_not_found")
    return record.to_dict()


@router.post("/memory/tasks/{task_id}/resume", summary="Resume a paused task")
def memory_task_resume_route(task_id: str) -> Dict[str, Any]:
    record = _memory().resume_task(task_id)
    if record is None:
        raise _error(404, f"No task {task_id!r}.", "memory_task_not_found")
    return record.to_dict()


@router.post("/memory/tasks/{task_id}/complete", summary="Mark a task complete")
def memory_task_complete_route(task_id: str) -> Dict[str, Any]:
    record = _memory().complete_task(task_id)
    if record is None:
        raise _error(404, f"No task {task_id!r}.", "memory_task_not_found")
    return record.to_dict()


@router.post("/memory/tasks/{task_id}/steps", summary="Append a step to a task")
def memory_task_step_add_route(
    task_id: str, body: MemoryTaskStepRequest
) -> Dict[str, Any]:
    step = _memory().add_task_step(
        task_id,
        body.action,
        target=body.target,
        idempotency_key=body.idempotency_key,
        status=body.status,
    )
    if step is None:
        raise _error(404, f"No task {task_id!r}.", "memory_task_not_found")
    return step.to_dict()


@router.patch(
    "/memory/tasks/{task_id}/steps/{step_id}", summary="Update a task step"
)
def memory_task_step_update_route(
    task_id: str, step_id: str, body: MemoryTaskStepUpdateRequest
) -> Dict[str, Any]:
    try:
        step = _memory().update_task_step(
            step_id,
            status=body.status,
            result=body.result,
            verification_status=body.verification_status,
            error=body.error,
        )
    except ValueError as exc:
        raise _error(422, str(exc), "memory_step_rejected") from exc
    if step is None or step.task_id != task_id:
        raise _error(404, f"No step {step_id!r} on task {task_id!r}.", "memory_step_not_found")
    return step.to_dict()


@router.post("/memory/prune", summary="Prune old sessions (dry-run by default)")
def memory_prune_route(body: MemoryPruneRequest) -> Dict[str, Any]:
    return _memory().prune(
        dry_run=body.dry_run, retention_days=body.retention_days
    )


@router.post("/memory/backup", summary="Write a consistent SQLite backup")
def memory_backup_route() -> Dict[str, Any]:
    destination = _memory().backup()
    if destination is None:
        raise _error(503, "Memory backup failed.", "memory_backup_failed")
    return {"backup": destination, "integrity": _memory().integrity_check()}


# ----------------------------------------------------------------------
# Error envelope
# ----------------------------------------------------------------------
def install_error_handler(app) -> None:
    """Return structured JSON errors for every API failure."""

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            body = detail
        else:
            body = {"error": {"type": "http_error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_input",
                    "message": "Request validation failed.",
                    "fields": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc) or "Unhandled server error.",
                }
            },
        )
