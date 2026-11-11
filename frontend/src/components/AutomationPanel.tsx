import { useMemo, useState } from "react";

import { formatDuration } from "../lib/format";
import type { ToolInfo } from "../lib/types";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

interface ExecutionState {
  tool: string;
  ok: boolean;
  message: string;
  duration: number;
  finalStatus: string;
}

export function AutomationPanel() {
  const { tools, executeTool, counts } = useDashboard();
  const [selected, setSelected] = useState<ToolInfo | null>(null);
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState("");
  const [argumentsText, setArgumentsText] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ExecutionState | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return tools;
    return tools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(needle) ||
        (tool.permission_key ?? "").toLowerCase().includes(needle),
    );
  }, [tools, search]);

  const begin = (tool: ToolInfo) => {
    setSelected(tool);
    setTarget("");
    setArgumentsText("");
    setConfirm(false);
    setFormError(null);
    setResult(null);
  };

  const run = async () => {
    if (!selected || busy) return;
    setFormError(null);
    let parsed: Record<string, unknown> = {};
    if (argumentsText.trim()) {
      try {
        const value = JSON.parse(argumentsText);
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          throw new Error("Arguments must be a JSON object.");
        }
        parsed = value as Record<string, unknown>;
      } catch (error) {
        setFormError(error instanceof Error ? error.message : "Invalid JSON arguments.");
        return;
      }
    }
    if (selected.requires_confirmation && !confirm) {
      setFormError("This action requires explicit confirmation.");
      return;
    }

    setBusy(true);
    const started = performance.now();
    const outcome = await executeTool(selected.id, {
      target,
      arguments: parsed,
      confirm,
    });
    const duration = performance.now() - started;
    setResult({
      tool: selected.name,
      ok: outcome.ok,
      message: outcome.message,
      duration,
      finalStatus: outcome.ok ? "completed" : "failed",
    });
    setBusy(false);
  };

  if (tools.length === 0) {
    return (
      <EmptyState
        title="No tools reported"
        description="The backend did not return a tool registry. Nothing can be executed until it does."
        icon="terminal"
      />
    );
  }

  return (
    <div className="stack">
      <div className="row wrap between">
        <div className="row" style={{ gap: 8 }}>
          <StatusPill
            status={counts.running > 0 ? "running" : "idle"}
            label={`${counts.running} running`}
            subtle={counts.running === 0}
          />
          <span className="tiny muted">
            {filtered.length} of {tools.length} tools · permission-gated by the backend registry
          </span>
        </div>
        <input
          type="text"
          placeholder="Filter tools…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Filter tools"
          style={{ maxWidth: 240 }}
        />
      </div>

      {selected ? (
        <div className="panel panel-accent" style={{ padding: 16 }}>
          <div className="row between">
            <strong className="row" style={{ gap: 8 }}>
              <Icon name="terminal" size={15} /> {selected.name}
            </strong>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setSelected(null)}>
              Close
            </button>
          </div>

          <div className="list-meta" style={{ marginTop: 6 }}>
            <span className="chip">{selected.permission_key ?? "system"}</span>
            {selected.dry_run ? <span className="chip">dry run</span> : <span className="chip">real execution</span>}
            {selected.requires_confirmation ? <span className="chip">confirmation required</span> : null}
            {!selected.allowed ? <span className="chip">blocked by permissions</span> : null}
          </div>

          <div className="stack-sm" style={{ marginTop: 12 }}>
            <div className="field">
              <label htmlFor="tool-target">Target</label>
              <input
                id="tool-target"
                type="text"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                placeholder="Target for this action (leave blank if unused)"
              />
            </div>
            <div className="field">
              <label htmlFor="tool-args">Extra arguments (JSON object, optional)</label>
              <textarea
                id="tool-args"
                value={argumentsText}
                onChange={(event) => setArgumentsText(event.target.value)}
                placeholder='{"application": "..."}'
                rows={2}
                spellCheck={false}
              />
            </div>
            {selected.requires_confirmation ? (
              <label className="row" style={{ gap: 8, fontSize: "0.8rem" }}>
                <input
                  type="checkbox"
                  checked={confirm}
                  onChange={(event) => setConfirm(event.target.checked)}
                  style={{ width: 16, height: 16 }}
                />
                I understand this action changes system state.
              </label>
            ) : null}

            {formError ? (
              <div className="alert" data-tone="error" role="alert">
                {formError}
              </div>
            ) : null}

            {result ? (
              <div className="alert" data-tone={result.ok ? "info" : "error"} role="status">
                <div>
                  <span className="alert-title">
                    {result.tool} {result.ok ? "completed" : "failed"} · {formatDuration(result.duration)}
                  </span>
                  {result.message}
                </div>
              </div>
            ) : null}

            <div className="row">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void run()}
                disabled={busy || !selected.allowed}
                title={selected.allowed ? "Execute through the real tool registry" : "Disabled by permissions"}
              >
                {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="bolt" size={14} />}
                {busy ? "Executing…" : "Execute"}
              </button>
              <span className="tiny muted">
                Runs through <span className="code-inline">friday.tools.registry</span> with the configured
                dry-run and permission gates.
              </span>
            </div>
          </div>
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Tool</th>
              <th scope="col">Permission</th>
              <th scope="col">Mode</th>
              <th scope="col">Status</th>
              <th scope="col" />
            </tr>
          </thead>
          <tbody>
            {filtered.map((tool) => (
              <tr key={tool.id}>
                <td>
                  <div style={{ fontWeight: 500 }}>{tool.name}</div>
                  <div className="tiny muted mono">{tool.id}</div>
                </td>
                <td className="mono tiny">{tool.permission_key ?? "system"}</td>
                <td className="tiny">{tool.dry_run ? "Dry run" : "Real"}</td>
                <td>
                  <StatusPill
                    status={tool.allowed ? "healthy" : "unavailable"}
                    label={tool.allowed ? "Enabled" : "Disabled"}
                  />
                </td>
                <td style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => begin(tool)}
                    disabled={!tool.allowed}
                    title={tool.allowed ? "Configure and run" : "Blocked by permissions"}
                  >
                    Configure
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 ? (
        <EmptyState title="No tools match" description="Clear the filter to see the full registry." icon="search" />
      ) : null}
    </div>
  );
}
