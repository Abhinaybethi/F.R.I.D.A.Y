import { useState } from "react";
import { NavLink } from "react-router-dom";

import { formatUptime, relativeTime, statusLabel, statusTone } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { Icon, type IconName } from "./Icon";

const PRIMARY: Array<{ to: string; label: string; icon: IconName; end?: boolean }> = [
  { to: "/", label: "Home", icon: "home", end: true },
  { to: "/chat", label: "Chat", icon: "chat" },
  { to: "/voice", label: "Voice", icon: "mic" },
  { to: "/news", label: "News", icon: "book" },
  { to: "/vision", label: "Vision", icon: "eye" },
  { to: "/image", label: "Create Image", icon: "image" },
  { to: "/research", label: "Research", icon: "search" },
  { to: "/code", label: "Code", icon: "code" },
  { to: "/memory", label: "Memory", icon: "archive" },
];

const OPERATIONS: Array<{ to: string; label: string; icon: IconName }> = [
  { to: "/automation", label: "Automation", icon: "bolt" },
  { to: "/projects", label: "Projects", icon: "folder" },
];

export function Sidebar() {
  const { agents, overview, health } = useDashboard();
  const [agentsOpen, setAgentsOpen] = useState(true);
  const [operationsOpen, setOperationsOpen] = useState(true);

  const working = agents.filter((agent) => agent.status === "working").length;
  const healthyCount = health ? Object.values(health.components).filter((c) => c.status === "healthy").length : 0;
  const totalServices = health ? Object.keys(health.components).length : 0;

  return (
    <aside className="sidebar" aria-label="Dashboard navigation">
      <nav className="side-section" aria-label="Workspace">
        <div className="side-title">
          <span>Workspace</span>
        </div>
        {PRIMARY.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
          >
            <span className="icon" aria-hidden="true">
              <Icon name={item.icon} size={16} />
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="side-section">
        <button
          type="button"
          className="side-title"
          style={{ border: "none", background: "none", cursor: "pointer", width: "100%" }}
          onClick={() => setOperationsOpen((open) => !open)}
          aria-expanded={operationsOpen}
        >
          <span>Operations</span>
          <Icon
            name="chevron"
            size={13}
            style={{ transform: operationsOpen ? "rotate(90deg)" : "none", transition: "transform 140ms" }}
          />
        </button>
        {operationsOpen
          ? OPERATIONS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
              >
                <span className="icon" aria-hidden="true">
                  <Icon name={item.icon} size={16} />
                </span>
                {item.label}
              </NavLink>
            ))
          : null}
      </div>

      <div className="side-section">
        <button
          type="button"
          className="side-title"
          style={{ border: "none", background: "none", cursor: "pointer", width: "100%" }}
          onClick={() => setAgentsOpen((open) => !open)}
          aria-expanded={agentsOpen}
        >
          <span>My Agents</span>
          <span className="row" style={{ gap: 6 }}>
            {working > 0 ? <span className="pill" data-tone="warn">{working} active</span> : null}
            <Icon
              name="chevron"
              size={13}
              style={{ transform: agentsOpen ? "rotate(90deg)" : "none", transition: "transform 140ms" }}
            />
          </span>
        </button>
        {agentsOpen ? (
          agents.length === 0 ? (
            <p className="tiny muted" style={{ padding: "4px 10px" }}>
              No agents reported by the backend yet.
            </p>
          ) : (
            agents.map((agent) => (
              <NavLink
                key={agent.id}
                to={`/agents?focus=${encodeURIComponent(agent.id)}`}
                className="side-agent"
                title={agent.current_task ?? agent.description}
              >
                <span
                  className="timeline-dot"
                  style={{ margin: 0 }}
                  data-tone={statusTone(agent.status)}
                  aria-hidden="true"
                />
                <span className="truncate" style={{ maxWidth: 112 }}>
                  {agent.name}
                </span>
                <span className="meta" title={`${statusLabel(agent.status)} · ${relativeTime(agent.last_activity)}`}>
                  {agent.status === "working" ? "working" : relativeTime(agent.last_activity)}
                </span>
              </NavLink>
            ))
          )
        ) : null}
        <NavLink
          to="/agents"
          className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
          style={{ marginTop: 4 }}
        >
          <span className="icon" aria-hidden="true">
            <Icon name="users" size={16} />
          </span>
          Agent console
        </NavLink>
      </div>

      <div className="side-footer">
        <div className="row between">
          <strong>{overview?.identity?.name ?? "F.R.I.D.A.Y"}</strong>
          <span>{overview?.identity ? formatUptime(overview.identity.uptime_seconds) : "—"}</span>
        </div>
        <div className="row between">
          <span>Services healthy</span>
          <span>
            {health ? `${healthyCount}/${totalServices}` : "—"}
          </span>
        </div>
        <div className="row between">
          <span>Tasks tracked</span>
          <span>{overview?.counts.total ?? 0}</span>
        </div>
        <p className="tiny" style={{ marginTop: 2 }}>
          Local-first. Some tools (web research) use outbound requests when invoked.
        </p>
      </div>
    </aside>
  );
}
