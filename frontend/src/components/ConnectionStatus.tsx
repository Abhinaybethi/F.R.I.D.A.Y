import { relativeTime } from "../lib/format";
import { dashboardSocket } from "../lib/ws";
import { useDashboard } from "../state/DashboardContext";

const LABELS: Record<string, string> = {
  connected: "Live",
  connecting: "Connecting",
  reconnecting: "Reconnecting",
  disconnected: "Offline",
  degraded: "Degraded",
};

export function ConnectionStatus({ compact = false }: { compact?: boolean }) {
  const { connection, connectionDetail, backendReachable, lastEventAt } = useDashboard();
  const effective = backendReachable ? connection : "disconnected";
  const label = LABELS[effective] ?? effective;

  return (
    <button
      type="button"
      className="conn-badge"
      data-state={effective}
      title={
        connectionDetail ||
        (lastEventAt ? `Last event ${relativeTime(lastEventAt)}` : "Waiting for the first event")
      }
      onClick={() => dashboardSocket.reconnectNow()}
      aria-label={`Backend connection: ${label}. Click to reconnect.`}
    >
      <span className="dot" aria-hidden="true" />
      <span>{label}</span>
      {!compact && backendReachable === false ? (
        <span className="tiny" aria-hidden="true">
          ·
        </span>
      ) : null}
      {!compact && backendReachable === false ? <span className="tiny">backend unreachable</span> : null}
    </button>
  );
}
