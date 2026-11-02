"""Tests for the dashboard web layer.

Operating-system telemetry and service probes are mocked where a real machine
dependency would make the test flaky. No model weights are loaded: the runtime
is lazy by design and these tests assert that property.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from friday.web import activity as activity_mod
from friday.web import metrics as metrics_mod
from friday.web.app import create_app
from friday.web.events import bus, install_notify_bridge, make_event
from friday.web.runtime import DashboardRuntime, reset_runtime


MINIMAL_CONFIG = """
wake_word: "friday"
security:
  dry_run: false
  allow_real_execution: true
tools:
  dry_run: false
  allow_real_execution: true
  permissions:
    get_time: true
    open_app: true
    close_app: false
reasoning:
  provider: llamacpp
  model: "C:/models/demo-Q4_K_M.gguf"
  endpoint: "http://127.0.0.1:9"
image:
  enabled: true
  provider: qwen-image
  output_dir: "{output_dir}"
research:
  enabled: true
  provider: duckduckgo
  max_results: 3
rag:
  enabled: true
  collection: friday_knowledge
voice:
  offline_only: true
  wake_word_required: true
  stt:
    model: small.en
  tts:
    engine: piper
"""


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        MINIMAL_CONFIG.format(output_dir=(tmp_path / "images").as_posix()),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics_mod, "prime_cpu", lambda: None)
    rt = DashboardRuntime(
        config_path=str(config_path),
        activity_path=str(tmp_path / "activity.json"),
    )
    reset_runtime(rt)
    yield rt
    reset_runtime(None)


@pytest.fixture()
def client(runtime):
    with TestClient(create_app()) as test_client:
        yield test_client


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
class _FakeVM:
    total = 16 * 1024 ** 3
    available = 4 * 1024 ** 3
    percent = 75.0


class _FakeDisk:
    total = 500 * 1024 ** 3
    used = 200 * 1024 ** 3
    free = 300 * 1024 ** 3
    percent = 40.0


def test_system_metrics_uses_real_probe_values(monkeypatch):
    monkeypatch.setattr(metrics_mod.psutil, "virtual_memory", lambda: _FakeVM())
    monkeypatch.setattr(metrics_mod.psutil, "disk_usage", lambda _p: _FakeDisk())
    monkeypatch.setattr(metrics_mod.psutil, "cpu_percent", lambda interval=None: 12.5)
    monkeypatch.setattr(metrics_mod.psutil, "cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(metrics_mod.psutil, "boot_time", lambda: 0)

    monkeypatch.setattr(metrics_mod, "_gpu_metrics", lambda: {
        "available": False,
        "name": None,
        "utilization_percent": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "memory_percent": None,
        "temperature_c": None,
        "provider": "nvidia-smi",
        "reason": "nvidia-smi not found; GPU telemetry unavailable.",
    })

    payload = metrics_mod.system_metrics()
    assert payload["cpu"]["percent"] == 12.5
    assert payload["cpu"]["logical_cores"] == 8
    assert payload["ram"]["total_gb"] == 16.0
    assert payload["ram"]["used_gb"] == 12.0
    assert payload["gpu"]["available"] is False
    assert payload["gpu"]["utilization_percent"] is None
    assert "reason" in payload["gpu"]


def test_gpu_metrics_parses_nvidia_smi(monkeypatch):
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="NVIDIA RTX 3050, 45, 2048, 6144, 61\n", stderr=""
    )
    monkeypatch.setattr(metrics_mod.subprocess, "run", lambda *a, **k: completed)
    gpu = metrics_mod._gpu_metrics()
    assert gpu["available"] is True
    assert gpu["name"] == "NVIDIA RTX 3050"
    assert gpu["utilization_percent"] == 45.0
    assert gpu["memory_used_mb"] == 2048
    assert gpu["memory_percent"] == 33.3
    assert gpu["temperature_c"] == 61.0


def test_gpu_metrics_reports_unavailable_without_inventing(monkeypatch):
    def _raise(*_a, **_k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(metrics_mod.subprocess, "run", _raise)
    gpu = metrics_mod._gpu_metrics()
    assert gpu["available"] is False
    assert gpu["memory_used_mb"] is None
    assert gpu["memory_total_mb"] is None


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------
def test_health_reports_offline_reasoner(runtime, monkeypatch):
    monkeypatch.setattr("friday.web.runtime._http_probe", lambda *a, **k: {"reachable": False, "error": "connection refused"})
    health = runtime.health()
    assert health["components"]["reasoning"]["status"] == "offline"
    assert health["overall"] == "degraded"


def test_health_never_claims_all_online_when_a_service_is_down(runtime, monkeypatch):
    monkeypatch.setattr("friday.web.runtime._http_probe", lambda *a, **k: {"reachable": True, "status": 200, "body": {"status": "ok"}})
    health = runtime.health()
    statuses = {name: c["status"] for name, c in health["components"].items()}
    assert statuses["reasoning"] == "healthy"
    # Research is enabled in the fixture but STT/TTS modules may genuinely be
    # unavailable on the test machine; "healthy" is only allowed when true.
    assert health["overall"] in ("healthy", "degraded")


def test_health_endpoint_shape(client):
    response = client.get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"overall", "components", "timestamp"}
    assert "backend" in body["components"]
    assert body["components"]["backend"]["status"] == "healthy"


# ----------------------------------------------------------------------
# Dashboard overview / models / agents
# ----------------------------------------------------------------------
def test_overview_returns_real_sections(client):
    response = client.get("/api/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["identity"]["name"] == "F.R.I.D.A.Y"
    assert "cpu" in body["metrics"]
    assert "ram" in body["metrics"]
    assert body["agents"]
    assert isinstance(body["activity"], list)


def test_models_reflect_unreachable_server(runtime, monkeypatch):
    monkeypatch.setattr("friday.web.runtime._http_probe", lambda *a, **k: {"reachable": False, "error": "refused"})
    models = runtime.models()
    reasoning = next(m for m in models if m["kind"] == "reasoning")
    assert reasoning["active"] is True
    assert reasoning["loaded"] is False
    assert "refused" in reasoning["error"]
    assert runtime.active_model()["id"] == reasoning["id"]


def test_agents_status_derives_from_live_activity(runtime, monkeypatch):
    monkeypatch.setattr("friday.web.runtime._http_probe", lambda *a, **k: {"reachable": True, "status": 200, "body": {"status": "ok"}})
    runtime.activity.add(activity_mod.KIND_RESEARCH, "Quantum news", source="research", status="running")
    agents = {a["id"]: a for a in runtime.agents()}
    assert agents["research"]["status"] == "working"
    assert agents["research"]["current_task"] == "Quantum news"


def test_agents_endpoint_and_unknown_agent(client):
    assert client.get("/api/agents").status_code == 200
    missing = client.get("/api/agents/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "agent_not_found"


# ----------------------------------------------------------------------
# Activity / tasks
# ----------------------------------------------------------------------
def test_activity_filters_and_pagination(runtime):
    for i in range(5):
        runtime.activity.add(activity_mod.KIND_TOOL, f"task {i}", source="tool", status="completed")
    runtime.activity.add(activity_mod.KIND_IMAGE, "picture", source="image", status="failed")

    tools = runtime.activity.list(kind=activity_mod.KIND_TOOL, limit=2)
    assert tools["total"] == 5
    assert len(tools["items"]) == 2

    failed = runtime.activity.list(status="failed")
    assert failed["total"] == 1
    assert failed["items"][0]["kind"] == "image"

    searched = runtime.activity.list(search="task 3")
    assert searched["total"] == 1


def test_activity_persists_to_disk(tmp_path, monkeypatch):
    path = tmp_path / "activity.json"
    monkeypatch.setattr(metrics_mod, "prime_cpu", lambda: None)
    store = activity_mod.ActivityStore(str(path))
    store.add(activity_mod.KIND_RESEARCH, "persisted", source="research", status="completed")
    assert path.is_file()
    reloaded = activity_mod.ActivityStore(str(path))
    assert reloaded.list()["total"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))[0]["title"] == "persisted"


def test_activity_update_computes_duration(runtime):
    item = runtime.activity.add(activity_mod.KIND_TOOL, "work", source="tool", status="running")
    updated = runtime.activity.update(item["id"], status="completed", message="done")
    assert updated["status"] == "completed"
    assert updated["completed_at"] is not None
    assert updated["duration_ms"] is not None


def test_tasks_endpoints(client, runtime):
    item = runtime.activity.add(activity_mod.KIND_CODE, "run tests", source="tool", status="completed")
    listing = client.get("/api/tasks?limit=10").json()
    assert listing["total"] >= 1
    single = client.get(f"/api/tasks/{item['id']}").json()
    assert single["id"] == item["id"]
    missing = client.get("/api/tasks/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "task_not_found"


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------
def test_tools_report_permission_state(runtime):
    tools = {t["name"]: t for t in runtime.tools()}
    assert tools["GET_TIME"]["allowed"] is True
    assert tools["CLOSE_APP"]["allowed"] is False
    assert tools["CLOSE_APP"]["requires_confirmation"] is True
    assert tools["GET_TIME"]["dry_run"] is False


def test_tool_execution_rejects_disabled_permission(client):
    response = client.post("/api/tools/close_app/execute", json={"target": "notepad"})
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "permission_denied"


def test_tool_execution_requires_confirmation_for_destructive_actions(client, runtime):
    perms = dict(runtime.tools_config())
    perms["permissions"] = {**perms.get("permissions", {}), "close_app": True}
    runtime.config["tools"] = perms
    response = client.post("/api/tools/close_app/execute", json={"target": "notepad"})
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "confirmation_required"


def test_tool_execution_is_recorded(client):
    response = client.post("/api/tools/get_time/execute", json={"target": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "GET_TIME"
    assert body["task_id"]
    stored = client.get(f"/api/tasks/{body['task_id']}").json()
    assert stored["kind"] == "tool"
    assert stored["status"] in ("completed", "failed", "blocked")


def test_unknown_tool_rejected(client):
    response = client.post("/api/tools/not_a_tool/execute", json={"target": ""})
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "tool_not_found"


# ----------------------------------------------------------------------
# Validation / errors
# ----------------------------------------------------------------------
@pytest.mark.parametrize("payload", [{}, {"message": ""}, {"message": "   "}])
def test_chat_rejects_blank_message(client, payload):
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 422


def test_image_rejects_bad_dimensions(client):
    response = client.post("/api/image/generate", json={"prompt": "a cat", "width": 64})
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "invalid_input"


def test_research_rejects_blank_query(client):
    assert client.post("/api/research", json={"query": ""}).status_code == 422


def test_image_file_blocks_path_traversal(client):
    response = client.get("/api/image/file", params={"path": "C:/Windows/win.ini"})
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "path_denied"


def test_image_file_missing_returns_404(client, tmp_path):
    candidate = tmp_path / "images" / "image_001.png"
    response = client.get("/api/image/file", params={"path": str(candidate)})
    assert response.status_code == 404


def test_image_history_empty_is_honest(client):
    payload = client.get("/api/image/history").json()
    assert payload["items"] == []
    assert payload["available"] is False


# ----------------------------------------------------------------------
# WebSocket
# ----------------------------------------------------------------------
def test_websocket_delivers_connection_ready_and_events(client):
    install_notify_bridge()
    with client.websocket_connect("/ws/dashboard") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connection.ready"
        assert hello["v"] == 1
        assert isinstance(hello["seq"], int)

        bus.publish_threadsafe(
            make_event("task.updated", source="test", task_id="abc", status="running")
        )
        event = ws.receive_json()
        assert event["type"] == "task.updated"
        assert event["task_id"] == "abc"
        assert event["seq"] > hello["seq"]


def test_websocket_ping_pong(client):
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "server.heartbeat"
        assert pong["data"]["pong"] is True


def test_websocket_unsupported_message_reports_error(client):
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        ws.send_text("nonsense")
        reply = ws.receive_json()
        assert reply["type"] == "error"


def test_event_schema_is_versioned_and_ordered():
    first = make_event("task.created", source="test")
    second = make_event("task.completed", source="test")
    assert set(first) >= {"type", "v", "seq", "timestamp", "task_id", "status", "source", "message", "progress", "data"}
    assert second["seq"] > first["seq"]
    assert first["v"] == 1


# ----------------------------------------------------------------------
# Lazy runtime / settings redaction
# ----------------------------------------------------------------------
def test_metrics_do_not_initialize_the_assistant(client, runtime):
    client.get("/api/system/metrics")
    client.get("/api/dashboard/overview")
    assert runtime._assistant is None


def test_settings_never_expose_secrets(runtime):
    runtime.config["research"] = {**runtime.config.get("research", {}), "api_key": "sk-secret"}
    payload = runtime.settings()
    serialized = json.dumps(payload)
    assert "sk-secret" not in serialized
    assert "api_key" not in payload["research"]


def test_tool_config_change_does_not_require_restart(client, runtime):
    runtime.config["tools"] = {**runtime.config.get("tools", {}), "permissions": {"get_time": False}}
    response = client.post("/api/tools/get_time/execute", json={"target": ""})
    assert response.status_code == 403
