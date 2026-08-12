"""
Friday - Personal AI Voice Assistant
=====================================
Run this file to start Friday:

    python main.py

Say "Friday" to wake her up, then speak a command or question.
Say "stop", "exit", "quit", or "goodbye" to shut her down.
"""
import sys
import argparse

from friday.core.assistant import Friday


def run_voice_diagnostics():
    print("F.R.I.D.A.Y. Voice Diagnostics\n")
    
    # 1. Microphone
    try:
        from friday.voice.audio_input import AudioInput
        audio = AudioInput()
        audio.start()
        audio.stop()
        print("Microphone ........ PASS")
    except Exception as e:
        print(f"Microphone ........ FAIL ({e})")
        return
        
    # 2. VAD
    try:
        from friday.voice.vad import VoiceActivityDetector
        vad = VoiceActivityDetector()
        if vad.session is None:
            raise RuntimeError("VAD session failed to initialize.")
        print("Silero VAD ........ PASS")
    except Exception as e:
        print(f"Silero VAD ........ FAIL ({e})")
        
    # 3. STT
    try:
        from friday.voice.speech_to_text import SpeechToText
        stt = SpeechToText()
        if stt.model is None:
            raise RuntimeError("Faster-whisper model failed to initialize.")
        print("faster-whisper .... PASS")
    except Exception as e:
        print(f"faster-whisper .... FAIL ({e})")
        
    # 4. TTS
    try:
        from friday.voice.text_to_speech import TextToSpeech
        tts = TextToSpeech(engine="kokoro")
        if tts.kokoro is None:
            raise RuntimeError("Kokoro TTS failed to initialize.")
        print("Kokoro TTS ........ PASS")
    except Exception as e:
        print(f"Kokoro TTS ........ FAIL ({e})")
        
    # 5. Speaker
    try:
        import sounddevice as sd
        sd.check_output_settings()
        print("Audio playback .... PASS")
    except Exception as e:
        print(f"Audio playback .... FAIL ({e})")
        
    print("\nVoice system ready.")


def main():
    parser = argparse.ArgumentParser(description="Friday Assistant")
    parser.add_argument("--voice-test", action="store_true", help="Run voice diagnostics")
    parser.add_argument("--download-voice-models", action="store_true", help="Download missing local voice models")
    args = parser.parse_args()

    if args.download_voice_models:
        from friday.voice.setup_models import setup_voice_models
        setup_voice_models()
        sys.exit(0)

    if args.voice_test:
        run_voice_diagnostics()
        sys.exit(0)

    assistant = Friday(config_path="config.yaml")
    try:
        assistant.run()
    except KeyboardInterrupt:
        pass
    finally:
        assistant.shutdown()
        print("\nFriday: Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
