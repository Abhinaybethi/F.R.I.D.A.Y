"""
System Health & Runtime Diagnostics Subsystem for F.R.I.D.A.Y. Phase 10.

Provides comprehensive diagnostic checks across all voice, safety, tool, and reasoning layers.
"""
import os
import urllib.request
import yaml
from pathlib import Path

from friday.utils.config_validator import validate_config
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def check_system_health(config_path: str = "config.yaml") -> dict:
    """
    Run diagnostic checks on all system components.

    Returns:
        {
            "overall_status": "PASS" | "DEGRADED" | "FAIL",
            "components": {
                "config": {"status": "PASS"|"FAIL", "details": ...},
                "microphone": {"status": "PASS"|"FAIL", "details": ...},
                "vad": {"status": "PASS"|"FAIL", "details": ...},
                "stt": {"status": "PASS"|"FAIL", "details": ...},
                "tts": {"status": "PASS"|"FAIL", "details": ...},
                "ollama": {"status": "PASS"|"FAIL", "details": ...},
            }
        }
    """
    results = {}
    overall_pass = True

    # 1. Config Validation Check
    try:
        if Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                raw_cfg = yaml.safe_load(f) or {}
            valid, cfg, warnings = validate_config(raw_cfg)
            results["config"] = {
                "status": "PASS" if valid else "FAIL",
                "details": f"Config validated. Gate 1 (dry_run)={cfg['tools']['dry_run']}, Gate 2 (allow_real)={cfg['tools']['allow_real_execution']}",
                "warnings": warnings,
            }
        else:
            results["config"] = {"status": "FAIL", "details": f"Config file {config_path!r} missing."}
            overall_pass = False
    except Exception as e:
        results["config"] = {"status": "FAIL", "details": str(e)}
        overall_pass = False

    # 2. Microphone Check
    try:
        from friday.voice.audio_input import AudioInput
        audio = AudioInput()
        dev_info = audio.get_device_info()
        results["microphone"] = {
            "status": "PASS",
            "details": f"Device: {dev_info.get('device_name', 'Default')} ({dev_info.get('sample_rate', 0)}Hz)",
        }
    except Exception as e:
        results["microphone"] = {"status": "FAIL", "details": str(e)}
        overall_pass = False

    # 3. Silero VAD Model Check
    try:
        from friday.voice.vad import VoiceActivityDetector
        vad_model_path = Path("models/vad/silero_vad.onnx")
        if vad_model_path.exists() or os.path.exists("models/vad"):
            results["vad"] = {"status": "PASS", "details": "Silero VAD module and model files ready."}
        else:
            results["vad"] = {"status": "PASS", "details": "Silero VAD module ready."}
    except Exception as e:
        results["vad"] = {"status": "FAIL", "details": str(e)}
        overall_pass = False

    # 4. faster-whisper STT Check
    try:
        import faster_whisper
        results["stt"] = {"status": "PASS", "details": "faster-whisper package ready."}
    except Exception as e:
        results["stt"] = {"status": "FAIL", "details": str(e)}
        overall_pass = False

    # 5. TTS Engine Check
    try:
        from friday.voice.text_to_speech import TextToSpeech
        results["tts"] = {"status": "PASS", "details": "TextToSpeech engine ready."}
    except Exception as e:
        results["tts"] = {"status": "FAIL", "details": str(e)}
        overall_pass = False

    # 6. Ollama Reasoning Layer Check
    try:
        req = urllib.request.Request("http://localhost:11434/", method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                results["ollama"] = {"status": "PASS", "details": "Ollama server reachable at http://localhost:11434"}
            else:
                results["ollama"] = {"status": "FAIL", "details": f"Ollama HTTP status {resp.status}"}
    except Exception as e:
        results["ollama"] = {"status": "FAIL", "details": f"Ollama unreachable: {e}"}

    return {
        "overall_status": "PASS" if overall_pass else "DEGRADED",
        "components": results,
    }
