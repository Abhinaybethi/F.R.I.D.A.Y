"""FastAPI application factory for the F.R.I.D.A.Y dashboard.

Design constraints honoured here:

* The server binds to ``127.0.0.1`` only — this is a local-first desktop app.
* A single shared WebSocket broadcaster fans out real events; each client gets
  its own bounded queue, so a slow client can never grow memory without bound.
* Metrics/health endpoints never load models. The runtime stays lazy.
* Shutdown stops any model server the dashboard itself started.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from friday.web.events import bus, event_types, install_notify_bridge, make_event
from friday.web.metrics import prime_cpu
from friday.web.routes import install_error_handler, router
from friday.web.runtime import get_runtime

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = Path(os.environ.get("FRIDAY_FRONTEND_DIST") or (REPO_ROOT / "frontend" / "dist"))

HEARTBEAT_SECONDS = 15.0
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8420",
    "http://127.0.0.1:8420",
]


class ConnectionRegistry:
    """Tracks live dashboard sockets so the UI can show a real client count."""

    def __init__(self) -> None:
        self._clients: set[str] = set()
        self._lock = asyncio.Lock()

    async def add(self, client_id: str) -> int:
        async with self._lock:
            self._clients.add(client_id)
            return len(self._clients)

    async def remove(self, client_id: str) -> int:
        async with self._lock:
            self._clients.discard(client_id)
            return len(self._clients)

    @property
    def count(self) -> int:
        return len(self._clients)


connections = ConnectionRegistry()


async def _heartbeat() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await bus.publish(
            make_event(
                "server.heartbeat",
                source="backend",
                status="ok",
                data={
                    "clients": connections.count,
                    "subscribers": bus.subscriber_count,
                },
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    bus.bind_loop(loop)
    prime_cpu()
    install_notify_bridge()
    runtime = get_runtime()
    app.state.runtime = runtime
    heartbeat = asyncio.create_task(_heartbeat(), name="dashboard-heartbeat")
    try:
        yield
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await asyncio.get_running_loop().run_in_executor(None, runtime.shutdown)


def create_app() -> FastAPI:
    app = FastAPI(
        title="F.R.I.D.A.Y Dashboard API",
        version="1.0.0",
        description="Local-first dashboard over the real F.R.I.D.A.Y services.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    install_error_handler(app)
    app.include_router(router)

    # --------------------------------------------------------------
    # WebSocket
    # --------------------------------------------------------------
    @app.websocket("/ws/dashboard")
    async def dashboard_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = bus.subscribe()
        client_id = f"ws-{id(websocket)}"
        clients = await connections.add(client_id)

        hello = make_event(
            "connection.ready",
            source="backend",
            status="connected",
            message="Dashboard connected",
            data={
                "clients": clients,
                "schema_version": 1,
                "types": event_types(),
            },
        )

        async def send_loop() -> None:
            await websocket.send_json(hello)
            while True:
                event = await queue.get()
                await websocket.send_json(event)

        async def receive_loop() -> None:
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_json(
                        make_event("server.heartbeat", source="backend", status="ok", data={"pong": True})
                    )
                else:
                    await websocket.send_json(
                        make_event(
                            "error",
                            source="backend",
                            status="error",
                            message="Unsupported client message.",
                        )
                    )

        send_task = asyncio.create_task(send_loop())
        recv_task = asyncio.create_task(receive_loop())
        try:
            done, pending = await asyncio.wait(
                {send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            for task in done:
                with contextlib.suppress(WebSocketDisconnect, RuntimeError, Exception):
                    task.result()
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(queue)
            remaining = await connections.remove(client_id)
            with contextlib.suppress(Exception):
                await websocket.close()

    # --------------------------------------------------------------
    # Static frontend (built Vite bundle) or a helpful placeholder
    # --------------------------------------------------------------
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        app.mount(
            "/assets",
            StaticFiles(directory=str(FRONTEND_DIST / "assets")),
            name="assets",
        )

        @app.get("/", include_in_schema=False)
        async def spa_root() -> FileResponse:
            return FileResponse(index_file)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "ws/")):
                return JSONResponse({"error": {"type": "not_found", "message": "Unknown endpoint."}}, status_code=404)
            candidate = FRONTEND_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)
    else:

        @app.get("/", include_in_schema=False)
        async def build_hint() -> Dict[str, Any]:
            return {
                "service": "F.R.I.D.A.Y Dashboard API",
                "status": "backend running",
                "frontend": "not built",
                "hint": "Run `npm install && npm run build` in ./frontend, then restart.",
                "api": "/api/dashboard/overview",
                "docs": "/api/docs",
            }

    return app


app = create_app()
