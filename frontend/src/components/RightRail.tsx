import { useEffect, useState } from "react";

import { formatGb, formatMb, formatUptime, relativeTime, statusLabel } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { AgentStatusList } from "./AgentStatusList";
import { EmptyState } from "./EmptyState";
import { StatusPill } from "./StatusPill";
import { ActiveModelSummary } from "./ModelStatusCard";
import { ResourceGauge, Sparkline } from "./ResourceGauge";
import { SystemHealthPanel } from "./SystemHealthPanel";

export function RightRail() {
  const { metrics, health, activeModel, tools, agents, activity, lastMetricAt, backendReachable } =
    useDashboard();
  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [ramHistory, setRamHistory] = useState<number[]>([]);

  useEffect(() => {
    if (!metrics || metrics.cpu.percent === null) return;
    setCpuHistory((previous) => [...previous, metrics.cpu.percent as number].slice(-40));
    setRamHistory((previous) => [...previous, metrics.ram.percent].slice(-40));
  }, [metrics]);

  const enabledTools = tools.filter((tool) => tool.allowed).length;
  const gpu = metrics?.gpu;
  const recent = activity.slice(0, 6);

  return (
    <>
      <section className="panel" aria-labelledby="rail-resources">
        <div className="panel-head">
          <div>
            <h2 id="rail-resources">System resources</h2>
            <p className="panel-sub">
              psutil + nvidia-smi · {lastMetricAt ? relativeTime(new Date(lastMetricAt).toISOString()) : "waiting"}
            </p>
          </div>
          {metrics ? (
            <StatusPill
              status={backendReachable ? "healthy" : "offline"}
              label={backendReachable ? "Live" : "Stale"}
              title={
                backendReachable
                  ? "Metrics are being sampled from this machine"
                  : "The backend is unreachable; these are the last known samples"
              }
            />
          ) : null}
        </div>
        <div className="panel-body stack">
          <ResourceGauge
            label="CPU"
            percent={metrics?.cpu.percent ?? null}
            detail={
              metrics ? `${metrics.cpu.logical_cores ?? "?"} logical · ${metrics.cpu.physical_cores ?? "?"} physical` : undefined
            }
          />
          <Sparkline values={cpuHistory} label="CPU utilization history" />
          <ResourceGauge
            label="Memory"
            percent={metrics?.ram.percent ?? null}
            footLeft={metrics ? `${formatGb(metrics.ram.used_gb)} used` : undefined}
            footRight={metrics ? `${formatGb(metrics.ram.available_gb)} free` : undefined}
          />
          <Sparkline values={ramHistory} label="Memory utilization history" />
          <ResourceGauge
            label="GPU"
            percent={gpu?.available ? gpu.utilization_percent : null}
            detail={gpu?.available ? gpu.name ?? undefined : "Unavailable"}
            footLeft={gpu?.available ? `${formatMb(gpu.memory_used_mb)} / ${formatMb(gpu.memory_total_mb)} VRAM` : undefined}
            footRight={gpu?.available && gpu.temperature_c !== null ? `${gpu.temperature_c}°C` : undefined}
          />
          {gpu && !gpu.available ? (
            <p className="tiny muted">{gpu.reason || "No GPU telemetry provider is available."}</p>
          ) : null}
          {metrics?.disk ? (
            <ResourceGauge
              label="Disk"
              percent={metrics.disk.percent}
              footLeft={`${formatGb(metrics.disk.used_gb)} used`}
              footRight={`${formatGb(metrics.disk.free_gb)} free`}
              tone="idle"
            />
          ) : null}
          {metrics ? (
            <div className="row between tiny muted">
              <span>System uptime</span>
              <span>{formatUptime(metrics.uptime_seconds)}</span>
            </div>
          ) : null}
        </div>
      </section>

      <section className="panel" aria-labelledby="rail-health">
        <div className="panel-head">
          <div>
            <h2 id="rail-health">Service health</h2>
            <p className="panel-sub">Real probes, refreshed continuously</p>
          </div>
          {health ? <StatusPill status={health.overall} label={statusLabel(health.overall)} /> : null}
        </div>
        <div className="panel-body">
          <SystemHealthPanel />
        </div>
      </section>

      <section className="panel" aria-labelledby="rail-model">
        <div className="panel-head">
          <div>
            <h2 id="rail-model">Active model</h2>
            <p className="panel-sub">The model actually configured for inference</p>
          </div>
        </div>
        <div className="panel-body">
          <ActiveModelSummary model={activeModel} />
          <div className="row between tiny muted" style={{ marginTop: 10 }}>
            <span>Tools enabled</span>
            <span>
              {enabledTools}/{tools.length}
            </span>
          </div>
        </div>
      </section>

      <section className="panel" aria-labelledby="rail-agents">
        <div className="panel-head">
          <div>
            <h2 id="rail-agents">Agents</h2>
            <p className="panel-sub">Derived from real subsystems</p>
          </div>
        </div>
        <div className="panel-body">
          <AgentStatusList agents={agents} limit={4} />
        </div>
      </section>

      <section className="panel" aria-labelledby="rail-tasks">
        <div className="panel-head">
          <div>
            <h2 id="rail-tasks">Recent tasks</h2>
            <p className="panel-sub">Persisted operations only</p>
          </div>
        </div>
        <div className="panel-body">
          {recent.length === 0 ? (
            <EmptyState title="Nothing yet" description="Tasks appear after real operations." icon="activity" />
          ) : (
            <div className="list">
              {recent.map((item) => (
                <div className="list-row" key={item.id}>
                  <div className="list-main">
                    <div className="row between" style={{ gap: 8 }}>
                      <span className="list-title" title={item.title}>
                        {item.title}
                      </span>
                      <StatusPill status={item.status} subtle />
                    </div>
                    <div className="list-meta">
                      <span className="chip">{item.kind}</span>
                      <span>{relativeTime(item.created_at)}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
