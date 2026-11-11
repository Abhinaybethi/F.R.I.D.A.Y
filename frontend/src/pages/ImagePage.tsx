import { ImageGenerationPanel } from "../components/ImageGenerationPanel";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../state/DashboardContext";

export function ImagePage() {
  const { health, settings } = useDashboard();
  const imageHealth = health?.components?.image;
  const imageSettings = settings?.image;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Create image</span>
          <h1>Qwen-Image generation</h1>
          <p>
            The existing stable-diffusion.cpp integration runs locally. The dashboard reports the real
            lifecycle and never invents progress percentages.
          </p>
        </div>
        <StatusPill status={imageHealth?.status ?? "unknown"} label={`Image backend ${imageHealth?.status ?? "unknown"}`} />
      </div>

      <section className="panel" aria-label="Image generation">
        <div className="panel-body">
          <ImageGenerationPanel />
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Integration details</h2>
            <p className="panel-sub">Read from the live configuration</p>
          </div>
        </div>
        <div className="panel-body">
          <dl className="kv">
            <dt>Backend</dt>
            <dd>stable-diffusion.cpp (sd-cli)</dd>
            <dt>Provider</dt>
            <dd>{imageSettings?.provider ?? "qwen-image"}</dd>
            <dt>Device</dt>
            <dd>{imageHealth?.device ?? imageSettings?.device ?? "auto"}</dd>
            <dt>VRAM</dt>
            <dd>
              {imageHealth?.vram_total_mb ? `${imageHealth.vram_total_mb} MB total` : "not reported"}
            </dd>
            <dt>Timeout</dt>
            <dd>{imageSettings?.timeout ? `${imageSettings.timeout}s` : "—"}</dd>
            <dt>Output</dt>
            <dd className="mono">output/generated_images/&lt;date&gt;/image_###.png</dd>
          </dl>
          <p className="tiny muted" style={{ marginTop: 10 }}>
            Video generation is intentionally not part of this build.
          </p>
        </div>
      </section>
    </div>
  );
}
