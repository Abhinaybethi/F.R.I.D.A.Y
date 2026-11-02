import { useState } from "react";

import { relativeTime } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

const PIPELINE_LABELS: Record<string, string> = {
  IDLE: "Idle",
  LISTENING: "Listening",
  TRANSCRIBING: "Transcribing",
  PROCESSING: "Processing",
  EXECUTING: "Executing",
  RESPONDING: "Speaking",
  WAITING_FOR_CONFIRMATION: "Waiting for confirmation",
  PAUSED: "Paused",
  STOPPING: "Stopping",
  UNKNOWN: "Unknown",
};

/**
 * In this web layer microphone capture is never active, so the assistant's
 * LISTENING conversation state means "awaiting input", not "recording".
 */
function stageLabel(stage: string, captureSupported: boolean): string {
  if (stage === "LISTENING" && !captureSupported) return "Awaiting input";
  return PIPELINE_LABELS[stage] ?? stage;
}

export function VoiceInteractionPanel({ allowTyped = false }: { allowTyped?: boolean }) {
  const { voice, sendChat, chatBusy, transcripts } = useDashboard();
  const [draft, setDraft] = useState("");

  const state = voice?.state ?? "UNKNOWN";
  const micAvailable = voice?.microphone.available ?? false;
  const captureActive = voice?.capture_active === true;

  const submit = async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    await sendChat(text);
  };

  return (
    <div className="stack">
      <div className="row between">
        <StatusPill
          status={micAvailable ? (captureActive ? "running" : "idle") : "unavailable"}
          label={micAvailable ? (captureActive ? "Capturing" : "Microphone detected") : "No microphone"}
          title={voice?.microphone.detail}
        />
        <span className="tiny muted">
          {transcripts.length > 0
            ? `Last transcript ${relativeTime(transcripts[transcripts.length - 1].timestamp)}`
            : "No transcript yet"}
        </span>
      </div>

      <div className="voice-orb" data-active={captureActive}>
        <div className="center">
          <Icon name="mic" size={30} />
          <div className="state" style={{ marginTop: 8 }}>
            {stageLabel(state, voice?.capture_supported === true)}
          </div>
        </div>
      </div>

      <div className="chip-row" style={{ justifyContent: "center" }}>
        {(voice?.pipeline ?? ["IDLE", "LISTENING", "PROCESSING", "RESPONDING"]).map((stage) => {
          const active = stage === state;
          return (
            <span
              className="chip"
              key={stage}
              style={{
                borderColor: active ? "var(--line-strong)" : undefined,
                color: active ? "var(--text)" : undefined,
                background: active ? "rgba(56,189,248,0.12)" : undefined,
              }}
            >
              {stageLabel(stage, voice?.capture_supported === true)}
            </span>
          );
        })}
      </div>

      <div className="row" style={{ justifyContent: "center", gap: 8 }}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!voice?.capture_supported}
          title={
            voice?.capture_supported
              ? "Start microphone capture"
              : "Microphone capture is owned by the desktop voice runtime; this web dashboard cannot open a competing audio pipeline."
          }
        >
          <Icon name="mic" size={15} />
          Start listening
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={!voice?.capture_supported || !captureActive}
          title="Stop microphone capture"
        >
          Stop
        </button>
      </div>

      <p className="tiny muted center">
        {voice?.reason ??
          "Microphone state will appear here when the desktop voice runtime reports it."}
      </p>

      {!micAvailable ? (
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">Microphone unavailable</span>
            {voice?.microphone.detail ?? "No audio input device was reported by the backend."}
          </div>
        </div>
      ) : null}

      {allowTyped ? (
        <div className="stack-sm" style={{ marginTop: 4 }}>
          <label className="tiny muted" htmlFor="voice-typed-input">
            Voice unavailable? Send a typed turn through the same assistant pipeline.
          </label>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <input
              id="voice-typed-input"
              type="text"
              placeholder="Type a command or question…"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submit();
                }
              }}
            />
            <button
              type="button"
              className="btn"
              onClick={() => void submit()}
              disabled={chatBusy || draft.trim().length === 0}
            >
              <Icon name="send" size={14} />
              {chatBusy ? "Working…" : "Send"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
