import { AutomationPanel } from "../components/AutomationPanel";
import { RecentActivityTimeline } from "../components/RecentActivityTimeline";
import { useDashboard } from "../state/DashboardContext";

export function AutomationPage() {
  const { tools, counts } = useDashboard();
  const enabled = tools.filter((tool) => tool.allowed).length;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Automation</span>
          <h1>Tool execution</h1>
          <p>
            Invoke registered tools through the existing registry. Permissions, dry-run behaviour, and
            confirmation gates are enforced by the backend — the UI cannot bypass them.
          </p>
        </div>
        <span className="pill" data-tone="info">
          <span className="dot" /> {enabled}/{tools.length} enabled
        </span>
      </div>

      <section className="panel" aria-label="Tools">
        <div className="panel-body">
          <AutomationPanel />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Execution history</h2>
            <p className="panel-sub">
              {counts.total} persisted tasks · {counts.failed} failed
            </p>
          </div>
        </div>
        <div className="panel-body">
          <RecentActivityTimeline />
        </div>
      </section>
    </div>
  );
}
