import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, ApiError } from "../lib/api";
import {
  formatDateTime,
  formatDuration,
  relativeTime,
  statusLabel,
  statusTone,
} from "../lib/format";
import type { AgentInfo, TaskItem } from "../lib/types";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function AgentsPage() {
  const { agents, sendChat, chatBusy, booting } = useDashboard();
  const [params, setParams] = useSearchParams();
  const focusId = params.get("focus");
  const selected = useMemo(
    () => agents.find((agent) => agent.id === focusId) ?? agents[0] ?? null,
    [agents, focusId],
  );

  const [history, setHistory] = useState<TaskItem[]>([]);
  const [historyState, setHistoryState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [historyError, setHistoryError] = useState("");
  const [taskDraft, setTaskDraft] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setHistoryState("loading");
    api
      .agent(selected.id)
      .then((payload) => {
        if (cancelled) return;
        setHistory(payload.history);
        setHistoryState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setHistoryError(error instanceof ApiError ? error.message : "History unavailable.");
        setHistoryState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id, selected?.status, selected?.last_activity]);

  const submit = async () => {
    const text = taskDraft.trim();
    if (!text || chatBusy) return;
    setSubmitted("Submitting through the conversation router…");
    setTaskDraft("");
    const response = await sendChat(text);
    setSubmitted(
      response
        ? "Request completed. The response appears in Chat and the activity timeline."
        : "Request failed. See the Chat page for the real error.",
    );
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Agents</span>
          <h1>Registered agents</h1>
          <p>
            These are F.R.I.D.A.Y&apos;s real subsystems as reported by the backend. They are not
            independent autonomous workers: tasks are triggered by user turns that route through the
            conversation manager.
          </p>
        </div>
        <span className="pill" data-tone="info">
          <span className="dot" /> {agents.length} registered
        </span>
      </div>

      {agents.length === 0 ? (
        booting ? <LoadingState label="Reading agent state" /> : (
          <EmptyState
            title="No agents reported"
            description="The backend has not returned any subsystem state."
            icon="users"
          />
        )
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "minmax(240px, 320px) minmax(0, 1fr)", alignItems: "start" }}>
          <section className="panel" aria-label="Agent list">
            <div className="panel-body list">
              {agents.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  className="list-row"
                  onClick={() => setParams({ focus: agent.id }, { replace: true })}
                  style={{
                    textAlign: "left",
                    background: selected?.id === agent.id ? "rgba(139,92,246,0.1)" : "transparent",
                    borderColor: selected?.id === agent.id ? "var(--line-purple)" : "transparent",
                    cursor: "pointer",
                    width: "100%",
                    font: "inherit",
                    color: "inherit",
                  }}
                >
                  <span
                    className="timeline-dot"
                    data-tone={statusTone(agent.status)}
                    style={{ margin: "6px 0 0" }}
                    aria-hidden="true"
                  />
                  <div className="list-main">
                    <div className="row between" style={{ gap: 6 }}>
                      <span className="list-title">{agent.name}</span>
                      <span className="tiny muted">{statusLabel(agent.status)}</span>
                    </div>
                    <div className="list-meta">
                      <span className="truncate">{agent.current_task ?? agent.description}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </section>

          <div className="stack">
            {selected ? <AgentDetail agent={selected} /> : null}

            <section className="panel" aria-labelledby="agent-submit">
              <div className="panel-head">
                <div>
                  <h2 id="agent-submit">Submit a task</h2>
                  <p className="panel-sub">
                    Routed through the real conversation manager; the router chooses which tool or
                    subsystem handles it.
                  </p>
                </div>
              </div>
              <div className="panel-body stack-sm">
                <textarea
                  value={taskDraft}
                  onChange={(event) => setTaskDraft(event.target.value)}
                  placeholder="Describe the task, e.g. “research the latest stable-diffusion.cpp release”"
                  rows={2}
                />
                <div className="row">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => void submit()}
                    disabled={chatBusy || taskDraft.trim().length === 0}
                  >
                    {chatBusy ? <span className="spinner" aria-hidden="true" /> : <Icon name="send" size={14} />}
                    {chatBusy ? "Working…" : "Submit task"}
                  </button>
                  <Link to="/chat" className="btn btn-sm btn-ghost">
                    Open chat
                  </Link>
                </div>
                {submitted ? <p className="tiny muted">{submitted}</p> : null}
              </div>
            </section>

            <section className="panel" aria-labelledby="agent-history">
              <div className="panel-head">
                <div>
                  <h2 id="agent-history">Task history</h2>
                  <p className="panel-sub">Persisted operations attributed to this subsystem</p>
                </div>
              </div>
              <div className="panel-body">
                {historyState === "loading" ? (
                  <LoadingState label="Loading history" />
                ) : historyState === "error" ? (
                  <div className="alert" data-tone="error">{historyError}</div>
                ) : history.length === 0 ? (
                  <EmptyState
                    title="No recorded tasks"
                    description="This subsystem has not produced a persisted task yet."
                    icon="clock"
                  />
                ) : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th scope="col">Task</th>
                          <th scope="col">Status</th>
                          <th scope="col">Started</th>
                          <th scope="col">Duration</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.map((item) => (
                          <tr key={item.id}>
                            <td>{item.title}</td>
                            <td>
                              <StatusPill status={item.status} />
                            </td>
                            <td className="tiny" title={formatDateTime(item.created_at)}>
                              {relativeTime(item.created_at)}
                            </td>
                            <td className="tiny">{formatDuration(item.duration_ms)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

function AgentDetail({ agent }: { agent: AgentInfo }) {
  return (
    <section className="panel panel-accent" aria-labelledby="agent-detail">
      <div className="panel-head">
        <div>
          <h2 id="agent-detail">{agent.name}</h2>
          <p className="panel-sub">{agent.description}</p>
        </div>
        <StatusPill status={agent.status} label={statusLabel(agent.status)} />
      </div>
      <div className="panel-body stack-sm">
        <div className="chip-row">
          {agent.capabilities.map((capability) => (
            <span className="chip" key={capability}>
              {capability}
            </span>
          ))}
        </div>

        <dl className="kv">
          <dt>Current task</dt>
          <dd>{agent.current_task ?? "None"}</dd>
          <dt>Last activity</dt>
          <dd>{agent.last_activity ? relativeTime(agent.last_activity) : "never"}</dd>
          <dt>Last result</dt>
          <dd>{agent.last_status ? statusLabel(agent.last_status) : "—"}</dd>
          <dt>Provider</dt>
          <dd>{agent.provider ?? "internal"}</dd>
          {agent.endpoint ? (
            <>
              <dt>Endpoint</dt>
              <dd className="mono">{agent.endpoint}</dd>
            </>
          ) : null}
          {agent.device ? (
            <>
              <dt>Device</dt>
              <dd>{agent.device}</dd>
            </>
          ) : null}
          {agent.collection ? (
            <>
              <dt>Collection</dt>
              <dd className="mono">{agent.collection}</dd>
            </>
          ) : null}
        </dl>

        {agent.last_error ? (
          <div className="alert" data-tone="error">
            <div>
              <span className="alert-title">Last error</span>
              {agent.last_error}
            </div>
          </div>
        ) : null}

        {agent.status === "working" ? (
          <div className="stack-sm">
            <div className="row between tiny muted">
              <span>Working on {agent.current_task ?? "a task"}</span>
              <span>The backend does not report a percentage</span>
            </div>
            <div className="progress-indeterminate" role="progressbar" aria-label="Indeterminate progress" />
          </div>
        ) : null}
      </div>
    </section>
  );
}
