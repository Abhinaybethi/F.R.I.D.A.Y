import { NavLink } from "react-router-dom";

import { useDashboard } from "../state/DashboardContext";
import { ConnectionStatus } from "./ConnectionStatus";
import { Icon } from "./Icon";

const LINKS = [
  { to: "/", label: "Home", end: true },
  { to: "/chat", label: "Chat" },
  { to: "/agents", label: "Agents" },
  { to: "/workspace", label: "Workspace" },
  { to: "/models", label: "Models" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/settings", label: "Settings" },
];

interface DesktopBridge {
  minimize?: () => void;
  maximize?: () => void;
  close?: () => void;
}

function desktopBridge(): DesktopBridge | undefined {
  return (window as unknown as { fridayDesktop?: DesktopBridge }).fridayDesktop;
}

export function TopNavigation() {
  const { settings, identity } = useDashboardIdentity();
  const bridge = desktopBridge();
  const researchEnabled = settings?.research?.enabled === true;
  const offlineOnly = settings?.voice?.offline_only === true;

  const modeLabel = researchEnabled ? "Local-first" : offlineOnly ? "Local only" : "Local";
  const modeTitle = researchEnabled
    ? "Local models and storage. Web research is enabled, so research queries make outbound requests when you run them."
    : "Configured for local operation; no cloud inference is configured.";

  return (
    <header className="top-nav">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          FR
        </span>
        <span className="brand-name">
          <strong>F.R.I.D.A.Y</strong>
          <span>v{identity?.version ?? "—"} · local ai console</span>
        </span>
      </div>

      <nav className="top-links" aria-label="Primary">
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={({ isActive }) => `top-link${isActive ? " active" : ""}`}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>

      <div className="top-right">
        <span className="local-mode" data-mode={researchEnabled ? "hybrid" : "local"} title={modeTitle}>
          <span className="dot" aria-hidden="true" />
          <span>{modeLabel}</span>
        </span>
        <ConnectionStatus />
        <div className="window-controls" aria-label="Window controls">
          <button
            type="button"
            aria-label="Minimize"
            title={bridge?.minimize ? "Minimize window" : "Window controls need the desktop shell"}
            disabled={!bridge?.minimize}
            onClick={() => bridge?.minimize?.()}
          >
            <Icon name="minimize" size={14} />
          </button>
          <button
            type="button"
            aria-label="Maximize"
            title={bridge?.maximize ? "Maximize window" : "Window controls need the desktop shell"}
            disabled={!bridge?.maximize}
            onClick={() => bridge?.maximize?.()}
          >
            <Icon name="maximize" size={13} />
          </button>
          <button
            type="button"
            className="close"
            aria-label="Close"
            title={bridge?.close ? "Close window" : "Window controls need the desktop shell"}
            disabled={!bridge?.close}
            onClick={() => bridge?.close?.()}
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      </div>
    </header>
  );
}

function useDashboardIdentity() {
  const { settings, overview } = useDashboard();
  return { settings, identity: overview?.identity ?? settings?.identity ?? null };
}
