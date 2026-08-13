"""
Hardware Voice Conversation Test.

Verifies full multi-turn conversation flow with real voice input:
  1. "open groom"               -> CONFIRM ("Did you mean Chrome?")
  2. "yes"                      -> CONFIRMED -> Chrome DRY RUN
  3. "open youtube"             -> SAFE -> YouTube DRY RUN
  4. "open grove"               -> CONFIRM ("Did you mean Chrome?")
  5. "no"                       -> CANCELLED -> returns LISTENING
  6. "what time is it"          -> SAFE -> Time response
  7. "stop"                     -> SYSTEM_STOP -> Clean exit

DRY RUN MODE ONLY. Real execution remains disabled.

Run:
    python tests/test_voice_conversation.py
"""
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.voice.session_manager import VoiceSessionManager
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState


def main():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    voice_cfg = config.get("voice", {})
    stt_cfg = voice_cfg.get("stt", {})
    listening_cfg = config.get("listening", {})
    debug_cfg = voice_cfg.get("debug", {})

    print("=" * 60)
    print("  VOICE CONVERSATION TEST (DRY RUN ONLY)")
    print("=" * 60)
    print("  Suggested sequence to speak:")
    print("    1. 'open groom'")
    print("    2. 'yes'")
    print("    3. 'open youtube'")
    print("    4. 'open grove'")
    print("    5. 'no'")
    print("    6. 'what time is it'")
    print("    7. 'stop'\n")

    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    session = VoiceSessionManager(
        stt_config=stt_cfg,
        listening_config=listening_cfg,
        debug_config=debug_cfg,
    )

    with session:
        cm.start_session()

        try:
            while True:
                transcript = session.listen_once()
                if not transcript:
                    continue

                print(f"\n[VOICE] Transcript : {transcript!r}")
                print(f"[STATE] State BEFORE: {cm.state.name}")

                response, keep_running = cm.handle_transcript(transcript)

                print(f"[STATE] State AFTER : {cm.state.name}")
                print(f"[ASSISTANT] Response: {response}")

                if not keep_running or cm.state == ConversationState.STOPPING:
                    print("\n[VOICE] Received STOP command. Exiting session cleanly.")
                    break

        except KeyboardInterrupt:
            print("\n\n[VOICE] Interrupted by Ctrl+C. Exiting session cleanly.")

    print("=" * 60)
    print("  Voice Conversation Test Completed.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
