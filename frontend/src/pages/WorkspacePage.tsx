import { RecentActivityTimeline } from "../components/RecentActivityTimeline";
import { WorkspaceView } from "../components/WorkspaceView";

export function WorkspacePage() {
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Workspace</span>
          <h1>Workspace and files</h1>
          <p>
            Real project root, configuration-referenced directories, and persisted task history. No
            synthetic files or entries are listed.
          </p>
        </div>
      </div>
      <WorkspaceView mode="workspace" />
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Workspace activity</h2>
            <p className="panel-sub">Operations performed by the assistant on this machine</p>
          </div>
        </div>
        <div className="panel-body">
          <RecentActivityTimeline />
        </div>
      </section>
    </div>
  );
}
