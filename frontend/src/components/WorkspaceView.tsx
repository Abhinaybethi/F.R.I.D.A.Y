import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../lib/api";
import { formatBytes, formatDateTime } from "../lib/format";
import type { WorkspaceResponse } from "../lib/types";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { LoadingState } from "./LoadingState";
import { StatusPill } from "./StatusPill";

export function WorkspaceView({ mode }: { mode: "workspace" | "projects" }) {
  const [data, setData] = useState<WorkspaceResponse | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const payload = await api.workspace();
      setData(payload);
      setState("ready");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Workspace unavailable.");
      setState("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (state === "loading") return <LoadingState label="Reading workspace" />;
  if (state === "error") {
    return (
      <div className="alert" data-tone="error" role="alert">
        <div>
          <span className="alert-title">Workspace unavailable</span>
          {error}
        </div>
      </div>
    );
  }
  if (!data) return <EmptyState title="No workspace data" icon="folder" />;

  return (
    <div className="stack">
      {mode === "projects" ? (
        <section className="panel" aria-labelledby="project-list">
          <div className="panel-head">
            <div>
              <h2 id="project-list">Registered projects</h2>
              <p className="panel-sub">Only projects that exist locally are listed</p>
            </div>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => void load()}>
              <Icon name="refresh" size={12} /> Refresh
            </button>
          </div>
          <div className="panel-body list">
            {data.projects.length === 0 ? (
              <EmptyState title="No projects" description="No project directories are registered." icon="folder" />
            ) : (
              data.projects.map((project) => (
                <div className="list-row" key={project.id}>
                  <div className="list-main">
                    <div className="row between">
                      <span className="list-title">{project.name}</span>
                      <StatusPill status={project.status} label={project.status === "active" ? "Active" : project.status} />
                    </div>
                    <div className="list-meta">
                      <span className="chip">{project.kind}</span>
                      <span>{project.detail}</span>
                    </div>
                    <div className="tiny muted mono truncate" title={project.path}>
                      {project.path}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      ) : null}

      <section className="panel" aria-labelledby="workspace-root">
        <div className="panel-head">
          <div>
            <h2 id="workspace-root">Workspace root</h2>
            <p className="panel-sub">Read-only filesystem metadata</p>
          </div>
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => void load()}>
            <Icon name="refresh" size={12} /> Refresh
          </button>
        </div>
        <div className="panel-body">
          <dl className="kv">
            <dt>Path</dt>
            <dd className="mono">{data.root.path ?? "—"}</dd>
            <dt>Name</dt>
            <dd>{data.root.name ?? "—"}</dd>
            <dt>Documents</dt>
            <dd className="mono">{data.documents_dir}</dd>
            <dt>RAG</dt>
            <dd>
              {data.rag.enabled ? "enabled" : "disabled"} ·{" "}
              <span className="mono">{data.rag.collection ?? "—"}</span>
            </dd>
          </dl>
          <p className="tiny muted" style={{ marginTop: 8 }}>
            {data.note}
          </p>
        </div>
      </section>

      <section className="panel" aria-labelledby="workspace-dirs">
        <div className="panel-head">
          <div>
            <h2 id="workspace-dirs">Present directories</h2>
            <p className="panel-sub">Only paths that exist on disk</p>
          </div>
        </div>
        <div className="panel-body">
          {data.directories.length === 0 ? (
            <EmptyState title="Nothing found" description="No expected workspace directories exist yet." icon="folder" />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Directory</th>
                    <th scope="col">Type</th>
                    <th scope="col">Size</th>
                    <th scope="col">Modified</th>
                  </tr>
                </thead>
                <tbody>
                  {data.directories.map((entry) => (
                    <tr key={entry.path}>
                      <td>
                        <div style={{ fontWeight: 500 }}>{entry.name}</div>
                        <div className="tiny muted mono truncate" title={entry.path}>
                          {entry.path}
                        </div>
                      </td>
                      <td className="tiny">{entry.is_dir ? "Directory" : "File"}</td>
                      <td className="tiny">{entry.size_bytes === null ? "—" : formatBytes(entry.size_bytes)}</td>
                      <td className="tiny">{formatDateTime(entry.modified_at * 1000)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="tiny muted" style={{ marginTop: 10 }}>
            The dashboard never deletes files or executes arbitrary shell commands. File actions remain in
            the permission-gated tool registry.
          </p>
        </div>
      </section>
    </div>
  );
}
