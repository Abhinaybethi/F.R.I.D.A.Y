import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function VisionPage() {
  const { tools, activity, executeTool, health } = useDashboard();
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const screenshotTool = tools.find((tool) => tool.name === "TAKE_SCREENSHOT");
  const visionActivity = useMemo(
    () => activity.filter((item) => /screenshot|vision|image/i.test(`${item.title} ${item.source}`)).slice(0, 6),
    [activity],
  );

  const capture = async () => {
    if (!screenshotTool || busy) return;
    setBusy(true);
    const outcome = await executeTool(screenshotTool.id, { target });
    setResult(outcome);
    setBusy(false);
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Vision</span>
          <h1>Screen and visual tools</h1>
          <p>
            This build has no vision-language model registered for image understanding, so the dashboard
            does not claim to describe or analyse images. Screenshot capture through the real desktop tool
            is available when enabled.
          </p>
        </div>
        <StatusPill status={screenshotTool?.allowed ? "healthy" : "unavailable"} label="Screenshot tool" />
      </div>

      <div className="alert" data-tone="info">
        <div>
          <span className="alert-title">No image-understanding model</span>
          A vision reasoning backend is not configured in this repository. Generation via Qwen-Image is
          available on the{" "}
          <Link to="/image" style={{ color: "inherit", textDecoration: "underline" }}>
            Create Image
          </Link>{" "}
          page; screenshot capture is a separate desktop action. The dashboard will not fabricate
          descriptions of your screen.
        </div>
      </div>

      <div className="grid grid-2" style={{ alignItems: "start" }}>
        <section className="panel" aria-labelledby="vision-capture">
          <div className="panel-head">
            <div>
              <h2 id="vision-capture">Screenshot capture</h2>
              <p className="panel-sub">Calls TAKE_SCREENSHOT through the tool registry</p>
            </div>
          </div>
          <div className="panel-body stack-sm">
            {screenshotTool ? (
              <>
                <div className="row between">
                  <span className="tiny muted mono">{screenshotTool.permission_key ?? "system"}</span>
                  <StatusPill
                    status={screenshotTool.allowed ? "healthy" : "unavailable"}
                    label={screenshotTool.allowed ? "Enabled" : "Disabled"}
                  />
                </div>
                <div className="field">
                  <label htmlFor="vision-target">Window or target (optional)</label>
                  <input
                    id="vision-target"
                    type="text"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    placeholder="Leave blank for the full desktop"
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!screenshotTool.allowed || busy}
                  onClick={() => void capture()}
                >
                  {busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="eye" size={14} />}
                  {busy ? "Capturing…" : "Capture screenshot"}
                </button>
                {result ? (
                  <div className="alert" data-tone={result.ok ? "info" : "error"} role="status">
                    {result.message || "Tool returned no message."}
                  </div>
                ) : null}
              </>
            ) : (
              <EmptyState
                title="Screenshot tool not reported"
                description="The backend did not include TAKE_SCREENSHOT in the tool registry."
                icon="eye"
              />
            )}
            <p className="tiny muted">
              Capture is permission-gated and honours the configured dry-run setting. Screenshots stay on
              this machine.
            </p>
          </div>
        </section>

        <section className="panel" aria-labelledby="vision-capabilities">
          <div className="panel-head">
            <div>
              <h2 id="vision-capabilities">Available capabilities</h2>
              <p className="panel-sub">Read directly from the tool registry</p>
            </div>
          </div>
          <div className="panel-body">
            <div className="list">
              {tools
                .filter((tool) => ["TAKE_SCREENSHOT", "READ_WEBSITE", "OPEN_FILE", "FIND_FILE"].includes(tool.name))
                .map((tool) => (
                  <div className="list-row" key={tool.id}>
                    <div className="list-main">
                      <div className="row between">
                        <span className="list-title">{tool.name}</span>
                        <StatusPill status={tool.allowed ? "healthy" : "unavailable"} label={tool.allowed ? "Enabled" : "Disabled"} />
                      </div>
                      <div className="list-meta">
                        <span className="mono">{tool.permission_key}</span>
                        <span>· {tool.dry_run ? "dry run" : "real execution"}</span>
                      </div>
                    </div>
                  </div>
                ))}
            </div>
            <p className="tiny muted" style={{ marginTop: 8 }}>
              Health check for vision-related services: {health?.components ? "reported in the status rail" : "unavailable"}.
            </p>
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Recent related activity</h2>
            <p className="panel-sub">Only real recorded operations</p>
          </div>
        </div>
        <div className="panel-body">
          {visionActivity.length === 0 ? (
            <EmptyState title="No visual activity" description="Screenshots and visual tool calls will appear here after they run." icon="eye" />
          ) : (
            <div className="list">
              {visionActivity.map((item) => (
                <div className="list-row" key={item.id}>
                  <div className="list-main">
                    <div className="row between">
                      <span className="list-title">{item.title}</span>
                      <StatusPill status={item.status} />
                    </div>
                    <div className="list-meta">
                      <span>{item.kind}</span>
                      <span>· {item.message}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
