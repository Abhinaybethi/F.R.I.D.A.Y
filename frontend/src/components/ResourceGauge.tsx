import { formatPercent } from "../lib/format";
import type { Tone } from "../lib/format";

interface ResourceGaugeProps {
  label: string;
  percent: number | null | undefined;
  detail?: string;
  footLeft?: string;
  footRight?: string;
  tone?: Tone;
  accent?: boolean;
}

function toneFor(percent: number | null | undefined, tone?: Tone): Tone {
  if (tone) return tone;
  if (percent === null || percent === undefined) return "idle";
  if (percent >= 90) return "error";
  if (percent >= 75) return "warn";
  return "ok";
}

export function ResourceGauge({
  label,
  percent,
  detail,
  footLeft,
  footRight,
  tone,
  accent,
}: ResourceGaugeProps) {
  const available = percent !== null && percent !== undefined && Number.isFinite(percent);
  const clamped = available ? Math.min(100, Math.max(0, percent as number)) : 0;
  const resolvedTone = accent ? "accent" : toneFor(percent, tone);

  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="gauge-label">{label}</span>
        <span className="gauge-value">{formatPercent(percent)}</span>
      </div>
      <div
        className="gauge-track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={available ? Math.round(clamped) : undefined}
        aria-valuetext={available ? `${Math.round(clamped)} percent` : "unavailable"}
      >
        <div
          className="gauge-fill"
          data-tone={resolvedTone}
          style={{ width: `${clamped}%`, opacity: available ? 1 : 0.18 }}
        />
      </div>
      {detail ? <span className="tiny muted">{detail}</span> : null}
      {footLeft || footRight ? (
        <div className="gauge-foot">
          <span>{footLeft ?? ""}</span>
          <span>{footRight ?? ""}</span>
        </div>
      ) : null}
    </div>
  );
}

interface SparklineProps {
  values: number[];
  label: string;
  max?: number;
}

export function Sparkline({ values, label, max = 100 }: SparklineProps) {
  if (values.length < 2) {
    return <div className="sparkline" aria-hidden="true" />;
  }
  const width = 220;
  const height = 42;
  const step = width / (values.length - 1);
  const points = values.map((value, index) => {
    const clamped = Math.min(max, Math.max(0, value));
    const y = height - (clamped / max) * (height - 4) - 2;
    return `${(index * step).toFixed(1)},${y.toFixed(1)}`;
  });

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${label}: ${values.length} recent samples`}
    >
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(56,189,248,0.35)" />
          <stop offset="100%" stopColor="rgba(56,189,248,0)" />
        </linearGradient>
      </defs>
      <polygon
        points={`0,${height} ${points.join(" ")} ${width},${height}`}
        fill="url(#spark-fill)"
      />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke="#38bdf8"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
