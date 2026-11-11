import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { RecentActivityTimeline } from "../components/RecentActivityTimeline";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

const CODE_TOOLS = ["FIND_FILE", "OPEN_FILE", "OPEN_FOLDER", "READ_WEBSITE", "TAKE_SCREENSHOT"];

export function CodePage() {
  const { tools } = useDashboard();
  const relevant = tools.filter((tool) => CODE_TOOLS.includes(tool.name));

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Code</span>
          <h1>Developer operations</h1>
          <p>
            F.R.I.D.A.Y exposes file and workspace inspection through explicit, permission-gated tools. It
            deliberately does not expose a generic shell or an unrestricted code-execution sandbox.
          </p>
        </div>
        <Link to="/automation" className="btn btn-sm">
          <Icon name="terminal" size={13} /> Open tool console
        </Link>
      </div>

      <div className="alert" data-tone="info">
        <div>
          <span className="alert-title">No arbitrary shell execution</span>
          There is no “run command” endpoint in this build. Code-related actions happen only through named
          tools, with the same dry-run, permission, and confirmation gates as the desktop assistant. That is
          a deliberate security property, not a missing feature.
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>File and workspace tools</h2>
            <p className="panel-sub">State read from the live registry</p>
          </div>
        </div>
        <div className="panel-body">
          {relevant.length === 0 ? (
            <EmptyState
              title="No file tools reported"
              description="The backend registry did not include file inspection actions."
              icon="folder"
            />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Tool</th>
                    <th scope="col">Permission key</th>
                    <th scope="col">Mode</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {relevant.map((tool) => (
                    <tr key={tool.id}>
                      <td>{tool.name}</td>
                      <td className="mono tiny">{tool.permission_key ?? "system"}</td>
                      <td className="tiny">{tool.dry_run ? "Dry run" : "Real"}</td>
                      <td>
                        <StatusPill
                          status={tool.allowed ? "healthy" : "unavailable"}
                          label={tool.allowed ? "Enabled" : "Disabled"}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="tiny muted" style={{ marginTop: 10 }}>
            Run these from the Automation console, where each tool exposes its own target and confirmation
            requirements.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Tool execution log</h2>
            <p className="panel-sub">Actual executions only</p>
          </div>
        </div>
        <div className="panel-body">
          <RecentActivityTimeline initialKind="tool" />
        </div>
      </section>
    </div>
  );
}
