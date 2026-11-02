import { ChatPanel } from "../components/ChatPanel";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function ChatPage() {
  const { activeModel, settings, chatMessages } = useDashboard();

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Conversation</span>
          <h1>Chat with F.R.I.D.A.Y</h1>
          <p>
            Routed through the existing conversation manager and local reasoning provider. Commands can
            trigger real tools; ordinary questions are answered by the active local model.
          </p>
        </div>
        <StatusPill
          status={activeModel?.loaded ? "healthy" : "unknown"}
          label={activeModel?.name ?? "No model reported"}
          title={activeModel?.endpoint ?? "Configured reasoning endpoint"}
        />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
        <section className="panel" aria-label="Conversation">
          <div className="panel-body">
            <ChatPanel />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>How this connects</h2>
            <p className="panel-sub">No cloud inference is configured or used</p>
          </div>
        </div>
        <div className="panel-body">
          <dl className="kv">
            <dt>Provider</dt>
            <dd>{settings?.reasoning?.provider ?? "unknown"}</dd>
            <dt>Endpoint</dt>
            <dd className="mono">{settings?.reasoning?.endpoint ?? "—"}</dd>
            <dt>Model</dt>
            <dd className="mono">{settings?.reasoning?.model ?? "—"}</dd>
            <dt>Timeout</dt>
            <dd>{settings?.reasoning?.timeout ? `${settings.reasoning.timeout}s` : "—"}</dd>
            <dt>Messages</dt>
            <dd>{chatMessages.length} stored locally in this browser</dd>
            <dt>Streaming</dt>
            <dd>Not exposed by the backend; responses arrive as a single completion.</dd>
          </dl>
        </div>
      </section>
    </div>
  );
}
