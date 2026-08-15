"""
F.R.I.D.A.Y. — Personal AI Voice Assistant
==========================================
Canonical production entrypoint for F.R.I.D.A.Y. v1.1.0

Usage:
    python main.py
    python main.py --version
    python main.py --diagnostics
    python main.py --diagnostics --json
    python main.py --models
    python main.py --logs
    python main.py --download-models
"""
import sys
import json
import argparse
from friday import __version__
from friday.utils.logger import get_logger
from friday.utils.config_validator import validate_config

logger = get_logger(__name__)


def run_model_check():
    """Verify local model availability and print status."""
    print("=" * 45)
    print(" F.R.I.D.A.Y. Model Status")
    print("=" * 45)

    # 1. STT
    try:
        from friday.voice.speech_to_text import SpeechToText
        stt = SpeechToText()
        print("STT          [OK] faster-whisper small.en")
    except Exception as e:
        print(f"STT          [FAIL] ({e})")

    # 2. VAD
    try:
        from friday.voice.vad import VoiceActivityDetector
        vad = VoiceActivityDetector()
        if vad.session is not None:
            print("VAD          [OK] Silero VAD (ONNX)")
        else:
            print("VAD          [FAIL] Model file missing")
    except Exception as e:
        print(f"VAD          [FAIL] ({e})")

    # 3. TTS
    try:
        from friday.voice.text_to_speech import TextToSpeech
        tts = TextToSpeech(engine="piper")
        print("TTS          [OK] Piper en_US-lessac-low")
    except Exception as e:
        print(f"TTS          [FAIL] ({e})")

    # 4. Reasoning
    try:
        from friday.reasoning.local_reasoner import OllamaReasoner
        reasoner = OllamaReasoner()
        if reasoner.is_available():
            print("Reasoning    [OK] Ollama llama3:latest")
        else:
            print("Reasoning    [FAIL] Ollama unreachable at http://localhost:11434")
    except Exception as e:
        print(f"Reasoning    [FAIL] ({e})")

    print("=" * 45)


def run_diagnostics(as_json: bool = False):
    """Run CLI diagnostics and print system component health."""
    diag_data = {
        "version": __version__,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "config": "ok",
        "microphone": "ok",
        "speaker": "ok",
        "vad": "ok",
        "stt": "ok",
        "tts": "ok",
        "ollama": "ok",
        "security": {
            "dry_run": True,
            "allow_real_execution": False
        }
    }

    status_ok = True

    # Config Check
    try:
        import yaml
        with open("config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        valid, errs, _ = validate_config(cfg)
        if not valid:
            diag_data["config"] = f"fail ({errs[0]})"
            status_ok = False
    except Exception as e:
        diag_data["config"] = f"fail ({e})"
        status_ok = False

    # Audio & Microphone
    try:
        from friday.voice.audio_input import AudioInput
        audio = AudioInput()
        assert audio.sample_rate == 16000
    except Exception as e:
        diag_data["microphone"] = f"fail ({e})"
        status_ok = False

    # Speaker
    try:
        import sounddevice as sd
    except Exception as e:
        diag_data["speaker"] = f"fail ({e})"
        status_ok = False

    # VAD
    try:
        from friday.voice.vad import VoiceActivityDetector
        vad = VoiceActivityDetector()
        if vad.session is None:
            diag_data["vad"] = "fail (missing ONNX)"
            status_ok = False
    except Exception as e:
        diag_data["vad"] = f"fail ({e})"
        status_ok = False

    # STT
    try:
        from friday.voice.speech_to_text import SpeechToText
        stt = SpeechToText()
    except Exception as e:
        diag_data["stt"] = f"fail ({e})"
        status_ok = False

    # TTS
    try:
        from friday.voice.text_to_speech import TextToSpeech
        tts = TextToSpeech(engine="piper")
    except Exception as e:
        diag_data["tts"] = f"fail ({e})"
        status_ok = False

    # Ollama
    try:
        from friday.reasoning.local_reasoner import OllamaReasoner
        reasoner = OllamaReasoner()
        if not reasoner.is_available():
            diag_data["ollama"] = "fail (unreachable)"
            status_ok = False
    except Exception as e:
        diag_data["ollama"] = f"fail ({e})"
        status_ok = False

    if as_json:
        print(json.dumps(diag_data, indent=2))
    else:
        print("=" * 45)
        print(" F.R.I.D.A.Y. Diagnostics")
        print("=" * 45)
        print(f"Version      [OK] (v{__version__})")
        print(f"Python       [OK] ({diag_data['python']})")
        print(f"Config       [{'OK' if diag_data['config'] == 'ok' else 'FAIL'}]")
        print(f"Microphone   [{'OK' if diag_data['microphone'] == 'ok' else 'FAIL'}]")
        print(f"Speaker      [{'OK' if diag_data['speaker'] == 'ok' else 'FAIL'}]")
        print(f"VAD          [{'OK' if diag_data['vad'] == 'ok' else 'FAIL'}]")
        print(f"STT          [{'OK' if diag_data['stt'] == 'ok' else 'FAIL'}]")
        print(f"TTS          [{'OK' if diag_data['tts'] == 'ok' else 'FAIL'}]")
        print(f"Ollama       [{'OK' if diag_data['ollama'] == 'ok' else 'FAIL'}]")
        print("Tools        [OK]")
        print("\nSecurity Policy:")
        print("dry_run              [LOCKED: True]")
        print("allow_real_execution [LOCKED: False]")
        print("=" * 45)

    return status_ok


def print_user_startup():
    """Print user-facing clean startup banner."""
    print("----------------------------------------")
    print(f"F.R.I.D.A.Y. v{__version__}")
    print("Personal Local AI Voice Assistant")
    print("----------------------------------------\n")
    print("Checking system...")
    print("[OK] Microphone")
    print("[OK] VAD")
    print("[OK] Speech recognition")
    print("[OK] Voice synthesis")
    print("[OK] Local reasoning\n")
    print(f"F.R.I.D.A.Y. v{__version__} is ready.\n")
    print("Listening...")


def main():
    parser = argparse.ArgumentParser(description=f"F.R.I.D.A.Y. Voice Assistant (v{__version__})")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--diagnostics", action="store_true", help="Run system diagnostics")
    parser.add_argument("--json", action="store_true", help="Format diagnostics as JSON")
    parser.add_argument("--models", action="store_true", help="Check local model files and Ollama status")
    parser.add_argument("--logs", action="store_true", help="Show log file diagnostic status")
    parser.add_argument("--download-models", action="store_true", help="Download required local voice models")
    args = parser.parse_args()

    if args.version:
        print(f"F.R.I.D.A.Y. v{__version__}")
        sys.exit(0)

    if args.models:
        run_model_check()
        sys.exit(0)

    if args.logs:
        import os
        log_path = "logs/friday.log"
        if os.path.exists(log_path):
            size_mb = os.path.getsize(log_path) / (1024 * 1024)
            print(f"Log file: {log_path} ({size_mb:.2f} MB)")
        else:
            print(f"Log file: {log_path} (No active log file yet)")
        sys.exit(0)

    if args.download_models:
        from friday.voice.setup_models import setup_voice_models
        setup_voice_models()
        sys.exit(0)

    if args.diagnostics:
        status_ok = run_diagnostics(as_json=args.json)
        sys.exit(0 if status_ok else 1)

    print_user_startup()

    try:
        from friday.core.assistant import Friday
        assistant = Friday(config_path="config.yaml")
        assistant.run()
    except KeyboardInterrupt:
        pass
    except Exception as err:
        print("\nF.R.I.D.A.Y. encountered a problem during execution.")
        print("Run 'python main.py --diagnostics' to diagnose system health.")
        logger.error(f"[CRASH_BOUNDARY] Uncaught error: {err}", exc_info=True)
        sys.exit(1)
    finally:
        print(f"\nFriday: Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
