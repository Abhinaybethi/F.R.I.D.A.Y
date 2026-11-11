/** Shared REST client. Every dashboard call goes through here. */

import type {
  AgentInfo,
  ChatResponse,
  HandsFreeState,
  ImageHistoryItem,
  ImageResult,
  KnowledgeResponse,
  ModelInfo,
  Overview,
  ResearchResponse,
  SettingsResponse,
  SystemHealth,
  SystemMetrics,
  TaskItem,
  TaskList,
  ToolExecution,
  ToolInfo,
  VoiceState,
  WorkspaceResponse,
} from "./types";

/** Same-origin by default (Vite proxies /api to the local backend in dev). */
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  readonly type: string;
  readonly status: number;
  readonly fields?: unknown;

  constructor(message: string, type: string, status: number, fields?: unknown) {
    super(message);
    this.name = "ApiError";
    this.type = type;
    this.status = status;
    this.fields = fields;
  }
}

export function apiBaseUrl(): string {
  if (BASE) return BASE;
  return typeof window === "undefined" ? "http://127.0.0.1:8420" : window.location.origin;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
  params?: Record<string, string | number | boolean | undefined>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, timeoutMs = 20_000, signal, params } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  let abortListener: (() => void) | undefined;
  if (signal) {
    if (signal.aborted) controller.abort();
    abortListener = () => controller.abort();
    signal.addEventListener("abort", abortListener, { once: true });
  }

  try {
    const suffix = params ? query(params) : "";
    const response = await fetch(`${BASE}${path}${suffix}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });

    const text = await response.text();
    let payload: unknown = undefined;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }

    if (!response.ok) {
      const envelope = payload as { error?: { type?: string; message?: string; fields?: unknown } } | undefined;
      const message = envelope?.error?.message ?? `Request failed with HTTP ${response.status}`;
      throw new ApiError(
        message,
        envelope?.error?.type ?? "http_error",
        response.status,
        envelope?.error?.fields,
      );
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if ((error as Error)?.name === "AbortError") {
      throw new ApiError(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s.`,
        "timeout",
        0,
      );
    }
    throw new ApiError(
      error instanceof Error ? error.message : "Backend unreachable.",
      "network_error",
      0,
    );
  } finally {
    window.clearTimeout(timer);
    if (signal && abortListener) signal.removeEventListener("abort", abortListener);
  }
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

export const api = {
  health: () =>
    request<{ ok: boolean; state: string; identity: Overview["identity"]; warnings: string[] }>(
      "/api/health",
    ),

  overview: (signal?: AbortSignal) =>
    request<Overview>("/api/dashboard/overview", { signal, timeoutMs: 30_000 }),

  metrics: (signal?: AbortSignal) =>
    request<SystemMetrics>("/api/system/metrics", { signal, timeoutMs: 10_000 }),

  systemHealth: (signal?: AbortSignal) =>
    request<SystemHealth>("/api/system/health", { signal, timeoutMs: 20_000 }),

  models: () => request<{ models: ModelInfo[]; active: ModelInfo | null; count: number }>("/api/models"),

  activeModel: () => request<{ active: ModelInfo | null }>("/api/models/active"),

  agents: () => request<{ agents: AgentInfo[]; count: number }>("/api/agents"),

  agent: (id: string) =>
    request<{ agent: AgentInfo; history: TaskItem[] }>(`/api/agents/${encodeURIComponent(id)}`),

  tasks: (params: {
    kind?: string;
    status?: string;
    source?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {}) => request<TaskList>(`/api/tasks${query(params)}`),

  task: (id: string) => request<TaskItem>(`/api/tasks/${encodeURIComponent(id)}`),

  activity: (params: {
    kind?: string;
    status?: string;
    source?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {}) => request<TaskList>(`/api/activity${query(params)}`),

  tools: () => request<{ tools: ToolInfo[]; count: number; enabled: number }>("/api/tools"),

  executeTool: (
    id: string,
    payload: { target?: string; arguments?: Record<string, unknown>; confirm?: boolean },
  ) =>
    request<ToolExecution>(`/api/tools/${encodeURIComponent(id)}/execute`, {
      method: "POST",
      body: payload,
      timeoutMs: 120_000,
    }),

  chat: (message: string, signal?: AbortSignal) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: { message },
      timeoutMs: 240_000,
      signal,
    }),

  voiceState: () => request<VoiceState>("/api/voice/state"),

  transcribeAudio: async (wav: Blob): Promise<{
    text: string;
    duration_seconds: number;
    rtf: number;
    device?: string;
    model?: string;
  }> => {
    const response = await fetch(`${BASE}/api/voice/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
      cache: "no-store",
    });
    const text = await response.text();
    let payload: unknown;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      const envelope = payload as { error?: { type?: string; message?: string } } | undefined;
      throw new ApiError(
        envelope?.error?.message ?? `Transcription failed with HTTP ${response.status}`,
        envelope?.error?.type ?? "http_error",
        response.status,
      );
    }
    return payload as { text: string; duration_seconds: number; rtf: number; device?: string; model?: string };
  },

  speak: async (text: string): Promise<Blob> => {
    const response = await fetch(`${BASE}/api/voice/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      cache: "no-store",
    });
    if (!response.ok) {
      const raw = await response.text();
      let message = `Speech synthesis failed with HTTP ${response.status}`;
      try {
        const envelope = JSON.parse(raw) as { error?: { message?: string } };
        message = envelope?.error?.message ?? message;
      } catch {
        /* keep default message */
      }
      throw new ApiError(message, "tts_failed", response.status);
    }
    return response.blob();
  },

  startCapture: () =>
    request<{ recording: boolean; sample_rate: number; device: string }>(
      "/api/voice/capture/start",
      { method: "POST", timeoutMs: 30_000 },
    ),

  stopCapture: () =>
    request<{ text: string; duration_seconds: number; rtf: number; device?: string; model?: string }>(
      "/api/voice/capture/stop",
      { method: "POST", timeoutMs: 240_000 },
    ),

  startHandsFree: () =>
    request<HandsFreeState>("/api/voice/wake/start", {
      method: "POST",
      timeoutMs: 30_000,
    }),

  stopHandsFree: () =>
    request<HandsFreeState>("/api/voice/wake/stop", {
      method: "POST",
      timeoutMs: 15_000,
    }),

  generateImage: (payload: {
    prompt: string;
    width?: number;
    height?: number;
    steps?: number;
    seed?: number;
  }) =>
    request<ImageResult>("/api/image/generate", {
      method: "POST",
      body: payload,
      // Local CPU/GPU generation is slow: the backend timeout is 900s.
      timeoutMs: 960_000,
    }),

  imageHistory: () =>
    request<{
      items: ImageHistoryItem[];
      count: number;
      root: string;
      available: boolean;
      error?: string;
    }>("/api/image/history"),

  research: (queryText: string) =>
    request<ResearchResponse>("/api/research", {
      method: "POST",
      body: { query: queryText },
      timeoutMs: 180_000,
    }),

  knowledge: () => request<KnowledgeResponse>("/api/knowledge/documents"),

  workspace: () => request<WorkspaceResponse>("/api/workspace"),

  settings: () => request<SettingsResponse>("/api/settings"),
  memoryStats: () => request<{ stats: any; health: any; settings: any }>("/api/memory/stats"),
  memorySessions: (params?: { source?: string; from_ts?: string; to_ts?: string }) =>
    request("/api/memory/sessions", { params, timeoutMs: 30_000 }),
  memorySearch: (
    queryText: string,
    mode?: string,
    params?: { from_ts?: string; to_ts?: string; topic?: string; session_id?: string; source?: string; limit?: number },
  ) =>
    request("/api/memory/search" + query({ q: queryText, mode, ...params }), { timeoutMs: 30_000 }),
  memoryFacts: (params?: { q?: string; category?: string; include_deleted?: boolean; limit?: number; offset?: number }) =>
    request("/api/memory/facts", { params, timeoutMs: 30_000 }),
  memoryTasks: (params?: { state?: string; limit?: number; offset?: number }) =>
    request("/api/memory/tasks", { params, timeoutMs: 30_000 }),
  memoryPrune: (body: { dry_run?: boolean; retention_days?: number }) =>
    request<{ enabled: boolean; dry_run: boolean; deleted: number; session_ids: string[]; retention_days: number; cutoff: string }>("/api/memory/prune", { method: "POST", body, timeoutMs: 30_000 }),
  memoryBackup: () => request<{ backup: string; integrity: string }>("/api/memory/backup", { method: "POST", timeoutMs: 30_000 }),
  /**
   * Search F.R.I.D.A.Y's stored knowledge/memory and normalise the hits into
   * `{ id, text, model }` rows for the dashboard UI.
   */
  search: async (
    queryText: string,
    params?: { mode?: string; topic?: string; source?: string; limit?: number },
  ): Promise<Array<{ id: string; text: string; model: string }>> => {
    const payload = await request<{ results?: Array<Record<string, unknown>> }>(
      "/api/memory/search" + query({ q: queryText, ...params }),
      { timeoutMs: 30_000 },
    );
    const rows = Array.isArray(payload?.results) ? payload.results : [];
    return rows.map((row, index) => {
      const session = row.session as { source?: string; title?: string } | undefined;
      return {
        id: String(row.id ?? index),
        text: String(row.raw_text ?? row.response_text ?? row.text ?? ""),
        model: String(row.match ?? session?.source ?? session?.title ?? "memory"),
      };
    });
  },
};