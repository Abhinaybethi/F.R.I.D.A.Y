import { Link } from "react-router-dom";

import { relativeTime, statusLabel } from "../lib/format";
import type { AgentInfo } from "../lib/types";
import { EmptyState } from "./EmptyState";
import { StatusPill } from "./StatusPill";

export function AgentStatusList({ agents, limit }: { agents: AgentInfo[]; limit?: number }) {
  if (agents.length === 0) {
    return (
      <EmptyState
        title="No agents registered"
        description="The backend derives agents from its real subsystems. None are currently reported."
        icon="users"
      />
    );
  }
  const visible = typeof limit === "number" ? agents.slice(0, limit) : agents;

  return (
    <div className="list">
      {visible.map((agent) => (
        <div className="list-row" key={agent.id}>
          <div className="list-main">
            <div className="row between" style={{ gap: 8 }}>
              <Link to={`/agents?focus=${encodeURIComponent(agent.id)}`} className="list-title" style={{ color: "inherit" }}>
                {agent.name}
              </Link>
              <StatusPill status={agent.status} label={statusLabel(agent.status)} />
            </div>
            <div className="list-meta">
              <span className="truncate" style={{ maxWidth: 260 }} title={agent.current_task ?? agent.description}>
                {agent.current_task ?? agent.description}
              </span>
              <span>· {relativeTime(agent.last_activity)}</span>
              {agent.last_error ? <span style={{ color: "var(--red)" }}>· {agent.last_error}</span> : null}
            </div>
          </div>
        </div>
      ))}
      {typeof limit === "number" && agents.length > limit ? (
        <Link to="/agents" className="tiny" style={{ padding: "8px 4px" }}>
          View all {agents.length} agents →
        </Link>
      ) : null}
    </div>
  );
}
