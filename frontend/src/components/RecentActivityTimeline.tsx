import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../lib/api";
import {
  formatDateTime,
  formatDuration,
  kindLabel,
  relativeTime,
  statusLabel,
  statusTone,
} from "../lib/format";
import type { TaskItem } from "../lib/types";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";
import { LoadingState } from "./LoadingState";
import { StatusPill } from "./StatusPill";

const FILTERS: Array<{ id: string; label: string; status?: string; kind?: string }> = [
  { id: "all", label: "All" },
  { id: "running", label: "Running", status: "running" },
  { id: "completed", label: "Completed", status: "completed" },
  { id: "failed", label: "Failed", status: "failed" },
  { id: "agents", label: "Agents", kind: "agent" },
  { id: "research", label: "Research", kind: "research" },
  { id: "images", label: "Images", kind: "image" },
  { id: "voice", label: "Voice", kind: "voice" },
  { id: "tools", label: "Tools", kind: "tool" },
  { id: "code", label: "Code", kind: "code" },
];

const PAGE_SIZE = 20;

export function RecentActivityTimeline({
  compact = false,
  initialKind,
}: {
  compact?: boolean;
  initialKind?: string;
}) {
  const { lastEventAt, refreshActivity } = useDashboard();
  const [filterId, setFilterId] = useState(initialKind ? `kind:${initialKind}` : "all");
  const [items, setItems] = useState<TaskItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const activeFilter =
    FILTERS.find((filter) => filter.id === filterId) ??
    (filterId.startsWith("kind:")
      ? { id: filterId, label: kindLabel(filterId.slice(5)), kind: filterId.slice(5) }
      : FILTERS[0]);

  const load = useCallback(
    async (append: boolean) => {
      const ticket = requestId.current + 1;
      requestId.current = ticket;
      if (!append) setLoading(true);
      try {
        const payload = await api.activity({
          status: activeFilter.status,
          kind: activeFilter.kind,
          limit: PAGE_SIZE,
          offset: append ? items.length : 0,
        });
        if (ticket !== requestId.current) return;
        setItems((previous) => (append ? [...previous, ...payload.items] : payload.items));
        setTotal(payload.total);
        setError(null);
      } catch (reason) {
        if (ticket !== requestId.current) return;
        setError(reason instanceof ApiError ? reason.message : "Activity could not be loaded.");
      } finally {
        if (ticket === requestId.current) setLoading(false);
      }
    },
    [activeFilter.kind, activeFilter.status, items.length],
  );

  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilter.kind, activeFilter.status]);

  // Real-time: refresh when the shared socket reports new operation events.
  useEffect(() => {
    if (!lastEventAt || compact) return;
    const timer = window.setTimeout(() => {
      void load(false);
      void refreshActivity();
    }, 600);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEventAt]);

  return (
    <div className="stack-sm">
      {!compact ? (
        <div className="row wrap" style={{ gap: 4 }} role="tablist" aria-label="Activity filters">
          {FILTERS.map((filter) => (
            <button
              key={filter.id}
              type="button"
              role="tab"
              aria-selected={filter.id === filterId}
              className={`btn btn-sm ${filter.id === filterId ? "btn-purple" : "btn-ghost"}`}
              onClick={() => setFilterId(filter.id)}
            >
              {filter.label}
            </button>
          ))}
        </div>
      ) : null}

      {loading && items.length === 0 ? (
        <LoadingState label="Loading activity" />
      ) : error ? (
        <div className="alert" data-tone="error" role="alert">
          <div>
            <span className="alert-title">Activity unavailable</span>
            {error}
          </div>
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="No activity recorded"
          description="Operations appear here after a real chat turn, tool call, research request, or image generation. Nothing is simulated."
          icon="activity"
        />
      ) : (
        <>
          <div className="timeline">
            {items.map((item) => (
              <div className="timeline-item" key={item.id}>
                <span className="timeline-dot" data-tone={statusTone(item.status)} aria-hidden="true" />
                <div style={{ minWidth: 0 }}>
                  <div className="row between" style={{ gap: 8 }}>
                    <span className="list-title" title={item.title}>
                      {item.title}
                    </span>
                    <StatusPill status={item.status} label={statusLabel(item.status)} />
                  </div>
                  <div className="list-meta">
                    <span className="chip">{kindLabel(item.kind)}</span>
                    {item.source ? <span>{item.source}</span> : null}
                    <span title={formatDateTime(item.created_at)}>{relativeTime(item.created_at)}</span>
                    {item.duration_ms !== null ? <span>· {formatDuration(item.duration_ms)}</span> : null}
                  </div>
                  {item.message ? (
                    <div className="tiny muted" title={item.message} style={{ marginTop: 2 }}>
                      {item.message.length > 160 ? `${item.message.slice(0, 159)}…` : item.message}
                    </div>
                  ) : null}
                  {item.error ? (
                    <div className="tiny" style={{ color: "var(--red)", marginTop: 2 }}>
                      {item.error}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
          {!compact && items.length < total ? (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => void load(true)}>
              Load more ({total - items.length} remaining)
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
