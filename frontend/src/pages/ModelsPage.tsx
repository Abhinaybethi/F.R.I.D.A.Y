import { useMemo, useState } from "react";

import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { ModelStatusCard } from "../components/ModelStatusCard";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function ModelsPage() {
  const { models, activeModel, refresh, settings } = useDashboard();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const selected = useMemo(
    () => models.find((model) => model.id === selectedId) ?? activeModel ?? models[0] ?? null,
    [models, selectedId, activeModel],
  );

  const reload = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Models</span>
          <h1>Model registry</h1>
          <p>
            Read from the live configuration and health probes. A model is marked loaded only when its
            inference server actually answers — never because a file exists.
          </p>
        </div>
        <button type="button" className="btn btn-sm" onClick={() => void reload()} disabled={refreshing}>
          <Icon name="refresh" size={13} /> {refreshing ? "Probing…" : "Refresh"}
        </button>
      </div>

      {models.length === 0 ? (
        <EmptyState
          title="No models reported"
          description="The backend did not return any configured model entries."
          icon="chip"
        />
      ) : (
        <div className="grid grid-2" style={{ alignItems: "start" }}>
          <section className="panel" aria-label="Models">
            <div className="panel-head">
              <div>
                <h2>Configured models</h2>
                <p className="panel-sub">{models.length} entries · select to inspect</p>
              </div>
            </div>
            <div className="panel-body list">
              {models.map((model) => (
                <ModelStatusCard
                  key={model.id}
                  model={model}
                  selected={selected?.id === model.id}
                  onSelect={(entry) => setSelectedId(entry.id)}
                />
              ))}
            </div>
            <p className="tiny muted" style={{ marginTop: 10 }}>
              Loading and unloading models is managed by the backend at request time and by the reasoning
              server lifecycle. This dashboard does not ship a load/unload endpoint, so no such buttons are
              shown.
            </p>
          </section>

          <div className="stack">
            {selected ? (
              <section className="panel panel-accent" aria-labelledby="model-detail">
                <div className="panel-head">
                  <div>
                    <h2 id="model-detail">{selected.name}</h2>
                    <p className="panel-sub">{selected.family}</p>
                  </div>
                  <StatusPill status={selected.health} />
                </div>
                <div className="panel-body">
                  <dl className="kv">
                    <dt>Identifier</dt>
                    <dd className="mono">{selected.id}</dd>
                    <dt>Kind</dt>
                    <dd>{selected.kind}</dd>
                    <dt>Provider</dt>
                    <dd>{selected.provider ?? "—"}</dd>
                    <dt>Quantization</dt>
                    <dd>{selected.quantization || "not encoded in filename"}</dd>
                    <dt>Loaded</dt>
                    <dd>
                      {selected.loaded === null
                        ? "Unknown — not probed"
                        : selected.loaded
                          ? "Yes (server responded)"
                          : "No (server unreachable)"}
                    </dd>
                    <dt>Context</dt>
                    <dd>{selected.context_window ? selected.context_window.toLocaleString() : "not reported"}</dd>
                    <dt>Endpoint</dt>
                    <dd className="mono">{selected.endpoint ?? "—"}</dd>
                    <dt>Path</dt>
                    <dd className="mono">{selected.path || "—"}</dd>
                  </dl>

                  {selected.components ? (
                    <div style={{ marginTop: 12 }}>
                      <span className="tiny muted">Image pipeline components</span>
                      <div className="chip-row" style={{ marginTop: 4 }}>
                        {Object.entries(selected.components).map(([key, value]) => (
                          <span className="chip" key={key}>
                            {key}: {value || "missing"}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {selected.error ? (
                    <div className="alert" data-tone="error" style={{ marginTop: 12 }}>
                      <div>
                        <span className="alert-title">Health note</span>
                        {selected.error}
                      </div>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}

            <section className="panel" aria-labelledby="model-constraints">
              <div className="panel-head">
                <div>
                  <h2 id="model-constraints">Hardware constraints</h2>
                  <p className="panel-sub">Why only one large model is active at a time</p>
                </div>
              </div>
              <div className="panel-body">
                <p className="tiny dim">
                  Reasoning uses{" "}
                  <span className="code-inline">{settings?.reasoning?.provider ?? "llamacpp"}</span> at{" "}
                  <span className="code-inline">{settings?.reasoning?.endpoint ?? "—"}</span>. The image
                  pipeline releases the reasoner&apos;s VRAM before generation when{" "}
                  <span className="code-inline">free_vram_before_generate</span> is enabled. The dashboard
                  will not start duplicate inference servers.
                </p>
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
