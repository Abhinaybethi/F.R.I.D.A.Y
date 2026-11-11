import { RecentActivityTimeline } from "../components/RecentActivityTimeline";
import { WorkspaceView } from "../components/WorkspaceView";

export function ProjectsPage() {
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Projects</span>
          <h1>Project oversight</h1>
          <p>
            F.R.I.D.A.Y does not have a project database in this build. This page reports the real
            repository, local directories, and task history that the assistant can actually see.
          </p>
        </div>
      </div>
      <WorkspaceView mode="projects" />
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Recent project activity</h2>
            <p className="panel-sub">Persisted operations</p>
          </div>
        </div>
        <div className="panel-body">
          <RecentActivityTimeline />
        </div>
      </section>
    </div>
  );
}
