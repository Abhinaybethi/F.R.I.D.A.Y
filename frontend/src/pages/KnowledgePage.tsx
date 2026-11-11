import { useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../lib/api";
import { formatBytes, formatDateTime } from "../lib/format";
import type { KnowledgeResponse } from "../lib/types";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function KnowledgePage() {
  const { health, settings } = useDashboard();
  const [data, setData] = useState<KnowledgeResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .knowledge()
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setState("ready");
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(reason instanceof ApiError ? reason.message : "Knowledge documents unavailable.");
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const ragHealth = health?.components?.rag;
  const filtered = useMemo(() => {
    if (!data) return [];
    const needle = search.trim().toLowerCase();
    if (!needle) return data.documents;
    return data.documents.filter(
      (document) =>
        document.name.toLowerCase().includes(needle) || document.path.toLowerCase().includes(needle),
    );
  }, [data, search]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Knowledge</span>
          <h1>Local knowledge base</h1>
          <p>
            Documents the local RAG index can see, read from the configured source directories. Retrieval
            happens inside chat; this page does not fabricate retrieved passages.
          </p>
        </div>
        <StatusPill status={ragHealth?.status ?? "unknown"} label={`RAG ${ragHealth?.status ?? "unknown"}`} />
      </div>

      <div className="grid grid-3">
        <div className="stat-tile">
          <span className="label">Collection</span>
          <span className="value" style={{ fontSize: "0.95rem" }}>
            {data?.collection ?? "—"}
          </span>
          <span className="foot">{data?.enabled ? "enabled in config" : "disabled in config"}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Indexable documents</span>
          <span className="value">{data?.count ?? "—"}</span>
          <span className="foot">metadata only — content is not exposed</span>
        </div>
        <div className="stat-tile">
          <span className="label">Source directories</span>
          <span className="value" style={{ fontSize: "0.9rem" }}>
            {data?.source_dirs.length ?? 0}
          </span>
          <span className="foot">configured under rag.source_dirs</span>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Indexable files</h2>
            <p className="panel-sub">Names and sizes only; secrets and credentials are never served</p>
          </div>
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Filter documents…"
            aria-label="Filter documents"
            style={{ maxWidth: 240 }}
          />
        </div>
        <div className="panel-body">
          {state === "loading" ? (
            <LoadingState label="Scanning configured directories" />
          ) : state === "error" ? (
            <div className="alert" data-tone="error" role="alert">
              <div>
                <span className="alert-title">Knowledge unavailable</span>
                {error}
              </div>
            </div>
          ) : !data || data.documents.length === 0 ? (
            <EmptyState
              title="No indexable documents found"
              description="The configured source directories contain no supported document types (.md, .txt, .pdf, .json, .yaml)."
              icon="book"
            />
          ) : (
            <>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Document</th>
                      <th scope="col">Type</th>
                      <th scope="col">Size</th>
                      <th scope="col">Modified</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((document) => (
                      <tr key={document.path}>
                        <td>
                          <div style={{ fontWeight: 500 }}>{document.name}</div>
                          <div className="tiny muted mono truncate" title={document.path}>
                            {document.path}
                          </div>
                        </td>
                        <td className="tiny">{document.suffix.replace(".", "").toUpperCase()}</td>
                        <td className="tiny">{formatBytes(document.size_bytes)}</td>
                        <td className="tiny">{formatDateTime(document.modified_at * 1000)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filtered.length === 0 ? (
                <EmptyState title="No matches" description="Clear the filter to see all documents." icon="search" />
              ) : null}
            </>
          )}
          {data?.errors.length ? (
            <div className="alert" data-tone="error" style={{ marginTop: 10 }}>
              <div>
                <span className="alert-title">Some directories could not be scanned</span>
                {data.errors.join(" · ")}
              </div>
            </div>
          ) : null}
          <p className="tiny muted" style={{ marginTop: 10 }}>
            {data?.note ??
              "Retrieval requires the RAG service; this page only reports files it can enumerate."}
            {settings?.research?.enabled
              ? " Web research is a separate pipeline and its sources are shown on the Research page."
              : ""}
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>How retrieval is used</h2>
            <p className="panel-sub">Grounded answers, not a document browser</p>
          </div>
        </div>
        <div className="panel-body">
          <p className="tiny dim">
            When you ask a question in Chat, the existing RAG service may retrieve passages from this local
            collection and pass them to the reasoning model. The dashboard displays the model&apos;s answer
            and the model attribution; it does not claim which passage was used unless the backend returns
            that evidence. No document contents are sent to a cloud service.
          </p>
          <div className="row" style={{ marginTop: 10 }}>
            <Icon name="shield" size={14} />
            <span className="tiny muted">Local-first: indexing and retrieval stay on this machine.</span>
          </div>
        </div>
      </section>
    </div>
  );
}
