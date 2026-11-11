import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";

type MemoryMode = "stats" | "sessions" | "facts" | "tasks" | "search";

interface MemoryStats {
  enabled: boolean;
  source?: string;
  db_size_bytes?: number;
  schema_version?: number;
  sessions?: number;
  messages?: number;
  facts?: number;
  tasks?: number;
  task_steps?: number;
  vector?: { enabled: boolean; available: boolean; count?: number };
}

interface MemorySession {
  id: string;
  title?: string | null;
  source?: string | null;
  turn_count?: number;
  started_at?: string | null;
  ended_at?: string | null;
}

interface MemoryFact {
  id: string;
  subject: string;
  predicate: string;
  object: string;
  confidence?: number;
  deleted_at?: string | null;
}

interface MemoryTask {
  id: string;
  goal?: string;
  state?: string;
  steps?: unknown[];
  created_at?: string;
}

interface MemorySearchResult {
  id: string;
  raw_text?: string;
  response_text?: string | null;
  match?: string;
  score?: number;
  session?: { id?: string; title?: string | null; source?: string | null };
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function MemoryPage() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [mode, setMode] = useState<MemoryMode>("stats");
  const [query, setQuery] = useState("");
  const [sessions, setSessions] = useState<MemorySession[]>([]);
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [tasks, setTasks] = useState<MemoryTask[]>([]);
  const [results, setResults] = useState<MemorySearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [modeLoading, setModeLoading] = useState(false);
  const [error, setError] = useState("");

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      const payload = (await api.memoryStats()) as unknown as MemoryStats;
      setStats(payload);
      setError("");
    } catch (err) {
      setError(errorMessage(err, "Backend unreachable."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    if (!stats?.enabled) return;
    let cancelled = false;

    const loadMode = async () => {
      setModeLoading(true);
      setError("");
      try {
        if (mode === "sessions") {
          const payload = (await api.memorySessions()) as unknown as {
            sessions?: MemorySession[];
          };
          if (!cancelled) setSessions(payload.sessions ?? []);
        } else if (mode === "facts") {
          const payload = (await api.memoryFacts()) as unknown as {
            facts?: MemoryFact[];
          };
          if (!cancelled) setFacts(payload.facts ?? []);
        } else if (mode === "tasks") {
          const payload = (await api.memoryTasks()) as unknown as {
            tasks?: MemoryTask[];
          };
          if (!cancelled) setTasks(payload.tasks ?? []);
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, `Failed to load ${mode}.`));
      } finally {
        if (!cancelled) setModeLoading(false);
      }
    };

    void loadMode();

    return () => {
      cancelled = true;
    };
  }, [mode, stats?.enabled]);

  const runSearch = useCallback(
    async (value: string) => {
      const needle = value.trim();
      if (!needle) {
        setResults([]);
        return;
      }
      setMode("search");
      setModeLoading(true);
      setError("");
      try {
        const payload = (await api.memorySearch(needle)) as unknown as {
          results?: MemorySearchResult[];
        };
        setResults(payload.results ?? []);
      } catch (err) {
        setError(errorMessage(err, "Search failed."));
        setResults([]);
      } finally {
        setModeLoading(false);
      }
    },
    [],
  );

  const renderStats = () => {
    if (!stats) return null;
    if (!stats.enabled) {
      return (
        <div className="stack-sm">
          <StatusPill status="degraded" label="Memory disabled" />
          <p className="tiny muted">
            Memory is disabled in config; no persistent history or search available.
          </p>
        </div>
      );
    }
    return (
      <div className="grid grid-3">
        <div className="stat-tile">
          <span className="label">DB size (bytes)</span>
          <span className="value">{stats.db_size_bytes}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Schema v</span>
          <span className="value">{stats.schema_version}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Source</span>
          <span className="value">{stats.source}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Sessions</span>
          <span className="value">{stats.sessions}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Messages</span>
          <span className="value">{stats.messages}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Facts</span>
          <span className="value">{stats.facts}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Tasks</span>
          <span className="value">{stats.tasks}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Steps</span>
          <span className="value">{stats.task_steps}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Vector</span>
          <span className="value">
            {stats.vector?.enabled && stats.vector.available ? "enabled" : "disabled"}
          </span>
        </div>
      </div>
    );
  };

  const renderSessions = () => {
    if (!stats?.enabled) {
      return <EmptyState title="Memory disabled" description="Memory is turned off in config." icon="archive" />;
    }
    if (modeLoading) return <LoadingState label="Fetching sessions" />;
    if (sessions.length === 0) {
      return (
        <EmptyState
          title="No sessions"
          description="Start a conversation to create your first session."
          icon="clock"
        />
      );
    }
    return (
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Session</th>
              <th scope="col">Turns</th>
              <th scope="col">Started</th>
              <th scope="col">Ended</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => (
              <tr key={session.id}>
                <td>
                  <div style={{ fontWeight: 500 }}>{session.title || session.id}</div>
                  <div className="tiny muted">source={session.source ?? "—"}</div>
                </td>
                <td>{session.turn_count ?? 0}</td>
                <td>{session.started_at ?? "—"}</td>
                <td>{session.ended_at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderFacts = () => {
    if (!stats?.enabled) {
      return <EmptyState title="Memory disabled" description="Memory is turned off in config." icon="check" />;
    }
    if (modeLoading) return <LoadingState label="Fetching facts" />;
    return (
      <div className="grid grid-3">
        <div className="panel">
          <div className="panel-head">
            <h2>Facts</h2>
            <p className="panel-sub">Persisted subject-predicate-object triples with revisions</p>
          </div>
          <div className="panel-body">
            {facts.length === 0 ? (
              <EmptyState
                title="No facts"
                description="Ask Friday to remember something, or correct a fact."
                icon="check"
              />
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Subject</th>
                      <th scope="col">Predicate</th>
                      <th scope="col">Object</th>
                      <th scope="col">Confidence</th>
                      <th scope="col">Deleted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {facts.map((fact) => (
                      <tr key={fact.id}>
                        <td>{fact.subject}</td>
                        <td>{fact.predicate}</td>
                        <td>{fact.object}</td>
                        <td>{fact.confidence ?? "—"}</td>
                        <td>{fact.deleted_at ? "soft-deleted" : "active"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
        <div className="panel" style={{ marginLeft: 0, borderLeft: "none" }}>
          <div className="panel-head">
            <h2>Fact Operations</h2>
            <p className="panel-sub">Add, correct, or delete facts from the sidebar</p>
          </div>
          <div className="panel-body" style={{ marginTop: 10 }}>
            <button
              className="secondary"
              style={{
                width: "100%",
                marginBottom: 8,
                height: 32,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Icon name="plus" size={14} /> Add fact
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderTasks = () => {
    if (!stats?.enabled) {
      return <EmptyState title="Memory disabled" description="Memory is turned off in config." icon="book" />;
    }
    if (modeLoading) return <LoadingState label="Fetching tasks" />;
    if (tasks.length === 0) {
      return (
        <EmptyState
          title="No tasks"
          description="Tasks accumulate as Friday processes them."
          icon="task"
        />
      );
    }
    return (
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">Goal</th>
              <th scope="col">State</th>
              <th scope="col">Steps</th>
              <th scope="col">Created</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td>{task.id}</td>
                <td>{task.goal ?? "—"}</td>
                <td>{task.state ?? "—"}</td>
                <td>{Array.isArray(task.steps) ? task.steps.length : 0}</td>
                <td>{task.created_at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderSearch = () => {
    if (!stats?.enabled) return null;
    return (
      <div className="panel">
        <div className="panel-head">
          <h2>Search Stored Turns</h2>
          <p className="panel-sub">
            Keyword / meaning / date / topic search across all sessions
          </p>
        </div>
        <div className="panel-body">
          {modeLoading ? (
            <LoadingState label="Search is running…" />
          ) : results.length === 0 ? (
            <EmptyState
              title="No results"
              description="Try a different keyword or filter."
              icon="search"
            />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Turn</th>
                    <th scope="col">Session</th>
                    <th scope="col">Match</th>
                    <th scope="col">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result) => (
                    <tr key={result.id}>
                      <td>
                        <div style={{ fontWeight: 500, whiteSpace: "pre-wrap" }}>
                          {result.raw_text || ""}
                        </div>
                        <div className="tiny muted">{result.response_text || ""}</div>
                      </td>
                      <td>
                        {result.session?.title || result.session?.id || "—"}
                        {result.session?.source ? ` (${result.session.source})` : ""}
                      </td>
                      <td>{result.match ?? "—"}</td>
                      <td>{result.score ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="page">
        <div className="page-header">
          <span className="eyebrow">Memory</span>
          <h1>Persistent Conversation &amp; Task Memory</h1>
          <p>Backend initializing…</p>
        </div>
        <LoadingState label="Loading memory data" />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Memory</span>
          <h1>Persistent Conversation &amp; Task Memory</h1>
          <StatusPill
            status={stats?.enabled ? "healthy" : "degraded"}
            label={stats?.enabled ? "Memory enabled" : "Memory disabled"}
          />
          <p className="dim">
            Local SQLite-first. Raw history, summaries, episodes, facts, and durable
            tasks.
          </p>
        </div>
      </div>

      {error ? (
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">Memory error</span>
            {error}
          </div>
        </div>
      ) : null}

      <section>
        {mode === "stats" && renderStats()}
        {mode === "sessions" && renderSessions()}
        {mode === "facts" && renderFacts()}
        {mode === "tasks" && renderTasks()}
        {mode === "search" && renderSearch()}
      </section>

      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <div>
            <h2>Memory Modes</h2>
            <p className="panel-sub">
              Toggle between overview, session list, facts, tasks and search.
            </p>
          </div>
        </div>
        <div className="panel-body" style={{ marginTop: 10 }}>
          <button
            style={{ width: "30%", marginRight: 8 }}
            onClick={() => setMode("stats")}
            className={`secondary ${mode === "stats" ? "active" : ""}`}
          >
            Overview
          </button>
          <button
            style={{ width: "30%", marginRight: 8 }}
            onClick={() => setMode("sessions")}
            className={`secondary ${mode === "sessions" ? "active" : ""}`}
          >
            Sessions
          </button>
          <button
            style={{ width: "30%" }}
            onClick={() => setMode("facts")}
            className={`secondary ${mode === "facts" ? "active" : ""}`}
          >
            Facts
          </button>
        </div>
        <div className="panel-body" style={{ marginTop: 10 }}>
          <button
            style={{ width: "30%", marginRight: 8 }}
            onClick={() => setMode("tasks")}
            className={`secondary ${mode === "tasks" ? "active" : ""}`}
          >
            Tasks
          </button>
          <button
            style={{ width: "30%" }}
            onClick={() => void runSearch(query)}
            className={`secondary ${mode === "search" ? "active" : ""}`}
          >
            Search
          </button>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <div>
            <h2>Search Across Memory</h2>
            <p className="panel-sub">
              Search by keyword, date, topic or meaning across all stored sessions.
            </p>
          </div>
        </div>
        <div className="panel-body" style={{ marginTop: 10 }}>
          <form
            className="row"
            style={{ gap: 8 }}
            onSubmit={(event) => {
              event.preventDefault();
              void runSearch(query);
            }}
          >
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search…"
              aria-label="Search memory"
              style={{ flex: 1 }}
            />
            <button className="secondary" type="submit" disabled={modeLoading}>
              <Icon name="search" size={14} /> Search
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
