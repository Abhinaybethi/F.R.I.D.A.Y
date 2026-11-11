import { formatClock } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";

export function LiveTranscript({ limit = 40 }: { limit?: number }) {
  const { transcripts } = useDashboard();
  const visible = transcripts.slice(-limit);

  if (visible.length === 0) {
    return (
      <EmptyState
        title="No transcript yet"
        description="Transcript entries appear after a real turn. Record from the browser microphone or type a message to start a conversation."
        icon="chat"
      />
    );
  }

  return (
    <div className="transcript" aria-live="polite">
      {visible.map((entry) => (
        <div className="transcript-entry" key={entry.id} data-role={entry.role}>
          <div className="row between tiny muted" style={{ marginBottom: 2 }}>
            <span>{entry.role === "user" ? "You" : "F.R.I.D.A.Y"}</span>
            <span>{formatClock(entry.timestamp)}</span>
          </div>
          <div style={{ whiteSpace: "pre-wrap" }}>{entry.text}</div>
        </div>
      ))}
    </div>
  );
}
