import os
import requests
import yaml
from friday.utils.logger import get_logger

logger = get_logger(__name__)


def download_file(url, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if os.path.exists(dest_path):
        return True
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error("Failed to download %s to %s: %s", url, dest_path, e)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise e


def setup_voice_models(config_path="config.yaml"):
    print("F.R.I.D.A.Y. Voice Model Setup\n")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    voice = config.get("voice", {})
    vad_path = voice.get("vad", {}).get("model_path", "models/vad/silero_vad.onnx")
    tts = voice.get("tts", {})
    kokoro_model = tts.get("kokoro_model", "models/tts/kokoro/kokoro-v1.0.int8.onnx")
    kokoro_voices = tts.get("kokoro_voices", "models/tts/kokoro/voices-v1.0.bin")
    piper_model = tts.get("piper_model", "models/tts/piper/en_US-lessac-low.onnx")
    piper_config = tts.get("piper_config", "models/tts/piper/en_US-lessac-low.onnx.json")

    # 1. Download Silero VAD
    try:
        download_file("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx", vad_path)
        print("Silero VAD ........ DOWNLOADED")
    except Exception as e:
        print(f"Silero VAD ........ FAILED ({e})")
        
    # 2. Download Kokoro
    try:
        download_file("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx", kokoro_model)
        print("Kokoro model ...... DOWNLOADED")
    except Exception as e:
        print(f"Kokoro model ...... FAILED ({e})")
        
    try:
        download_file("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin", kokoro_voices)
        print("Kokoro voices ..... DOWNLOADED")
    except Exception as e:
        print(f"Kokoro voices ..... FAILED ({e})")
        
    # 3. Download Piper
    try:
        download_file("https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx", piper_model)
        download_file("https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low/en_US-lessac-low.onnx.json", piper_config)
        print("Piper voice ....... READY")
    except Exception as e:
        print(f"Piper voice ....... FAILED ({e})")
        
    print("\nVoice models ready.")


if __name__ == "__main__":
    setup_voice_models()
