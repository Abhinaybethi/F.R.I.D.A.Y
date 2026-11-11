import { LiveTranscript } from "../components/LiveTranscript";
import { StatusPill } from "../components/StatusPill";
import { VoiceInteractionPanel } from "../components/VoiceInteractionPanel";
import { useDashboard } from "../state/DashboardContext";

export function VoicePage() {
  const { voice, transcripts, health } = useDashboard();
  const micHealth = health?.components?.microphone;
  const sttHealth = health?.components?.stt;
  const ttsHealth = health?.components?.tts;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Voice</span>
          <h1>Voice console</h1>
          <p>
            Hands-free is on: just say <strong>“Hey Friday”</strong> and ask your question. The machine
            microphone is always listening for the wake word, audio is transcribed locally by
            faster-whisper, and replies are spoken aloud — nothing is sent to a cloud service. You can
            still record a single turn from the browser or type below.
          </p>
        </div>
        <StatusPill
          status={voice?.microphone.available ? "idle" : "unavailable"}
          label={
            voice?.hands_free?.active
              ? `Listening for “Hey ${voice.hands_free.wake_word}”`
              : voice?.microphone.available
                ? "Microphone ready"
                : "No microphone"
          }
        />
      </div>

      <div className="grid grid-2">
        <section className="panel panel-accent" aria-labelledby="voice-control">
          <div className="panel-head">
            <div>
              <h2 id="voice-control">Interaction</h2>
              <p className="panel-sub">Wake word → local transcription → local model → spoken reply</p>
            </div>
          </div>
          <div className="panel-body">
            <VoiceInteractionPanel allowTyped />
          </div>
        </section>

        <section className="panel" aria-labelledby="voice-transcript">
          <div className="panel-head">
            <div>
              <h2 id="voice-transcript">Transcript</h2>
              <p className="panel-sub">{transcripts.length} real turns in this session</p>
            </div>
          </div>
          <div className="panel-body">
            <LiveTranscript />
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Audio pipeline</h2>
            <p className="panel-sub">Component availability is probed by the backend</p>
          </div>
        </div>
        <div className="panel-body">
          <div className="grid grid-3">
            <div className="stat-tile">
              <span className="label">Microphone</span>
              <div style={{ marginTop: 4 }}>
                <StatusPill status={micHealth?.status ?? "unknown"} />
              </div>
              <span className="foot">{micHealth?.detail ?? voice?.microphone.detail ?? "No data"}</span>
            </div>
            <div className="stat-tile">
              <span className="label">Speech recognition</span>
              <div style={{ marginTop: 4 }}>
                <StatusPill status={sttHealth?.status ?? "unknown"} />
              </div>
              <span className="foot">{sttHealth?.detail ?? "faster-whisper status not reported"}</span>
            </div>
            <div className="stat-tile">
              <span className="label">Text to speech</span>
              <div style={{ marginTop: 4 }}>
                <StatusPill status={ttsHealth?.status ?? "unknown"} />
              </div>
              <span className="foot">{ttsHealth?.detail ?? "TTS status not reported"}</span>
            </div>
          </div>
          <p className="tiny muted" style={{ marginTop: 12 }}>
            Wake-word detection, transcription, and speech synthesis run locally in the F.R.I.D.A.Y.
            backend; the dashboard only reflects state. Hands-free replies play on this machine's default
            output, so they are not also played in the browser.
          </p>
        </div>
      </section>
    </div>
  );
}
