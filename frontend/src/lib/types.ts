/** Types mirrored from the FastAPI dashboard responses (friday/web/*). */

export type ServiceStatus =
  | "healthy"
  | "starting"
  | "degraded"
  | "offline"
  | "unavailable"
  | "error"
  | "unknown"
  | "ready";

export interface Identity {
  name: string;
  version: string;
  platform: string;
  uptime_seconds: number;
}

export interface CpuMetrics {
  percent: number | null;
  logical_cores: number | null;
  physical_cores: number | null;
}

export interface RamMetrics {
  total_gb: number;
  used_gb: number;
  available_gb: number;
  percent: number;
}

export interface DiskMetrics {
  total_gb: number;
  used_gb: number;
  free_gb: number;
  percent: number;
}

export interface GpuMetrics {
  available: boolean;
  name: string | null;
  utilization_percent: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  memory_percent: number | null;
  temperature_c: number | null;
  provider: string;
  reason: string;
}

export interface SystemMetrics {
  timestamp: string;
  cpu: CpuMetrics;
  ram: RamMetrics;
  disk: DiskMetrics | null;
  gpu: GpuMetrics;
  uptime_seconds: number;
  source: string;
}

export interface HealthComponent {
  status: ServiceStatus;
  detail: string;
  clients?: number;
  device?: string | null;
  vram_total_mb?: number | null;
  provider?: string;
  endpoint?: string;
}

export interface SystemHealth {
  overall: "healthy" | "degraded" | "fail";
  components: Record<string, HealthComponent>;
  timestamp: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  family: string;
  kind: "reasoning" | "image" | "chat" | string;
  provider?: string;
  path?: string;
  quantization?: string;
  active: boolean;
  loaded: boolean | null;
  health: ServiceStatus;
  context_window?: number | null;
  endpoint?: string;
  device?: string;
  components?: Record<string, string>;
  error?: string;
}

export type AgentStatus = "idle" | "working" | "offline" | "queued" | "failed" | "completed";

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  source: string;
  status: AgentStatus;
  current_task: string | null;
  current_task_id: string | null;
  last_activity: string | null;
  last_status: string | null;
  last_error: string;
  capabilities: string[];
  provider?: string | null;
  endpoint?: string | null;
  device?: string | null;
  collection?: string;
}

export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "blocked"
  | "waiting_approval";

export interface TaskItem {
  id: string;
  kind: string;
  title: string;
  source: string;
  status: TaskStatus;
  message: string;
  progress: number | null;
  error: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  started_ts: number;
  duration_ms: number | null;
  meta: Record<string, unknown>;
}

export interface TaskList {
  total: number;
  items: TaskItem[];
  counts?: { total: number; running: number; completed: number; failed: number };
}

export interface ToolInfo {
  name: string;
  id: string;
  permission_key: string | null;
  allowed: boolean;
  dry_run: boolean;
  requires_confirmation: boolean;
  available: boolean;
}

export interface ToolExecution {
  task_id: string;
  action: string;
  target: string;
  status: string;
  final_status: string;
  verification: string;
  message: string;
  spoken_message: string;
  blocked: boolean;
  latency_ms: number;
  tool_result: Record<string, unknown>;
}

export interface ChatResponse {
  task_id: string;
  response: string;
  keep_running: boolean;
  state: string;
  model: ModelInfo | null;
  timestamp: string;
}

export interface VoiceState {
  state: string;
  capture_active: boolean;
  microphone: { available: boolean; detail: string };
  pipeline: string[];
  capture_supported: boolean;
  reason: string;
}

export interface ImageResult {
  success: boolean;
  message: string;
  path: string;
  filename: string;
  prompt: string;
  width: number;
  height: number;
  steps: number;
  seed: number | null;
  provider: string;
  backend: string;
  device: string;
  request_id: string;
  elapsed_ms: number;
  error_type: string;
  detail: Record<string, unknown>;
  task_id?: string;
  url?: string | null;
}

export interface ImageHistoryItem {
  filename: string;
  path: string;
  url: string;
  created_at: number;
  size_bytes: number;
  metadata: Record<string, unknown>;
}

export interface ResearchResult {
  title?: string;
  url?: string;
  snippet?: string;
  source?: string;
  rank?: number;
  published_at?: string | null;
  [key: string]: unknown;
}

export interface ResearchError {
  provider?: string;
  error_type?: string;
  message?: string;
  retryable?: boolean;
}

export interface ResearchResponse {
  success: boolean;
  original_query?: string;
  search_queries?: string[];
  results?: ResearchResult[];
  provider?: string;
  elapsed_ms?: number;
  needs_web?: boolean;
  query_type?: string;
  error?: ResearchError | string | null;
  task_id?: string;
}

export interface KnowledgeDocument {
  name: string;
  path: string;
  suffix: string;
  size_bytes: number;
  modified_at: number;
}

export interface KnowledgeResponse {
  enabled: boolean;
  collection: string | null;
  source_dirs: string[];
  documents: KnowledgeDocument[];
  count: number;
  errors: string[];
  note: string;
}

export interface WorkspaceResponse {
  root: { path?: string; name?: string };
  projects: Array<{
    id: string;
    name: string;
    path: string;
    status: string;
    kind: string;
    detail: string;
  }>;
  directories: Array<{
    path: string;
    name: string;
    is_dir: boolean;
    size_bytes: number | null;
    modified_at: number;
  }>;
  documents_dir: string;
  rag: { enabled: boolean; collection?: string | null };
  note: string;
}

export interface SettingsResponse {
  identity: Identity;
  backend_url: string;
  mode: string;
  state: string;
  warnings: string[];
  security: { dry_run: boolean; allow_real_execution: boolean };
  reasoning: { provider?: string; model?: string; endpoint?: string; timeout?: number };
  image: {
    provider?: string;
    width?: number;
    height?: number;
    steps?: number;
    device?: string;
    timeout?: number;
  };
  voice: {
    offline_only?: boolean;
    wake_word_required?: boolean;
    stt_model?: string;
    tts_engine?: string;
  };
  research: { enabled?: boolean; provider?: string; max_results?: number };
  monitoring: { refresh_interval_ms: number };
}

export interface Overview {
  identity: Identity;
  state: string;
  metrics: SystemMetrics;
  health: SystemHealth;
  active_model: ModelInfo | null;
  agents: AgentInfo[];
  activity: TaskItem[];
  counts: { total: number; running: number; completed: number; failed: number };
  warnings: string[];
  timestamp: string;
}

/** Versioned dashboard event emitted by /ws/dashboard. */
export interface DashboardEvent {
  type: string;
  v: number;
  seq: number;
  timestamp: string;
  task_id: string | null;
  status: string | null;
  source: string;
  message: string;
  progress: number | null;
  data: Record<string, unknown>;
}
