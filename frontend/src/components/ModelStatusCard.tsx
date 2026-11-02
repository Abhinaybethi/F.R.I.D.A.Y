import { statusLabel } from "../lib/format";
import type { ModelInfo } from "../lib/types";
import { StatusPill } from "./StatusPill";

interface ModelStatusCardProps {
  model: ModelInfo;
  onSelect?: (model: ModelInfo) => void;
  selected?: boolean;
}

function loadLabel(model: ModelInfo): string {
  if (model.loaded === null) return "Load state unknown";
  return model.loaded ? "Loaded" : "Not loaded";
}

export function ModelStatusCard({ model, onSelect, selected }: ModelStatusCardProps) {
  const clickable = Boolean(onSelect);
  return (
    <div
      className="list-row"
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? () => onSelect?.(model) : undefined}
      onKeyDown={
        clickable
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect?.(model);
              }
            }
          : undefined
      }
      style={{
        cursor: clickable ? "pointer" : "default",
        borderColor: selected ? "var(--line-purple)" : undefined,
        background: selected ? "rgba(139,92,246,0.09)" : undefined,
      }}
    >
      <div className="list-main">
        <div className="row between" style={{ gap: 8 }}>
          <span className="list-title" title={model.name}>
            {model.name || model.id}
          </span>
          <span className="row" style={{ gap: 6 }}>
            {model.active ? <StatusPill status="active" tone="accent" label="Active" /> : null}
            <StatusPill status={model.health} label={statusLabel(model.health)} />
          </span>
        </div>
        <div className="list-meta">
          <span className="chip">{model.family}</span>
          <span className="chip">{model.kind}</span>
          {model.quantization ? <span className="chip">{model.quantization}</span> : null}
          <span>{loadLabel(model)}</span>
          {model.context_window ? <span>{model.context_window.toLocaleString()} ctx</span> : null}
          {model.device ? <span>{model.device}</span> : null}
        </div>
        {model.path ? (
          <div className="tiny muted truncate" title={model.path}>
            {model.path}
          </div>
        ) : null}
        {model.error ? <div className="tiny" style={{ color: "var(--red)" }}>{model.error}</div> : null}
      </div>
    </div>
  );
}

export function ActiveModelSummary({ model }: { model: ModelInfo | null }) {
  if (!model) {
    return <p className="tiny muted">No active reasoning model reported.</p>;
  }
  return (
    <div className="stack-sm">
      <div className="row between">
        <strong className="truncate" title={model.name}>
          {model.name}
        </strong>
        <StatusPill status={model.health} />
      </div>
      <div className="list-meta">
        <span>{model.family}</span>
        {model.quantization ? <span>· {model.quantization}</span> : null}
        {model.endpoint ? <span>· {model.endpoint}</span> : null}
      </div>
      <div className="tiny muted">
        {model.loaded ? "Loaded · health probe passing" : "Not currently reachable"}
      </div>
    </div>
  );
}
