/**
 * Dashboard state provider.
 *
 * REST bootstraps the first paint; lightweight metrics poll on a configurable
 * interval; every other state change arrives over the shared WebSocket. No
 * value in this store is invented — missing backend data stays missing and is
 * rendered as an explicit unavailable/empty state.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api, ApiError } from "../lib/api";
import { relativeTime } from "../lib/format";
import type {
  AgentInfo,
  ChatResponse,
  HandsFreeState,
  ModelInfo,
  Overview,
  SettingsResponse,
  SystemHealth,
  SystemMetrics,
  TaskItem,
  TaskList,
  ToolInfo,
  VoiceState,
} from "../lib/types";
import { dashboardSocket, type ConnectionState } from "../lib/ws";

export type { ConnectionState };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  model?: string | null;
  pending?: boolean;
  error?: boolean;
}

export interface TranscriptEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: string;
}

const CHAT_STORAGE_KEY = "friday.dashboard.chat.v1";
const INTERVAL_STORAGE_KEY = "friday.dashboard.metricsInterval.v1";
const MIN_INTERVAL = 1000;
const MAX_INTERVAL = 10_000;

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadChat(): ChatMessage[] {
  try {
    const raw = window.localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is ChatMessage => Boolean(item) && typeof item.content === "string")
      .filter((item) => !item.pending)
      .slice(-100);
  } catch {
    return [];
  }
}

function appendTranscript(list: TranscriptEntry[], entry: TranscriptEntry): TranscriptEntry[] {
  return [...list, entry].slice(-50);
}

function loadInterval(): number {
  try {
    const raw = Number(window.localStorage.getItem(INTERVAL_STORAGE_KEY));
    if (Number.isFinite(raw) && raw >= MIN_INTERVAL && raw <= MAX_INTERVAL) return raw;
  } catch {
    /* ignore */
  }
  return 1500;
}

interface DashboardContextValue {
  overview: Overview | null;
  metrics: SystemMetrics | null;
  health: SystemHealth | null;
  models: ModelInfo[];
  activeModel: ModelInfo | null;
  agents: AgentInfo[];
  activity: TaskItem[];
  counts: { total: number; running: number; completed: number; failed: number };
  tools: ToolInfo[];
  voice: VoiceState | null;
  settings: SettingsResponse | null;
  connection: ConnectionState;
  connectionDetail: string;
  backendReachable: boolean;
  booting: boolean;
  bootError: string | null;
  lastMetricAt: number | null;
  lastEventAt: string | null;
  refreshIntervalMs: number;
  setRefreshIntervalMs: (value: number) => void;
  refresh: () => Promise<void>;
  refreshActivity: () => Promise<void>;
  chatMessages: ChatMessage[];
  chatBusy: boolean;
  chatError: string | null;
  transcripts: TranscriptEntry[];
  sendChat: (message: string) => Promise<ChatResponse | null>;
  clearChat: () => void;
  clearChatError: () => void;
  executeTool: (
    id: string,
    payload: { target?: string; arguments?: Record<string, unknown>; confirm?: boolean },
  ) => Promise<{ ok: boolean; message: string }>;
}

const DashboardContext = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [activeModel, setActiveModel] = useState<ModelInfo | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [activity, setActivity] = useState<TaskItem[]>([]);
  const [counts, setCounts] = useState({ total: 0, running: 0, completed: 0, failed: 0 });
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("disconnected");
  const [connectionDetail, setConnectionDetail] = useState("");
  const [backendReachable, setBackendReachable] = useState(true);
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);
  const [lastMetricAt, setLastMetricAt] = useState<number | null>(null);
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);
  const [refreshIntervalMs, setRefreshIntervalState] = useState(loadInterval);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(loadChat);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);

  const chatBusyRef = useRef(false);
  const refreshTimerRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const applyTaskList = useCallback((payload: TaskList) => {
    setActivity(payload.items);
    if (payload.counts) setCounts(payload.counts);
  }, []);

  const refreshActivity = useCallback(async () => {
    try {
      const payload = await api.activity({ limit: 50 });
      if (mountedRef.current) applyTaskList(payload);
    } catch {
      /* connection banner already reports backend loss */
    }
  }, [applyTaskList]);

  const refreshAgents = useCallback(async () => {
    try {
      const payload = await api.agents();
      if (mountedRef.current) setAgents(payload.agents);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const payload = await api.systemHealth();
      if (mountedRef.current) setHealth(payload);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const payload = await api.models();
      if (!mountedRef.current) return;
      setModels(payload.models);
      setActiveModel(payload.active);
    } catch {
      /* ignore */
    }
  }, []);

  const refresh = useCallback(async () => {
    setBooting(true);
    const [overviewResult, toolsResult, voiceResult, settingsResult, modelsResult] =
      await Promise.allSettled([
        api.overview(),
        api.tools(),
        api.voiceState(),
        api.settings(),
        api.models(),
      ]);

    if (!mountedRef.current) return;

    if (overviewResult.status === "fulfilled") {
      const data = overviewResult.value;
      setOverview(data);
      setMetrics(data.metrics);
      setHealth(data.health);
      setAgents(data.agents);
      setActivity(data.activity);
      setCounts(data.counts);
      setActiveModel(data.active_model);
      setLastMetricAt(Date.parse(data.metrics.timestamp) || Date.now());
      setBackendReachable(true);
      setBootError(null);
    } else {
      const reason = overviewResult.reason;
      setBackendReachable(false);
      setBootError(reason instanceof Error ? reason.message : "Backend unreachable.");
    }

    if (toolsResult.status === "fulfilled") setTools(toolsResult.value.tools);
    if (voiceResult.status === "fulfilled") setVoice(voiceResult.value);
    if (settingsResult.status === "fulfilled") setSettings(settingsResult.value);
    if (modelsResult.status === "fulfilled") {
      setModels(modelsResult.value.models);
      setActiveModel(modelsResult.value.active);
    }
    setBooting(false);
  }, []);

  // Boot once.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Persist chat history (never pending placeholders).
  useEffect(() => {
    try {
      const stable = chatMessages.filter((message) => !message.pending).slice(-100);
      window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(stable));
    } catch {
      /* storage may be disabled */
    }
  }, [chatMessages]);

  // Metrics polling: recursive timeout avoids overlapping requests.
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const tick = async () => {
      controller = new AbortController();
      try {
        const payload = await api.metrics(controller.signal);
        if (cancelled || !mountedRef.current) return;
        setMetrics(payload);
        setLastMetricAt(Date.now());
        setBackendReachable(true);
      } catch (error) {
        if (cancelled || !mountedRef.current) return;
        if (error instanceof ApiError && error.type === "network_error") {
          setBackendReachable(false);
        }
      } finally {
        if (!cancelled) timer = window.setTimeout(tick, refreshIntervalMs);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [refreshIntervalMs]);

  // Slower polling for health/agents/activity.
  useEffect(() => {
    let cancelled = false;
    const run = () => {
      if (cancelled) return;
      void refreshHealth();
      void refreshAgents();
      void refreshActivity();
    };
    const timer = window.setInterval(run, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshHealth, refreshAgents, refreshActivity]);

  const scheduleEventRefresh = useCallback(() => {
    if (refreshTimerRef.current !== null) return;
    refreshTimerRef.current = window.setTimeout(() => {
      refreshTimerRef.current = null;
      if (!mountedRef.current) return;
      void refreshActivity();
      void refreshAgents();
    }, 400);
  }, [refreshActivity, refreshAgents]);

  // Shared socket subscription.
  useEffect(() => {
    dashboardSocket.acquire();
    const offEvent = dashboardSocket.onEvent((event) => {
      if (!mountedRef.current) return;
      setLastEventAt(event.timestamp);
      switch (event.type) {
        case "connection.ready":
          setBackendReachable(true);
          break;
        case "voice.state":
          setVoice((previous) =>
            previous ? { ...previous, state: event.status ?? previous.state } : previous,
          );
          break;
        case "voice.handsfree": {
          const status = event.status ?? "STOPPED";
          const data = (event.data ?? {}) as Record<string, unknown>;
          const handsFree: HandsFreeState = {
            enabled: data.enabled !== false,
            active:
              typeof data.active === "boolean"
                ? data.active
                : status !== "STOPPED" && status !== "ERROR",
            state: status,
            wake_word: String(data.wake_word ?? "friday"),
            error: String(data.error ?? event.message ?? ""),
            heard: String(data.heard ?? ""),
          };
          setVoice((previous) =>
            previous
              ? {
                  ...previous,
                  hands_free: handsFree,
                  hands_free_active: handsFree.active,
                  hands_free_state: handsFree.state,
                  wake_word: handsFree.wake_word,
                }
              : previous,
          );
          break;
        }
        case "transcript.updated": {
          const text = String(event.data?.text ?? event.message ?? "");
          if (!text) break;
          setTranscripts((previous) =>
            appendTranscript(previous, {
              id: newId(),
              role: event.data?.role === "assistant" ? "assistant" : "user",
              text,
              timestamp: event.timestamp,
            }),
          );
          break;
        }
        case "model.changed":
        case "model.unavailable":
        case "status.updated":
          void refreshModels();
          break;
        default:
          break;
      }
      if (
        event.type.startsWith("task.") ||
        event.type.startsWith("tool.") ||
        event.type.startsWith("research.") ||
        event.type.startsWith("image.") ||
        event.type.startsWith("automation.")
      ) {
        scheduleEventRefresh();
      }
    });

    const offState = dashboardSocket.onState((state, detail) => {
      if (!mountedRef.current) return;
      setConnection(state);
      setConnectionDetail(detail ?? "");
    });

    return () => {
      offEvent();
      offState();
      dashboardSocket.release();
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [refreshModels, scheduleEventRefresh]);

  const setRefreshIntervalMs = useCallback((value: number) => {
    const clamped = Math.min(MAX_INTERVAL, Math.max(MIN_INTERVAL, Math.round(value)));
    setRefreshIntervalState(clamped);
    try {
      window.localStorage.setItem(INTERVAL_STORAGE_KEY, String(clamped));
    } catch {
      /* ignore */
    }
  }, []);

  const sendChat = useCallback(
    async (message: string): Promise<ChatResponse | null> => {
      const trimmed = message.trim();
      if (!trimmed || chatBusyRef.current) return null;
      chatBusyRef.current = true;
      setChatBusy(true);
      setChatError(null);

      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        content: trimmed,
        timestamp: new Date().toISOString(),
      };
      const pendingId = newId();
      const pendingMessage: ChatMessage = {
        id: pendingId,
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        pending: true,
      };
      setChatMessages((previous) => [...previous, userMessage, pendingMessage]);
      setTranscripts((previous) =>
        appendTranscript(previous, {
          id: userMessage.id,
          role: "user",
          text: trimmed,
          timestamp: userMessage.timestamp,
        }),
      );

      try {
        const response = await api.chat(trimmed);
        if (!mountedRef.current) return response;
        setChatMessages((previous) =>
          previous.map((item) =>
            item.id === pendingId
              ? {
                  ...item,
                  content: response.response,
                  pending: false,
                  model: response.model?.name ?? null,
                  timestamp: response.timestamp || new Date().toISOString(),
                }
              : item,
          ),
        );
        setTranscripts((previous) =>
          appendTranscript(previous, {
            id: pendingId,
            role: "assistant",
            text: response.response,
            timestamp: response.timestamp || new Date().toISOString(),
          }),
        );
        setVoice((previous) => (previous ? { ...previous, state: response.state } : previous));
        scheduleEventRefresh();
        void refreshModels();
        return response;
      } catch (error) {
        const detail =
          error instanceof ApiError ? error.message : "The local model request failed.";
        if (!mountedRef.current) return null;
        setChatError(detail);
        setChatMessages((previous) =>
          previous.map((item) =>
            item.id === pendingId
              ? { ...item, content: detail, pending: false, error: true }
              : item,
          ),
        );
        scheduleEventRefresh();
        return null;
      } finally {
        chatBusyRef.current = false;
        if (mountedRef.current) setChatBusy(false);
      }
    },
    [refreshModels, scheduleEventRefresh],
  );

  const clearChat = useCallback(() => {
    setChatMessages([]);
    setChatError(null);
    setTranscripts([]);
    try {
      window.localStorage.removeItem(CHAT_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const clearChatError = useCallback(() => setChatError(null), []);

  const executeTool = useCallback<DashboardContextValue["executeTool"]>(
    async (id, payload) => {
      try {
        const result = await api.executeTool(id, payload);
        scheduleEventRefresh();
        return { ok: result.blocked === false && result.final_status !== "FAILED", message: result.message };
      } catch (error) {
        const detail = error instanceof ApiError ? error.message : "Tool execution failed.";
        scheduleEventRefresh();
        return { ok: false, message: detail };
      }
    },
    [scheduleEventRefresh],
  );

  const value = useMemo<DashboardContextValue>(
    () => ({
      overview,
      metrics,
      health,
      models,
      activeModel,
      agents,
      activity,
      counts,
      tools,
      voice,
      settings,
      connection,
      connectionDetail,
      backendReachable,
      booting,
      bootError,
      lastMetricAt,
      lastEventAt,
      refreshIntervalMs,
      setRefreshIntervalMs,
      refresh,
      refreshActivity,
      chatMessages,
      chatBusy,
      chatError,
      transcripts,
      sendChat,
      clearChat,
      clearChatError,
      executeTool,
    }),
    [
      overview,
      metrics,
      health,
      models,
      activeModel,
      agents,
      activity,
      counts,
      tools,
      voice,
      settings,
      connection,
      connectionDetail,
      backendReachable,
      booting,
      bootError,
      lastMetricAt,
      lastEventAt,
      refreshIntervalMs,
      setRefreshIntervalMs,
      refresh,
      refreshActivity,
      chatMessages,
      chatBusy,
      chatError,
      transcripts,
      sendChat,
      clearChat,
      clearChatError,
      executeTool,
    ],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const context = useContext(DashboardContext);
  if (!context) throw new Error("useDashboard must be used inside DashboardProvider");
  return context;
}

export function useLastUpdatedLabel(timestamp: number | null): string {
  if (!timestamp) return "waiting";
  return relativeTime(new Date(timestamp).toISOString());
}
