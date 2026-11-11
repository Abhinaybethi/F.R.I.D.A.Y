import { ResearchPanel } from "../components/ResearchPanel";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function ResearchPage() {
  const { health, settings } = useDashboard();
  const researchHealth = health?.components?.research;
  const ragHealth = health?.components?.rag;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Research</span>
          <h1>Live web research</h1>
          <p>
            Query the configured search provider through the existing research pipeline. Returned sources
            are real; local RAG retrieval is reported separately on the Knowledge page.
          </p>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <StatusPill status={researchHealth?.status ?? "unknown"} label={`Web ${researchHealth?.status ?? "unknown"}`} />
          <StatusPill status={ragHealth?.status ?? "unknown"} label={`RAG ${ragHealth?.status ?? "unknown"}`} />
        </div>
      </div>

      <section className="panel" aria-label="Research">
        <div className="panel-body">
          <ResearchPanel />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Sources and provenance</h2>
            <p className="panel-sub">The dashboard distinguishes provider results from local knowledge</p>
          </div>
        </div>
        <div className="panel-body">
          <div className="grid grid-2">
            <div>
              <h3>Web results</h3>
              <p className="tiny dim" style={{ marginTop: 4 }}>
                Produced by the configured provider ({settings?.research?.provider ?? "unknown"}), limited to{" "}
                {settings?.research?.max_results ?? "?"} results. Links open the original source.
              </p>
            </div>
            <div>
              <h3>Local knowledge</h3>
              <p className="tiny dim" style={{ marginTop: 4 }}>
                Retrieved from the local RAG collection (
                <span className="code-inline">friday_knowledge</span>) when you chat. It is not mixed into
                this web-research result list.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
