/**
 * Tiny external store for browser-local voice activity.
 *
 * The hologram overlay lives in AppShell (outside the Voice page), while the
 * local recorder phase lives inside VoiceInteractionPanel. This store lets the
 * panel publish "listening / thinking / speaking" without lifting its whole
 * state machine into the global dashboard context.
 */

import { useSyncExternalStore } from "react";

export type LocalVoicePhase = "idle" | "listening" | "thinking" | "speaking";

let phase: LocalVoicePhase = "idle";
const listeners = new Set<() => void>();

export function setLocalVoicePhase(next: LocalVoicePhase): void {
  if (phase === next) return;
  phase = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): LocalVoicePhase {
  return phase;
}

export function useLocalVoicePhase(): LocalVoicePhase {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
