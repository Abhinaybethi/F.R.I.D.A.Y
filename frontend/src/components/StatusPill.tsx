import type { ReactNode } from "react";

import { statusLabel, statusTone, type Tone } from "../lib/format";
import { Icon } from "./Icon";

interface StatusPillProps {
  status: string | null | undefined;
  label?: string;
  title?: string;
  subtle?: boolean;
  tone?: Tone;
}

/** Single source of truth for how a backend status is rendered. */
export function StatusPill({ status, label, title, subtle, tone: toneOverride }: StatusPillProps) {
  const tone = toneOverride ?? statusTone(status);
  return (
    <span
      className={`pill${subtle ? " subtle" : ""}`}
      data-tone={subtle ? undefined : tone}
      title={title ?? label ?? status ?? "unknown"}
    >
      <span className="dot" aria-hidden="true" />
      {label ?? statusLabel(status)}
    </span>
  );
}

export function Dot({ tone = "ok" }: { tone?: string }) {
  return <span className="live-dot" data-tone={tone} aria-hidden="true" />;
}

export function IconLabel({ icon, children }: { icon: Parameters<typeof Icon>[0]["name"]; children: ReactNode }) {
  return (
    <span className="row" style={{ gap: 6 }}>
      <Icon name={icon} size={14} />
      {children}
    </span>
  );
}
