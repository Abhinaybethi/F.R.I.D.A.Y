"""
F.R.I.D.A.Y. Local STT Test
============================
Tests the full voice pipeline (mic → VAD → STT) with the microphone
initialized ONCE for the entire session.

Run:
    python tests/test_local_stt.py

Press Ctrl+C to stop.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.voice.session_manager import VoiceSessionManager


def main():
    print("\nF.R.I.D.A.Y. Local STT Test")
    print("=" * 36)

    sm = VoiceSessionManager()
    stt = sm.stt

    print(f"\n  Model   : {stt.model_size}")
    print(f"  Device  : {stt.active_device.upper()}")
    print(f"  Compute : {stt.active_compute}")

    if stt.model is None:
        print("\n[ERROR] STT model failed to load — cannot continue.")
        sys.exit(1)

    print("\nReady. Speak naturally.")
    print("Press Ctrl+C to stop.\n")

    # Use context manager — guarantees mic is closed on Ctrl+C
    try:
        with sm as session:
            while True:
                print("Listening...")
                text = session.listen_once()
                if text:
                    print(f"Heard: {text}\n")
                else:
                    print("(silence or no speech detected)\n")
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}")
        raise


if __name__ == "__main__":
    main()
