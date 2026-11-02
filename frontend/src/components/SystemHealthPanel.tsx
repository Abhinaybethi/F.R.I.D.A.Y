import { formatClock, statusLabel } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";
import { LoadingState } from "./LoadingState";
import { StatusPill } from "./StatusPill";

const COMPONENT_LABELS: Record<string, string> = {
  backend: "Backend API",
  config: "Configuration",
  reasoning: "Reasoning server",
  image: "Image generation",
  research: "Web research",
  rag: "Knowledge retrieval",
  stt: "Speech recognition",
  tts: "Text to speech",
  websocket: "Dashboard events",
  microphone: "Microphone",
};

export function SystemHealthPanel() {
  const { health, booting } = useDashboard();

  if (!health) {
    return booting ? <LoadingState label="Checking services" /> : (
      <EmptyState
        title="Health unavailable"
        description="The backend has not reported service health yet."
        icon="shield"
      />
    );
  }

  const entries = Object.entries(health.components);
  const healthy = entries.filter(([, component]) => component.status === "healthy").length;
  const allHealthy = healthy === entries.length && entries.length > 0;
  const headline = allHealthy
    ? `${healthy}/${entries.length} services healthy`
    : `${entries.length - healthy} of ${entries.length} services need attention`;

  return (
    <div className="stack-sm">
      <div className="row between" style={{ marginBottom: 2 }}>
        <div className="row" style={{ gap: 8 }}>
          <StatusPill status={health.overall} label={statusLabel(health.overall)} />
          <span className="tiny muted">{headline}</span>
        </div>
        <span className="tiny muted" title={health.timestamp}>
          checked {formatClock(health.timestamp)}
        </span>
      </div>

      <div>
        {entries.map(([name, component]) => (
          <div className="service-row" key={name}>
            <span style={{ marginTop: 5 }}>
              <StatusPill status={component.status} subtle label="" title={component.status} />
            </span>
            <div className="grow">
              <div className="row between" style={{ gap: 8 }}>
                <span className="service-name">{COMPONENT_LABELS[name] ?? name}</span>
                <span className="tiny muted">{statusLabel(component.status)}</span>
              </div>
              {component.detail ? <div className="service-detail">{component.detail}</div> : null}
            </div>
          </div>
        ))}
      </div>

      {!allHealthy ? (
        <p className="tiny muted">
          Overall status is computed from real probes: a required service that is not healthy keeps the
          dashboard out of the “all online” state. Individual failures are not treated as permanent.
        </p>
      ) : null}
    </div>
  );
}
