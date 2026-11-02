import { useState } from "react";

import { api, ApiError } from "../lib/api";
import { formatDuration, relativeTime } from "../lib/format";
import type { ResearchResponse, ResearchResult } from "../lib/types";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

interface ResearchState {
  status: "idle" | "running" | "done" | "failed";
  response: ResearchResponse | null;
  error: string | null;
  duration: number;
  query: string;
}

const INITIAL: ResearchState = { status: "idle", response: null, error: null, duration: 0, query: "" };

export function ResearchPanel() {
  const { activity, refreshActivity, settings } = useDashboard();
  const [query, setQuery] = useState("");
  const [state, setState] = useState<ResearchState>(INITIAL);

  const researchEnabled = settings?.research?.enabled !== false;

  const run = async () => {
    const text = query.trim();
    if (!text || state.status === "running") return;
    setState({ status: "running", response: null, error: null, duration: 0, query: text });
    const started = performance.now();
    try {
      const response = await api.research(text);
      setState({
        status: "done",
        response,
        error: null,
        duration: performance.now() - started,
        query: text,
      });
    } catch (error) {
      setState({
        status: "failed",
        response: null,
        error: error instanceof ApiError ? error.message : "Research request failed.",
        duration: performance.now() - started,
        query: text,
      });
    } finally {
      void refreshActivity();
    }
  };

  const sources: ResearchResult[] = Array.isArray(state.response?.results)
    ? (state.response?.results as ResearchResult[])
    : [];
  const errorPayload = state.response?.error;
  const errorMessage =
    state.error ??
    (typeof errorPayload === "string"
      ? errorPayload
      : errorPayload && typeof errorPayload === "object" && "message" in errorPayload
        ? String((errorPayload as { message?: string }).message ?? "")
        : "");

  const history = activity.filter((item) => item.kind === "research").slice(0, 5);

  return (
    <div className="stack">
      {!researchEnabled ? (
        <div className="alert" data-tone="info">
          <div>
            <span className="alert-title">Web research is disabled in config</span>
            The backend will return immediately without searching. Enable <code>research.enabled</code> to
            allow live queries.
          </div>
        </div>
      ) : null}

      <div className="stack-sm">
        <label className="tiny muted" htmlFor="research-query">
          Research question
        </label>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <input
            id="research-query"
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="What would you like to research on the live web?"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void run();
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void run()}
            disabled={state.status === "running" || query.trim().length === 0}
          >
            {state.status === "running" ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <Icon name="search" size={14} />
            )}
            {state.status === "running" ? "Researching…" : "Research"}
          </button>
        </div>
        <p className="tiny muted">
          Live provider results. Local document retrieval is separate — see the Knowledge page. Sources are
          never invented: an empty result set stays empty.
        </p>
      </div>

      {state.status === "idle" ? (
        <EmptyState
          title="No research run yet"
          description="Submit a question to run the real research pipeline. The router may decide a query needs no web search, in which case it reports that instead of fabricating sources."
          icon="search"
        />
      ) : null}

      {state.status === "failed" ? (
        <div className="alert" data-tone="error" role="alert">
          <div>
            <span className="alert-title">Research failed after {formatDuration(state.duration)}</span>
            {errorMessage || "The backend reported a failure without a message."}
          </div>
        </div>
      ) : null}

      {state.status === "done" && state.response ? (
        <div className="stack-sm">
          <div className="row wrap between">
            <div className="row" style={{ gap: 8 }}>
              <StatusPill
                status={state.response.success ? "completed" : "failed"}
                label={state.response.success ? "Completed" : "Failed"}
              />
              <span className="tiny muted">
                {sources.length} source{sources.length === 1 ? "" : "s"} ·{" "}
                {formatDuration(
                  typeof state.response.elapsed_ms === "number" ? state.response.elapsed_ms : state.duration,
                )}
              </span>
            </div>
            <div className="chip-row">
              {state.response.provider ? <span className="chip">{String(state.response.provider)}</span> : null}
              {state.response.query_type ? <span className="chip">{String(state.response.query_type)}</span> : null}
              <span className="chip">
                {state.response.needs_web ? "live web search" : "no web search performed"}
              </span>
            </div>
          </div>

          {errorMessage ? (
            <div className="alert" data-tone="error" role="alert">
              {errorMessage}
            </div>
          ) : null}

          {state.response.success && !state.response.needs_web ? (
            <div className="alert" data-tone="info">
              <div>
                <span className="alert-title">No web search was performed</span>
                The research router decided this query did not require live sources
                {state.response.search_queries?.length
                  ? ` (queries considered: ${state.response.search_queries.join(", ")}).`
                  : "."}
              </div>
            </div>
          ) : null}

          {sources.length === 0 ? (
            <EmptyState
              title="No sources returned"
              description={
                state.response.needs_web
                  ? "The provider returned zero results. The dashboard will not fabricate citations."
                  : "This query did not trigger a web search, so there are no sources to show."
              }
              icon="search"
            />
          ) : (
            <ol className="list" style={{ paddingLeft: 0, listStyle: "none" }}>
              {sources.map((source, index) => (
                <li className="list-row" key={`${String(source.url ?? index)}-${index}`}>
                  <div className="list-main">
                    <div className="row between" style={{ gap: 8 }}>
                      {source.url ? (
                        <a
                          href={String(source.url)}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="list-title"
                        >
                          {String(source.title || source.url)}
                          <Icon name="external" size={12} style={{ marginLeft: 6 }} />
                        </a>
                      ) : (
                        <span className="list-title">{String(source.title ?? "Untitled result")}</span>
                      )}
                      <span className="tiny muted">#{source.rank ?? index + 1}</span>
                    </div>
                    {source.snippet ? (
                      <p className="tiny dim" style={{ marginTop: 3 }}>
                        {String(source.snippet)}
                      </p>
                    ) : null}
                    <div className="list-meta">
                      {source.source ? <span>{String(source.source)}</span> : null}
                      {source.url ? <span className="truncate" style={{ maxWidth: 360 }}>{String(source.url)}</span> : null}
                      {source.published_at ? <span>· {String(source.published_at)}</span> : null}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : null}

      <div>
        <div className="panel-head" style={{ marginBottom: 6 }}>
          <h3>Recent research</h3>
        </div>
        {history.length === 0 ? (
          <p className="tiny muted">No research tasks recorded yet.</p>
        ) : (
          <div className="list">
            {history.map((item) => (
              <div className="list-row" key={item.id}>
                <div className="list-main">
                  <div className="row between">
                    <span className="list-title">{item.title}</span>
                    <StatusPill status={item.status} />
                  </div>
                  <div className="list-meta">
                    <span>{relativeTime(item.created_at)}</span>
                    {item.message ? <span>· {item.message}</span> : null}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
