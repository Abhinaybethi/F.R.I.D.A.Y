import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { Icon, type IconName } from "../components/Icon";
import { LiveTranscript } from "../components/LiveTranscript";
import { RecentActivityTimeline } from "../components/RecentActivityTimeline";
import { StatusPill } from "../components/StatusPill";
import { SystemHealthPanel } from "../components/SystemHealthPanel";
import { VoiceInteractionPanel } from "../components/VoiceInteractionPanel";
import { formatUptime } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";

const SHORTCUTS: Array<{ to: string; title: string; description: string; icon: IconName }> = [
  { to: "/chat", title: "Chat", description: "Talk to the local reasoning model", icon: "chat" },
  { to: "/voice", title: "Voice", description: "Pipeline state and transcript", icon: "mic" },
  { to: "/image", title: "Create Image", description: "Qwen-Image, fully local", icon: "image" },
  { to: "/research", title: "Research", description: "Live web sources", icon: "search" },
  { to: "/automation", title: "Automation", description: "Permission-gated tools", icon: "bolt" },
  { to: "/agents", title: "Agents", description: "Live subsystem status", icon: "users" },
];

export function HomePage() {
  const { overview, metrics, health, agents, counts, booting, activeModel } = useDashboard();
  const working = agents.filter((agent) => agent.status === "working").length;
  const healthyServices = health
    ? Object.values(health.components).filter((component) => component.status === "healthy").length
    : 0;
  const totalServices = health ? Object.keys(health.components).length : 0;

  return (
    <div className="page">
      <section className="hero" aria-labelledby="home-title">
        <div className="row wrap between">
          <span className="eyebrow">Personal AI operating environment</span>
          <StatusPill
            status={overview?.state ?? (booting ? "starting" : "unknown")}
            label={overview?.state === "ready" ? "Backend ready" : (overview?.state ?? "Waiting")}
          />
        </div>
        <h1 id="home-title">
          Welcome back. I&apos;m <span style={{ color: "var(--cyan)" }}>F.R.I.D.A.Y</span>.
        </h1>
        <p className="lede">
          A local-first assistant with local reasoning, real tools, live research, and local image
          generation. Every status below is measured — never simulated.
        </p>
        <div className="row wrap" style={{ marginTop: 16, gap: 8 }}>
          <Link to="/chat" className="btn btn-primary">
            <Icon name="chat" size={15} /> Start a conversation
          </Link>
          <Link to="/voice" className="btn btn-ghost">
            <Icon name="mic" size={15} /> Voice console
          </Link>
          <span className="tiny muted" style={{ alignSelf: "center" }}>
            {activeModel ? `Model · ${activeModel.name}` : "No active model reported"}
            {overview ? ` · up ${formatUptime(overview.identity.uptime_seconds)}` : ""}
          </span>
        </div>
      </section>

      <div className="grid grid-3">
        <div className="stat-tile">
          <span className="label">Tasks tracked</span>
          <span className="value">{counts.total}</span>
          <span className="foot">{counts.running} running now</span>
        </div>
        <div className="stat-tile">
          <span className="label">Services healthy</span>
          <span className="value">
            {healthyServices}
            <span className="muted" style={{ fontSize: "0.8rem" }}>
              /{totalServices}
            </span>
          </span>
          <span className="foot">{health ? `overall ${health.overall}` : "health pending"}</span>
        </div>
        <div className="stat-tile">
          <span className="label">Agents active</span>
          <span className="value">
            {working}
            <span className="muted" style={{ fontSize: "0.8rem" }}>
              /{agents.length}
            </span>
          </span>
          <span className="foot">{agents.length} registered subsystems</span>
        </div>
      </div>

      <div className="grid grid-2">
        <section className="panel" aria-labelledby="home-voice">
          <div className="panel-head">
            <div>
              <h2 id="home-voice">Assistant</h2>
              <p className="panel-sub">Conversation state reported by the backend</p>
            </div>
          </div>
          <div className="panel-body">
            <VoiceInteractionPanel />
          </div>
        </section>

        <section className="panel" aria-labelledby="home-transcript">
          <div className="panel-head">
            <div>
              <h2 id="home-transcript">Live transcript</h2>
              <p className="panel-sub">Only real processed turns appear here</p>
            </div>
            <Link to="/voice" className="btn btn-sm btn-ghost">
              Open voice console
            </Link>
          </div>
          <div className="panel-body">
            <LiveTranscript limit={6} />
          </div>
        </section>
      </div>

      <section className="panel" aria-labelledby="home-shortcuts">
        <div className="panel-head">
          <div>
            <h2 id="home-shortcuts">Quick actions</h2>
            <p className="panel-sub">Every destination is a working surface backed by real services</p>
          </div>
        </div>
        <div className="panel-body shortcut-grid">
          {SHORTCUTS.map((shortcut) => (
            <Link className="shortcut" to={shortcut.to} key={shortcut.to}>
              <span className="icon">
                <Icon name={shortcut.icon} size={18} />
              </span>
              <strong>{shortcut.title}</strong>
              <span>{shortcut.description}</span>
            </Link>
          ))}
        </div>
      </section>

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="panel" aria-labelledby="home-activity">
          <div className="panel-head">
            <div>
              <h2 id="home-activity">Recent activity</h2>
              <p className="panel-sub">Persisted history across restarts</p>
            </div>
          </div>
          <div className="panel-body">
            <RecentActivityTimeline />
          </div>
        </section>

        <section className="panel" aria-labelledby="home-health">
          <div className="panel-head">
            <div>
              <h2 id="home-health">System health</h2>
              <p className="panel-sub">Probed per service</p>
            </div>
          </div>
          <div className="panel-body">
            <SystemHealthPanel />
            {metrics ? (
              <p className="tiny muted" style={{ marginTop: 10 }}>
                Telemetry source: {metrics.source} · sampled{" "}
                {new Date(metrics.timestamp).toLocaleTimeString()}
              </p>
            ) : null}
          </div>
        </section>
      </div>

      {!overview && !booting ? (
        <EmptyState
          title="Waiting for the backend"
          description="The dashboard could not reach the local FastAPI service. Start it with `python -m friday.web`, then retry."
        />
      ) : null}
    </div>
  );
}
