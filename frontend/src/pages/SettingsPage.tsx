import { apiBaseUrl } from "../lib/api";
import { formatDateTime, formatUptime, relativeTime, statusLabel } from "../lib/format";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { Icon } from "../components/Icon";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

const INTERVALS = [1000, 1500, 2000, 3000, 5000, 10000];

export function SettingsPage() {
  const {
    settings,
    overview,
    connection,
    backendReachable,
    refresh,
    refreshing,
    refreshIntervalMs,
    setRefreshIntervalMs,
    lastEventAt,
    lastMetricAt,
  } = useDashboardSafe();

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Settings</span>
          <h1>Configuration and diagnostics</h1>
          <p>
            Read-only view of the live backend configuration, plus client-side display preferences.
            Secrets are never returned by the API and environment files are never written from the browser.
          </p>
        </div>
        <button type="button" className="btn btn-sm" onClick={() => void refresh()} disabled={refreshing}>
          <Icon name="refresh" size={13} /> {refreshing ? "Reloading…" : "Reload configuration"}
        </button>
      </div>

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="panel" aria-labelledby="settings-connection">
          <div className="panel-head">
            <div>
              <h2 id="settings-connection">Connection</h2>
              <p className="panel-sub">Where this dashboard talks to</p>
            </div>
            <ConnectionStatus compact />
          </div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Backend URL</dt>
              <dd className="mono">{settings?.backend_url ?? apiBaseUrl()}</dd>
              <dt>Browser origin</dt>
              <dd className="mono">{apiBaseUrl()}</dd>
              <dt>WebSocket</dt>
              <dd>{statusLabel(connection)}</dd>
              <dt>Reachable</dt>
              <dd>{backendReachable ? "yes" : "no"}</dd>
              <dt>Last event</dt>
              <dd>{lastEventAt ? `${relativeTime(lastEventAt)} · ${formatDateTime(lastEventAt)}` : "none yet"}</dd>
              <dt>Metrics sample</dt>
              <dd>{lastMetricAt ? relativeTime(new Date(lastMetricAt).toISOString()) : "none yet"}</dd>
            </dl>
          </div>
        </section>

        <section className="panel" aria-labelledby="settings-monitoring">
          <div className="panel-head">
            <div>
              <h2 id="settings-monitoring">Monitoring</h2>
              <p className="panel-sub">Client-side refresh cadence</p>
            </div>
          </div>
          <div className="panel-body stack-sm">
            <div className="field">
              <label htmlFor="interval">Metrics refresh interval</label>
              <select
                id="interval"
                value={refreshIntervalMs}
                onChange={(event) => setRefreshIntervalMs(Number(event.target.value))}
              >
                {INTERVALS.map((value) => (
                  <option key={value} value={value}>
                    {value / 1000}s
                  </option>
                ))}
              </select>
            </div>
            <p className="tiny muted">
              CPU/RAM polling is non-blocking on the server (psutil snapshots) and runs in a single interval.
              Health, agents, and activity refresh every 15 seconds; WebSocket events refresh them sooner.
            </p>
          </div>
        </section>

        <section className="panel" aria-labelledby="settings-appearance">
          <div className="panel-head">
            <div>
              <h2 id="settings-appearance">Appearance</h2>
              <p className="panel-sub">Designed for low GPU/CPU cost</p>
            </div>
          </div>
          <div className="panel-body">
            <div className="row" style={{ gap: 8 }}>
              <label className="row" style={{ gap: 6 }}>
                <input type="radio" name="theme" checked readOnly />
                Dark (only theme in this build)
              </label>
            </div>
            <p className="tiny muted" style={{ marginTop: 8 }}>
              Animations are reduced automatically when your OS requests reduced motion. Glow effects are
              static CSS and do not run canvas or WebGL loops.
            </p>
            <p className="tiny muted" style={{ marginTop: 6 }}>
              Desktop notifications are owned by the desktop runtime. This web dashboard does not request
              browser notification permissions.
            </p>
          </div>
        </section>

        <section className="panel" aria-labelledby="settings-security">
          <div className="panel-head">
            <div>
              <h2 id="settings-security">Security posture</h2>
              <p className="panel-sub">Actual backend settings</p>
            </div>
            <StatusPill
              status={settings?.security.allow_real_execution ? "running" : "idle"}
              label={settings?.security.allow_real_execution ? "Real execution" : "Dry run"}
            />
          </div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Dry run</dt>
              <dd>{settings?.security.dry_run ? "enabled" : "disabled"}</dd>
              <dt>Allow real execution</dt>
              <dd>{settings?.security.allow_real_execution ? "yes" : "no"}</dd>
              <dt>Permission gates</dt>
              <dd>Enforced in friday.tools.registry</dd>
              <dt>Arbitrary shell</dt>
              <dd>Not exposed</dd>
            </dl>
            <p className="tiny muted" style={{ marginTop: 8 }}>
              This page cannot change security settings. Edit <span className="code-inline">config.yaml</span>{" "}
              deliberately on the host.
            </p>
          </div>
        </section>

        <section className="panel" aria-labelledby="settings-voice">
          <div className="panel-head">
            <div>
              <h2 id="settings-voice">Voice</h2>
              <p className="panel-sub">Read from voice configuration</p>
            </div>
          </div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Offline only</dt>
              <dd>{settings?.voice.offline_only ? "true" : "false"}</dd>
              <dt>Wake word required</dt>
              <dd>{settings?.voice.wake_word_required ? "true" : "false"}</dd>
              <dt>STT model</dt>
              <dd>{settings?.voice.stt_model ?? "—"}</dd>
              <dt>TTS engine</dt>
              <dd>{settings?.voice.tts_engine ?? "—"}</dd>
            </dl>
            <p className="tiny muted" style={{ marginTop: 8 }}>
              Audio device selection is handled by the desktop runtime; the web dashboard does not enumerate
              or claim control of capture devices beyond the backend&apos;s microphone probe.
            </p>
          </div>
        </section>

        <section className="panel" aria-labelledby="settings-research">
          <div className="panel-head">
            <div>
              <h2 id="settings-research">Research and generation</h2>
              <p className="panel-sub">Backend defaults</p>
            </div>
          </div>
          <div className="panel-body">
            <dl className="kv">
              <dt>Web research</dt>
              <dd>
                {settings?.research.enabled ? "enabled" : "disabled"} ·{" "}
                {settings?.research.provider ?? "—"} · max {settings?.research.max_results ?? "—"}
              </dd>
              <dt>Image provider</dt>
              <dd>{settings?.image.provider ?? "—"}</dd>
              <dt>Image defaults</dt>
              <dd>
                {settings?.image.width ?? "?"}×{settings?.image.height ?? "?"} ·{" "}
                {settings?.image.steps ?? "?"} steps
              </dd>
              <dt>Image device</dt>
              <dd>{settings?.image.device ?? "auto"}</dd>
              <dt>Image timeout</dt>
              <dd>{settings?.image.timeout ? `${settings.image.timeout}s` : "—"}</dd>
            </dl>
          </div>
        </section>
      </div>

      <section className="panel" aria-labelledby="settings-debug">
        <div className="panel-head">
          <div>
            <h2 id="settings-debug">Debug information</h2>
            <p className="panel-sub">Safe to share; contains no secrets or paths beyond the configured model</p>
          </div>
          {overview ? <StatusPill status={overview.state} label={overview.state} /> : null}
        </div>
        <div className="panel-body">
          <dl className="kv">
            <dt>Version</dt>
            <dd>{overview?.identity.version ?? "—"}</dd>
            <dt>Platform</dt>
            <dd>{overview?.identity.platform ?? "—"}</dd>
            <dt>Backend uptime</dt>
            <dd>{overview ? formatUptime(overview.identity.uptime_seconds) : "—"}</dd>
            <dt>Reasoning provider</dt>
            <dd>{settings?.reasoning.provider ?? "—"}</dd>
            <dt>Reasoning endpoint</dt>
            <dd className="mono">{settings?.reasoning.endpoint ?? "—"}</dd>
            <dt>Configured model</dt>
            <dd className="mono">{settings?.reasoning.model ?? "—"}</dd>
            <dt>Warnings</dt>
            <dd>
              {settings?.warnings.length
                ? settings.warnings.join(" · ")
                : "none reported"}
            </dd>
          </dl>
        </div>
      </section>
    </div>
  );
}

/** Small wrapper so the page reads clearly while keeping one hook call site. */
function useDashboardSafe() {
  const dashboard = useDashboard();
  return { ...dashboard, refreshing: dashboard.booting };
}
