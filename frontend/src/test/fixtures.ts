/** Shared test fixtures + fetch mocking. Values mirror real backend shapes. */

import { vi } from "vitest";

import type {
  AgentInfo,
  ModelInfo,
  Overview,
  SettingsResponse,
  SystemHealth,
  SystemMetrics,
  TaskItem,
  ToolInfo,
} from "../lib/types";

export function metrics(overrides: Partial<SystemMetrics> = {}): SystemMetrics {
  return {
    timestamp: "2026-11-02T10:00:00+00:00",
    cpu: { percent: 12.4, logical_cores: 12, physical_cores: 8 },
    ram: { total_gb: 16, used_gb: 10.1, available_gb: 5.9, percent: 63.2 },
    disk: { total_gb: 500, used_gb: 200, free_gb: 300, percent: 40 },
    gpu: {
      available: true,
      name: "NVIDIA GeForce RTX 3050 6GB Laptop GPU",
      utilization_percent: 21,
      memory_used_mb: 1200,
      memory_total_mb: 6144,
      memory_percent: 19.5,
      temperature_c: 54,
      provider: "nvidia-smi",
      reason: "",
    },
    uptime_seconds: 7200,
    source: "psutil+nvidia-smi",
    ...overrides,
  };
}

export function health(overrides: Partial<SystemHealth> = {}): SystemHealth {
  return {
    overall: "degraded",
    components: {
      backend: { status: "healthy", detail: "FastAPI process alive · 2.0.0" },
      config: { status: "healthy", detail: "configuration valid" },
      reasoning: { status: "healthy", detail: "llamacpp reachable", provider: "llamacpp", endpoint: "http://127.0.0.1:8080" },
      research: { status: "healthy", detail: "provider=duckduckgo" },
      rag: { status: "healthy", detail: "collection=friday_knowledge" },
      stt: { status: "healthy", detail: "faster-whisper · small.en" },
      tts: { status: "healthy", detail: "piper engine" },
      image: { status: "healthy", detail: "cuda · RTX 3050", device: "cuda", vram_total_mb: 6144 },
      websocket: { status: "healthy", detail: "1 dashboard client(s) connected", clients: 1 },
      microphone: { status: "healthy", detail: "2 input device(s)" },
    },
    timestamp: "2026-11-02T10:00:00+00:00",
    ...overrides,
  };
}

export const ACTIVE_MODEL: ModelInfo = {
  id: "reasoning:llamacpp",
  name: "Bonsai-8B-Q1_0.gguf",
  family: "llama.cpp",
  kind: "reasoning",
  provider: "llamacpp",
  path: "C:/AI/models/Bonsai-8B-Q1_0.gguf",
  quantization: "Q1_0",
  active: true,
  loaded: true,
  health: "healthy",
  context_window: 2048,
  endpoint: "http://127.0.0.1:8080",
  error: "",
};

export const AGENTS: AgentInfo[] = [
  {
    id: "reasoner",
    name: "Local Reasoner",
    description: "Routes and answers requests.",
    source: "chat",
    status: "idle",
    current_task: null,
    current_task_id: null,
    last_activity: "2026-11-02T09:59:00+00:00",
    last_status: "completed",
    last_error: "",
    capabilities: ["chat", "intent routing"],
  },
  {
    id: "research",
    name: "Research Agent",
    description: "Runs live web research.",
    source: "research",
    status: "idle",
    current_task: null,
    current_task_id: null,
    last_activity: null,
    last_status: null,
    last_error: "",
    capabilities: ["web search"],
  },
];

export const TOOLS: ToolInfo[] = [
  {
    name: "GET_TIME",
    id: "get_time",
    permission_key: "get_time",
    allowed: true,
    dry_run: false,
    requires_confirmation: false,
    available: true,
  },
  {
    name: "CLOSE_APP",
    id: "close_app",
    permission_key: "close_app",
    allowed: false,
    dry_run: false,
    requires_confirmation: true,
    available: false,
  },
];

export function task(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    id: "task-1",
    kind: "tool",
    title: "GET_TIME",
    source: "tool",
    status: "completed",
    message: "It is 10:00.",
    progress: null,
    error: "",
    created_at: "2026-11-02T09:58:00+00:00",
    updated_at: "2026-11-02T09:58:01+00:00",
    completed_at: "2026-11-02T09:58:01+00:00",
    started_ts: 1762077480,
    duration_ms: 120,
    meta: {},
    ...overrides,
  };
}

export function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    identity: { name: "F.R.I.D.A.Y", version: "2.0.0", platform: "win32", uptime_seconds: 7200 },
    state: "ready",
    metrics: metrics(),
    health: health(),
    active_model: ACTIVE_MODEL,
    agents: AGENTS,
    activity: [task()],
    counts: { total: 3, running: 0, completed: 2, failed: 1 },
    warnings: [],
    timestamp: "2026-11-02T10:00:00+00:00",
    ...overrides,
  };
}

export const SETTINGS: SettingsResponse = {
  identity: { name: "F.R.I.D.A.Y", version: "2.0.0", platform: "win32", uptime_seconds: 7200 },
  backend_url: "http://127.0.0.1:8420",
  mode: "local-first",
  state: "ready",
  warnings: [],
  security: { dry_run: false, allow_real_execution: true },
  reasoning: { provider: "llamacpp", model: "C:/AI/models/Bonsai-8B-Q1_0.gguf", endpoint: "http://127.0.0.1:8080", timeout: 30 },
  image: { provider: "qwen-image", width: 768, height: 768, steps: 8, device: "auto", timeout: 900 },
  voice: { offline_only: true, wake_word_required: true, stt_model: "small.en", tts_engine: "piper" },
  research: { enabled: true, provider: "duckduckgo", max_results: 5 },
  monitoring: { refresh_interval_ms: 1500 },
};

export const VOICE = {
  state: "IDLE",
  capture_active: false,
  microphone: { available: true, detail: "2 input device(s)" },
  pipeline: ["IDLE", "LISTENING", "PROCESSING", "EXECUTING", "RESPONDING"],
  capture_supported: false,
  reason: "Live microphone capture is owned by the desktop voice runtime.",
};

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export type RouteMap = Record<string, () => unknown>;

export function installFetchMock(routes: RouteMap) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(raw, "http://localhost").pathname;
    const handler = routes[path];
    if (!handler) {
      return jsonResponse({ error: { type: "not_found", message: `No mock for ${path}` } }, 404);
    }
    return jsonResponse(handler());
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

export function defaultRoutes(overrides: RouteMap = {}): RouteMap {
  return {
    "/api/dashboard/overview": () => overview(),
    "/api/system/metrics": () => metrics(),
    "/api/system/health": () => health(),
    "/api/models": () => ({ models: [ACTIVE_MODEL], active: ACTIVE_MODEL, count: 1 }),
    "/api/models/active": () => ({ active: ACTIVE_MODEL }),
    "/api/agents": () => ({ agents: AGENTS, count: AGENTS.length }),
    "/api/agents/reasoner": () => ({ agent: AGENTS[0], history: [task()] }),
    "/api/tools": () => ({ tools: TOOLS, count: TOOLS.length, enabled: 1 }),
    "/api/voice/state": () => VOICE,
    "/api/settings": () => SETTINGS,
    "/api/activity": () => ({ total: 1, items: [task()], counts: { total: 3, running: 0, completed: 2, failed: 1 } }),
    "/api/tasks": () => ({ total: 1, items: [task()] }),
    "/api/image/history": () => ({ items: [], count: 0, root: "output/generated_images", available: false }),
    "/api/knowledge/documents": () => ({
      enabled: true,
      collection: "friday_knowledge",
      source_dirs: ["docs"],
      documents: [],
      count: 0,
      errors: [],
      note: "metadata only",
    }),
    "/api/workspace": () => ({
      root: { path: "C:/repo", name: "F.R.I.D.A.Y v2" },
      projects: [],
      directories: [],
      documents_dir: "docs",
      rag: { enabled: true, collection: "friday_knowledge" },
      note: "real paths only",
    }),
    ...overrides,
  };
}
