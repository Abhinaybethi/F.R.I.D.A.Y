import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../lib/api";
import { formatBytes, formatDateTime, formatDuration } from "../lib/format";
import type { ImageHistoryItem, ImageResult } from "../lib/types";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { LoadingState } from "./LoadingState";
import { StatusPill } from "./StatusPill";

type Phase = "idle" | "queued" | "generating" | "completed" | "failed";

export function ImageGenerationPanel() {
  const { settings, health, refreshActivity } = useDashboard();
  const [prompt, setPrompt] = useState("");
  const [width, setWidth] = useState<string>("");
  const [height, setHeight] = useState<string>("");
  const [steps, setSteps] = useState<string>("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<ImageResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [history, setHistory] = useState<ImageHistoryItem[]>([]);
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "error">("loading");
  const [historyNote, setHistoryNote] = useState<string>("");
  const startedRef = useRef(0);

  const imageHealth = health?.components?.image;
  const imageReady = imageHealth?.status === "healthy";
  const defaults = settings?.image;

  useEffect(() => {
    if (width === "" && defaults?.width) setWidth(String(defaults.width));
    if (height === "" && defaults?.height) setHeight(String(defaults.height));
    if (steps === "" && defaults?.steps) setSteps(String(defaults.steps));
  }, [defaults, width, height, steps]);

  const loadHistory = useCallback(async () => {
    setHistoryState("loading");
    try {
      const payload = await api.imageHistory();
      setHistory(payload.items);
      setHistoryNote(
        payload.available
          ? `Reading ${payload.root}`
          : `No output directory yet at ${payload.root}. Nothing has been generated.`,
      );
      setHistoryState("ready");
    } catch (reason) {
      setHistoryNote(reason instanceof ApiError ? reason.message : "History could not be loaded.");
      setHistoryState("error");
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (phase !== "generating" && phase !== "queued") return;
    const timer = window.setInterval(() => {
      setElapsed((performance.now() - startedRef.current) / 1000);
    }, 500);
    return () => window.clearInterval(timer);
  }, [phase]);

  const generate = async () => {
    const text = prompt.trim();
    if (!text || phase === "generating" || phase === "queued") return;

    setPhase("queued");
    setResult(null);
    setError(null);
    setElapsed(0);
    // The request is asynchronous from the UI's perspective but the backend
    // starts working immediately; switch to "generating" on the next tick.
    startedRef.current = performance.now();
    window.setTimeout(() => setPhase((current) => (current === "queued" ? "generating" : current)), 350);

    try {
      const response = await api.generateImage({
        prompt: text,
        width: width ? Number(width) : undefined,
        height: height ? Number(height) : undefined,
        steps: steps ? Number(steps) : undefined,
      });
      setResult(response);
      setPhase(response.success ? "completed" : "failed");
      if (!response.success) {
        setError(
          [response.error_type, response.message].filter(Boolean).join(": ") ||
            "The image backend reported a failure.",
        );
      }
      void loadHistory();
    } catch (reason) {
      setPhase("failed");
      setError(reason instanceof ApiError ? reason.message : "Image generation request failed.");
    } finally {
      void refreshActivity();
    }
  };

  const busy = phase === "queued" || phase === "generating";

  return (
    <div className="stack">
      <div className="row wrap between">
        <StatusPill
          status={imageReady ? "healthy" : (imageHealth?.status ?? "unknown")}
          label={
            imageReady
              ? `Qwen-Image ready · ${imageHealth?.detail ?? "device reported"}`
              : `Image backend ${imageHealth?.status ?? "unknown"}`
          }
        />
        <span className="tiny muted">
          {defaults ? `defaults ${defaults.width}×${defaults.height} · ${defaults.steps} steps` : "no defaults reported"}
        </span>
      </div>

      {!imageReady ? (
        <div className="alert" data-tone="info">
          <div>
            <span className="alert-title">Image backend not healthy</span>
            {imageHealth?.detail ?? "The backend has not reported image-generation readiness."} Generation
            requests will use the real pipeline and surface the real error if it cannot run.
          </div>
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="image-prompt">Prompt</label>
        <textarea
          id="image-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Describe the image to generate locally…"
          rows={3}
          maxLength={2000}
        />
      </div>

      <div className="inline-fields">
        <div className="field">
          <label htmlFor="image-width">Width</label>
          <input
            id="image-width"
            type="number"
            min={256}
            max={2048}
            step={8}
            value={width}
            onChange={(event) => setWidth(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="image-height">Height</label>
          <input
            id="image-height"
            type="number"
            min={256}
            max={2048}
            step={8}
            value={height}
            onChange={(event) => setHeight(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="image-steps">Steps</label>
          <input
            id="image-steps"
            type="number"
            min={1}
            max={60}
            value={steps}
            onChange={(event) => setSteps(event.target.value)}
          />
        </div>
      </div>

      <div className="row wrap between">
        <div className="row" style={{ gap: 8 }}>
          <StatusPill
            status={
              phase === "completed"
                ? "completed"
                : phase === "failed"
                  ? "failed"
                  : phase === "generating"
                    ? "running"
                    : phase === "queued"
                      ? "queued"
                      : "idle"
            }
            label={phase === "idle" ? "Idle" : phase.charAt(0).toUpperCase() + phase.slice(1)}
          />
          {busy ? (
            <span className="tiny muted row" style={{ gap: 8 }}>
              <span className="spinner" aria-hidden="true" /> {Math.floor(elapsed)}s elapsed
            </span>
          ) : null}
          {phase === "completed" && result ? (
            <span className="tiny muted">{formatDuration(result.elapsed_ms)}</span>
          ) : null}
        </div>
        <div className="row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void generate()}
            disabled={busy || prompt.trim().length === 0}
          >
            <Icon name="spark" size={14} />
            {busy ? "Generating…" : "Generate image"}
          </button>
        </div>
      </div>

      {busy ? (
        <div className="alert" data-tone="info" role="status">
          <div>
            <span className="alert-title">Generation runs as a single blocking backend call</span>
            The existing Qwen pipeline does not emit incremental progress, so the dashboard shows elapsed
            time instead of an invented percentage. On a 6 GB GPU this commonly takes 100–300 seconds.
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="alert" data-tone="error" role="alert">
          <div>
            <span className="alert-title">Generation failed</span>
            {error}
            {result?.detail && Object.keys(result.detail).length > 0 ? (
              <pre className="mono tiny" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>
                {JSON.stringify(result.detail, null, 2).slice(0, 1200)}
              </pre>
            ) : null}
          </div>
        </div>
      ) : null}

      {phase === "completed" && result?.success ? (
        <div className="stack-sm">
          <div className="image-preview">
            {result.url ? (
              <img src={result.url} alt={`Generated result for: ${result.prompt}`} loading="lazy" />
            ) : null}
          </div>
          <dl className="kv">
            <dt>File</dt>
            <dd className="mono">{result.path || result.filename}</dd>
            <dt>Dimensions</dt>
            <dd>
              {result.width}×{result.height} · {result.steps} steps
            </dd>
            <dt>Device</dt>
            <dd>{result.device}</dd>
            <dt>Seed</dt>
            <dd>{result.seed ?? "random"}</dd>
            <dt>Elapsed</dt>
            <dd>{formatDuration(result.elapsed_ms)}</dd>
            <dt>Request</dt>
            <dd className="mono">{result.request_id}</dd>
          </dl>
          <div className="row">
            {result.url ? (
              <a className="btn btn-sm" href={result.url} target="_blank" rel="noreferrer noopener">
                <Icon name="external" size={12} /> Open image
              </a>
            ) : null}
            <span className="tiny muted">Served from the configured output directory only.</span>
          </div>
        </div>
      ) : null}

      <div>
        <div className="panel-head" style={{ marginBottom: 8 }}>
          <div>
            <h3>Generation history</h3>
            <p className="tiny muted">{historyNote}</p>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => void loadHistory()}>
            <Icon name="refresh" size={12} /> Refresh
          </button>
        </div>

        {historyState === "loading" ? (
          <LoadingState label="Reading output directory" />
        ) : history.length === 0 ? (
          <EmptyState
            title="No generated images"
            description="Images appear here after the real pipeline writes a PNG and its metadata sidecar."
            icon="image"
          />
        ) : (
          <div className="image-grid">
            {history.map((item) => (
              <div className="image-card" key={item.path}>
                <a href={item.url} target="_blank" rel="noreferrer noopener">
                  <img src={item.url} alt={String(item.metadata.prompt ?? item.filename)} loading="lazy" />
                </a>
                <div className="caption">
                  <span className="truncate" title={String(item.metadata.prompt ?? item.filename)}>
                    {String(item.metadata.prompt ?? item.filename)}
                  </span>
                  <span>{formatBytes(item.size_bytes)}</span>
                </div>
                <div className="caption" style={{ borderTop: "1px solid var(--line)" }}>
                  <span>{formatDateTime(item.created_at * 1000)}</span>
                  {typeof item.metadata.seed === "number" ? <span>seed {item.metadata.seed}</span> : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
