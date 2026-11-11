import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../lib/api";
import { decodeTo16kMono, encodeWav, preferredRecorderMime, recordingSupported } from "../lib/audio";
import { relativeTime } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { setLocalVoicePhase, type LocalVoicePhase } from "../state/voiceActivity";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

type Phase = "idle" | "recording" | "transcribing" | "thinking" | "speaking";

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

const PHASE_STAGE: Record<Phase, string | null> = {
  idle: null,
  recording: "LISTENING",
  transcribing: "TRANSCRIBING",
  thinking: "PROCESSING",
  speaking: "RESPONDING",
};

/** Browser-recorder phases published to the global voice hologram overlay. */
const LOCAL_VOICE_PHASE: Record<Phase, LocalVoicePhase> = {
  idle: "idle",
  recording: "listening",
  transcribing: "thinking",
  thinking: "thinking",
  speaking: "speaking",
};

const HANDSFREE_STAGE: Record<string, string> = {
  WAKE_LISTENING: "IDLE",
  COMMAND_LISTENING: "LISTENING",
  PROCESSING: "PROCESSING",
  RESPONDING: "RESPONDING",
};

function titleCase(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function handsFreeLabel(state: string, wakeWord: string): string {
  switch (state) {
    case "WAKE_LISTENING":
      return `Say \u201cHey ${titleCase(wakeWord)}\u201d`;
    case "COMMAND_LISTENING":
      return "Listening\u2026";
    case "PROCESSING":
      return "Thinking\u2026";
    case "RESPONDING":
      return "Speaking\u2026";
    case "ERROR":
      return "Hands-free error";
    case "STOPPED":
      return "Hands-free off";
    default:
      return "Hands-free";
  }
}

const MAX_RECORDING_MS = 60_000;
const AUTO_SPEAK_KEY = "friday.voice.autoSpeak";

function stageLabel(stage: string, captureSupported: boolean): string {
  if (stage === "LISTENING" && !captureSupported) return "Awaiting input";
  return PIPELINE_LABELS[stage] ?? stage;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Voice request failed.";
}

export function VoiceInteractionPanel({ allowTyped = false }: { allowTyped?: boolean }) {
  const { voice, sendChat, chatBusy, transcripts } = useDashboard();
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [heard, setHeard] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [wakeBusy, setWakeBusy] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<
    Array<{ id: string; text: string; model?: string }>
  >([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [autoSpeak, setAutoSpeak] = useState(() => {
    try {
      return window.localStorage.getItem(AUTO_SPEAK_KEY) !== "false";
    } catch {
      return true;
    }
  });

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const serverCaptureRef = useRef(false);
  const wakeAutoStartedRef = useRef(false);

  const setPhaseSafe = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const state = voice?.state ?? "UNKNOWN";
  const micAvailable = voice?.microphone.available ?? false;
  const captureSupported = voice?.capture_supported === true;
  const browserSupported = recordingSupported();
  const canRecord =
    micAvailable && captureSupported && browserSupported && !chatBusy &&
    phase !== "recording" && phase !== "transcribing" && phase !== "thinking";

  const captureActive = phase === "recording";
  const handsFree = voice?.hands_free;
  const handsFreeEnabled = handsFree?.enabled ?? true;
  const handsFreeActive = Boolean(handsFree?.active ?? voice?.hands_free_active);
  const handsFreeState = handsFree?.state ?? voice?.hands_free_state ?? "STOPPED";
  const wakeWord = handsFree?.wake_word ?? voice?.wake_word ?? "friday";
  const handsFreeStage = handsFreeActive ? HANDSFREE_STAGE[handsFreeState] ?? null : null;
  const orbStage = PHASE_STAGE[phase] ?? handsFreeStage ?? state;

  // Publish the local recorder phase so the global hologram overlay can wake
  // up while the user is on any page; reset it when the panel unmounts.
  useEffect(() => {
    setLocalVoicePhase(LOCAL_VOICE_PHASE[phase]);
  }, [phase]);

  useEffect(() => () => setLocalVoicePhase("idle"), []);

  const startHandsFree = useCallback(async () => {
    setWakeBusy(true);
    setError(null);
    try {
      await api.startHandsFree();
    } catch (wakeError) {
      setError(errorMessage(wakeError));
    } finally {
      setWakeBusy(false);
    }
  }, []);

  const stopHandsFree = useCallback(async () => {
    setWakeBusy(true);
    try {
      await api.stopHandsFree();
    } catch (wakeError) {
      setError(errorMessage(wakeError));
    } finally {
      setWakeBusy(false);
    }
  }, []);

  // Hands-free listening is automatic: no button press is required. Start it
  // once the microphone is known to be available, unless it is already on.
  useEffect(() => {
    if (wakeAutoStartedRef.current || !voice) return;
    if (!handsFreeEnabled || !voice.microphone.available) return;
    wakeAutoStartedRef.current = true;
    if (!voice.hands_free?.active) void startHandsFree();
  }, [handsFreeEnabled, startHandsFree, voice]);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const stopPlayback = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
  }, []);

  const playSpeech = useCallback(async (text: string) => {
    const blob = await api.speak(text);
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audioRef.current = audio;
    try {
      await audio.play();
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
      });
    } finally {
      URL.revokeObjectURL(url);
      if (audioRef.current === audio) audioRef.current = null;
    }
  }, []);

  const runTurn = useCallback(
    async (text: string) => {
      setPhaseSafe("thinking");
      setError(null);
      const response = await sendChat(text);
      if (!response) {
        setPhaseSafe("idle");
        return;
      }
      if (autoSpeak && response.response) {
        setPhaseSafe("speaking");
        try {
          await playSpeech(response.response);
        } catch (speechError) {
          setError(`Reply shown in chat, but speech playback failed: ${errorMessage(speechError)}`);
        }
      }
      setPhaseSafe("idle");
    },
    [autoSpeak, playSpeech, sendChat, setPhaseSafe],
  );

  const handleTranscript = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) {
        setError("I didn't catch any speech. Try again and speak a little closer to the mic.");
        setPhaseSafe("idle");
        return;
      }
      setHeard(trimmed);
      await runTurn(trimmed);
    },
    [runTurn, setPhaseSafe],
  );

  const handleRecordingStopped = useCallback(async () => {
    const mime = recorderRef.current?.mimeType || "audio/webm";
    const blob = new Blob(chunksRef.current, { type: mime });
    chunksRef.current = [];
    recorderRef.current = null;
    stopStream();

    if (blob.size === 0) {
      setError("No audio was captured. Check the microphone and try again.");
      setPhaseSafe("idle");
      return;
    }

    setPhaseSafe("transcribing");
    try {
      const samples = await decodeTo16kMono(blob);
      const wav = encodeWav(samples);
      const result = await api.transcribeAudio(wav);
      await handleTranscript(result.text);
    } catch (transcriptionError) {
      setError(errorMessage(transcriptionError));
      setPhaseSafe("idle");
    }
  }, [handleTranscript, setPhaseSafe, stopStream]);

  const stopServerRecording = useCallback(async () => {
    serverCaptureRef.current = false;
    setPhaseSafe("transcribing");
    try {
      const result = await api.stopCapture();
      await handleTranscript(result.text);
    } catch (transcriptionError) {
      setError(errorMessage(transcriptionError));
      setPhaseSafe("idle");
    }
  }, [handleTranscript, setPhaseSafe]);

  const stopRecording = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (serverCaptureRef.current) {
      void stopServerRecording();
      return;
    }
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
  }, [stopServerRecording]);

  const beginServerRecording = useCallback(
    async (browserError: unknown) => {
      try {
        const capture = await api.startCapture();
        serverCaptureRef.current = true;
        setNotice(
          `Browser microphone access was blocked (${errorMessage(browserError)}). ` +
            `Recording with the backend microphone${capture.device ? ` (${capture.device})` : ""} instead.`,
        );
        setPhaseSafe("recording");
        timerRef.current = window.setTimeout(() => stopRecording(), MAX_RECORDING_MS);
      } catch (fallbackError) {
        setPhaseSafe("idle");
        setError(
          `Could not open the microphone: ${errorMessage(browserError)}. ` +
            `Backend capture also failed: ${errorMessage(fallbackError)}`,
        );
      }
    },
    [setPhaseSafe, stopRecording],
  );

  const startRecording = useCallback(async () => {
    if (!canRecord) return;
    setError(null);
    setNotice(null);
    setHeard("");
    stopPlayback();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;
      const mimeType = preferredRecorderMime();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => void handleRecordingStopped();
      recorderRef.current = recorder;
      recorder.start();
      setPhaseSafe("recording");
      timerRef.current = window.setTimeout(() => stopRecording(), MAX_RECORDING_MS);
    } catch (recordError) {
      stopStream();
      await beginServerRecording(recordError);
    }
  }, [
    beginServerRecording,
    canRecord,
    handleRecordingStopped,
    setPhaseSafe,
    stopPlayback,
    stopRecording,
    stopStream,
  ]);

  const stopAll = useCallback(() => {
    if (phaseRef.current === "recording") {
      stopRecording();
    } else {
      stopPlayback();
      setPhaseSafe("idle");
    }
  }, [setPhaseSafe, stopPlayback, stopRecording]);

  const performSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    setSearchError("");
    try {
      const result = await api.search(searchQuery);
      setSearchResults(Array.isArray(result) ? result : []);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearchLoading(false);
    }
  }, [searchQuery]);

  useEffect(() => {
    try {
      window.localStorage.setItem(AUTO_SPEAK_KEY, String(autoSpeak));
    } catch {
      /* ignore */
    }
  }, [autoSpeak]);

  // Persist search state
  useEffect(() => {
    try {
      window.localStorage.setItem("friday.voice.search.v1", JSON.stringify({ query: searchQuery, results: searchResults.slice(-50) }));
    } catch {
      /* ignore */
    }
  }, [searchQuery, searchResults]);

  // Load search state
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("friday.voice.search.v1");
      if (saved) {
        const parsed = JSON.parse(saved);
        setSearchQuery(parsed.query || "");
        setSearchResults(parsed.results || []);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      recorderRef.current = null;
      if (serverCaptureRef.current) {
        serverCaptureRef.current = false;
        void api.stopCapture().catch(() => undefined);
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  const submit = async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    await runTurn(text);
  };

  const microphoneReady = micAvailable && browserSupported;
  const statusLabel = captureActive
    ? "Recording"
    : phase === "transcribing"
      ? "Transcribing"
      : phase === "thinking"
        ? "Thinking"
        : phase === "speaking"
          ? "Speaking"
          : handsFreeActive
            ? handsFreeLabel(handsFreeState, wakeWord)
            : microphoneReady
              ? "Microphone ready"
              : "No microphone";
  const wakeTitle = titleCase(wakeWord);

  return (
    <div className="stack">
      <div className="row between">
        <StatusPill
          status={microphoneReady ? (captureActive ? "running" : "idle") : "unavailable"}
          label={statusLabel}
          title={voice?.microphone.detail}
        />
        <span className="tiny muted">
          {transcripts.length > 0
            ? `Last transcript ${relativeTime(transcripts[transcripts.length - 1].timestamp)}`
            : "No transcript yet"}
        </span>
      </div>

      <div className="chip-row" style={{ justifyContent: "center" }}>
        {(voice?.pipeline ?? ["IDLE", "LISTENING", "PROCESSING", "RESPONDING"]).map((pipelineStage) => {
          const active = pipelineStage === orbStage;
          return (
            <span
              className="chip"
              key={pipelineStage}
              style={{
                borderColor: active ? "var(--line-strong)" : undefined,
                color: active ? "var(--text)" : undefined,
                background: active ? "rgba(56,189,248,0.12)" : undefined,
              }}
            >
              {stageLabel(pipelineStage, captureSupported)}
            </span>
          );
        })}
      </div>

      <div
        className="row between"
        style={{
          gap: 12,
          padding: "10px 12px",
          border: "1px solid var(--line)",
          borderRadius: 10,
          background: handsFreeActive ? "rgba(56,189,248,0.06)" : undefined,
        }}
      >
        <div className="stack-sm">
          <span className="tiny muted">Hands-free</span>
          <strong style={{ fontSize: 14 }}>{handsFreeLabel(handsFreeState, wakeWord)}</strong>
          <span className="tiny muted">
            {handsFreeActive
              ? `Say \u201cHey ${wakeTitle}\u201d, then ask your question. Replies are spoken automatically.`
              : handsFreeEnabled
                ? "Always-on wake-word listening is paused."
                : "Disabled in config.yaml (voice.hands_free)."}
          </span>
        </div>
        <button
          type="button"
          className={handsFreeActive ? "btn btn-ghost" : "btn btn-primary"}
          onClick={() => void (handsFreeActive ? stopHandsFree() : startHandsFree())}
          disabled={wakeBusy || !handsFreeEnabled || !micAvailable}
          title={
            handsFreeActive
              ? "Pause hands-free listening"
              : "Resume hands-free wake-word listening"
          }
        >
          <Icon name={handsFreeActive ? "pause" : "mic"} size={15} />
          {wakeBusy ? "Working\u2026" : handsFreeActive ? "Pause" : "Resume"}
        </button>
      </div>

      {handsFreeState === "ERROR" && handsFree?.error ? (
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">Hands-free unavailable</span>
            {handsFree.error}
          </div>
        </div>
      ) : null}

      <div className="row" style={{ justifyContent: "center", gap: 8 }}>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => void startRecording()}
          disabled={!canRecord}
          title={
            !browserSupported
              ? "This browser does not support MediaRecorder microphone capture."
              : !micAvailable
                ? "No microphone was reported by the backend."
                : "Record a single turn from the browser microphone"
          }
        >
          <Icon name="mic" size={15} />
          {captureActive ? "Recording\u2026" : "Record one turn"}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={stopAll}
          disabled={phase !== "recording" && phase !== "speaking"}
          title={phase === "recording" ? "Stop recording and transcribe" : "Stop playback"}
        >
          Stop
        </button>
      </div>

      <label className="row tiny muted" style={{ justifyContent: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={autoSpeak}
          onChange={(event) => setAutoSpeak(event.target.checked)}
        />
        Speak manual replies aloud
      </label>

      <p className="tiny muted center">
        {voice?.reason ??
          "Record a question in the browser; audio is transcribed locally and answered by the local model."}
      </p>

      {notice ? <p className="tiny muted center">{notice}</p> : null}

      <div className="row" style={{ justifyContent: "center", gap: 8 }}>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => void performSearch()}
          disabled={searchLoading}
          title="Search F.R.I.D.A.Y's memory and knowledge">
          <Icon name="search" size={15} />
          {searchLoading ? "Searching…" : "Search knowledge"}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setSearchQuery("")}
          disabled={searchLoading}
          title="Clear search">
          <Icon name="close" size={15} />
        </button>
      </div>

      {searchLoading ? (
        <p className="tiny muted center">Searching…</p>
      ) : null}

      {searchError ? (
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">Search failed</span>
            {searchError}
          </div>
        </div>
      ) : null}

      {searchResults.length > 0 ? (
        <div className="list">
          {searchResults.map((result) => (
            <div
              className="list-row"
              key={result.id}
              onClick={() => {
                setHeard(result.text);
                setPhaseSafe("idle");
                setSearchQuery("");
                setSearchResults([]);
              }}
            >
              <span className="list-main">{result.text}</span>
              <span className="list-meta">{result.model ?? "memory"}</span>
            </div>
          ))}
        </div>
      ) : null}

      {heard ? (
        <p className="tiny muted center">
          Heard: <span style={{ color: "var(--text)" }}>{heard}</span>
        </p>
      ) : null}

      {error ? (
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">Voice request failed</span>
            {error}
          </div>
        </div>
      ) : null}

      {!microphoneReady ? (
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">Microphone unavailable</span>
            {!browserSupported
              ? "This browser does not support microphone recording. Use a Chromium or Firefox browser."
              : voice?.microphone.detail ?? "No audio input device was reported by the backend."}
          </div>
        </div>
      ) : null}

      {allowTyped ? (
        <div className="stack-sm" style={{ marginTop: 4 }}>
          <label className="tiny muted" htmlFor="voice-typed-input">
            Prefer typing? Send a turn through the same assistant pipeline.
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
