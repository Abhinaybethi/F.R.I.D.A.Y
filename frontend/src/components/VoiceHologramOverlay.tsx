import { useEffect, useRef, useState } from "react";

import { useDashboard } from "../state/DashboardContext";
import { useLocalVoicePhase, type LocalVoicePhase } from "../state/voiceActivity";
import { DEFAULT_HOLOGRAM_THEME, HolographicSphere } from "./HolographicSphere";

// ---------------------------------------------------------------
// Voice-activated hologram overlay.
//
// F.R.I.D.A.Y. only "wakes up" when voice is actually engaged:
//   • the browser recorder on the Voice page (local phase), or
//   • a live hands-free session (wake word → command → reply).
//
// Passive wake-word listening is deliberately excluded so the overlay is
// invisible during the always-on "Hey Friday" standby state. Typed chat never
// wakes it either, because only voice stages are mapped below.
// ---------------------------------------------------------------

type HologramStage =
  | "LISTENING"
  | "PROCESSING"
  | "EXECUTING"
  | "RESPONDING"
  | "WAITING_FOR_CONFIRMATION"
  | "INTERRUPTED";

const LOCAL_STAGE: Record<LocalVoicePhase, HologramStage | null> = {
  idle: null,
  listening: "LISTENING",
  thinking: "PROCESSING",
  speaking: "RESPONDING",
};

/** Hands-free listener/runtime states. WAKE_LISTENING stays dormant on purpose. */
const HANDSFREE_STAGE: Record<string, HologramStage | null> = {
  WAKE_LISTENING: null,
  COMMAND_LISTENING: "LISTENING",
  PROCESSING: "PROCESSING",
  EXECUTING: "EXECUTING",
  RESPONDING: "RESPONDING",
  WAITING_FOR_CONFIRMATION: "WAITING_FOR_CONFIRMATION",
  STOPPED: null,
  ERROR: null,
};

/** Assistant states, used to refine hands-free PROCESSING into a specific stage. */
const ASSISTANT_STAGE: Record<string, HologramStage | null> = {
  LISTENING: "LISTENING",
  TRANSCRIBING: "PROCESSING",
  PROCESSING: "PROCESSING",
  EXECUTING: "EXECUTING",
  RESPONDING: "RESPONDING",
  SPEAKING: "RESPONDING",
  WAITING_FOR_CONFIRMATION: "WAITING_FOR_CONFIRMATION",
  INTERRUPTED: "INTERRUPTED",
};

const STAGE_INTENSITY: Record<HologramStage, number> = {
  LISTENING: 0.45,
  PROCESSING: 0.7,
  EXECUTING: 0.85,
  RESPONDING: 1,
  WAITING_FOR_CONFIRMATION: 0.5,
  INTERRUPTED: 0.9,
};

const STAGE_LABEL: Record<HologramStage, string> = {
  LISTENING: "Listening",
  PROCESSING: "Thinking",
  EXECUTING: "Executing",
  RESPONDING: "Speaking",
  WAITING_FOR_CONFIRMATION: "Awaiting confirmation",
  INTERRUPTED: "Interrupted",
};

/** Keep the sphere mounted during its fade-out so the wake/sleep transition reads. */
const EXIT_MS = 420;

export function VoiceHologramOverlay() {
  const { voice } = useDashboard();
  const localPhase = useLocalVoicePhase();

  const handsFreeActive = Boolean(voice?.hands_free?.active ?? voice?.hands_free_active);
  const handsFreeState = String(
    voice?.hands_free?.state ?? voice?.hands_free_state ?? "STOPPED",
  ).toUpperCase();
  const assistantState = String(voice?.state ?? "").toUpperCase();

  const localStage = LOCAL_STAGE[localPhase];
  let stage: HologramStage | null = null;
  if (localStage) {
    stage = localStage;
  } else if (handsFreeActive) {
    stage = HANDSFREE_STAGE[handsFreeState] ?? null;
    // While a command runs, the listener reports PROCESSING for its whole
    // duration; prefer the assistant's finer-grained stage when it is useful.
    if (handsFreeState !== "WAKE_LISTENING") {
      const assistantStage = ASSISTANT_STAGE[assistantState] ?? null;
      if (assistantStage === "EXECUTING" || assistantStage === "WAITING_FOR_CONFIRMATION") {
        stage = assistantStage;
      }
    }
  }

  const active = stage !== null;
  const [mounted, setMounted] = useState(active);
  const [leaving, setLeaving] = useState(false);
  const lastStageRef = useRef<HologramStage>(stage ?? "LISTENING");
  if (stage) lastStageRef.current = stage;

  useEffect(() => {
    if (active) {
      setMounted(true);
      setLeaving(false);
      return;
    }
    if (!mounted) return;
    setLeaving(true);
    const timer = window.setTimeout(() => {
      setMounted(false);
      setLeaving(false);
    }, EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [active, mounted]);

  if (!mounted) return null;

  const displayStage = stage ?? lastStageRef.current;
  const label = STAGE_LABEL[displayStage];

  return (
    <div
      className="voice-hologram-overlay"
      data-stage={displayStage.toLowerCase()}
      data-theme={DEFAULT_HOLOGRAM_THEME}
      data-leaving={leaving || !active}
      role="status"
      aria-live="polite"
      aria-label={`F.R.I.D.A.Y. voice ${label.toLowerCase()}`}
    >
      <div className="voice-hologram-backdrop" aria-hidden="true" />
      <div className="voice-hologram-glow" aria-hidden="true" />
      <div className="voice-hologram-scene" aria-hidden="true">
        <HolographicSphere
          phase={displayStage}
          size={440}
          activityIntensity={STAGE_INTENSITY[displayStage]}
          theme={DEFAULT_HOLOGRAM_THEME}
        />
      </div>
      <div className="voice-hologram-floor" aria-hidden="true" />
      <span className="voice-hologram-label">{label}</span>
    </div>
  );
}
