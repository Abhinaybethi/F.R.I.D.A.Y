import io
import os
import wave
import yaml
import soundfile as sf
import sounddevice as sd

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class TextToSpeech:
    def __init__(self, engine="kokoro", fallback_engine="piper", voice="af_heart", speed=1.0, device="auto"):
        self.engine_name = engine
        self.fallback_engine = fallback_engine
        self.voice = voice
        self.speed = speed
        self.kokoro = None
        self.piper = None
        
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        tts_cfg = config.get("voice", {}).get("tts", {})
        self.kokoro_model = tts_cfg.get("kokoro_model", "models/tts/kokoro/kokoro-v0_19.onnx")
        self.kokoro_voices = tts_cfg.get("kokoro_voices", "models/tts/kokoro/voices.json")
        self.piper_model = tts_cfg.get("piper_model", "models/tts/piper/en_US-lessac-low.onnx")
        self.piper_config = tts_cfg.get("piper_config", "models/tts/piper/en_US-lessac-low.onnx.json")
        
        if engine == "kokoro":
            self._init_kokoro()
        if fallback_engine == "piper":
            self._init_piper()

    def _init_kokoro(self):
        if not os.path.exists(self.kokoro_model) or not os.path.exists(self.kokoro_voices):
            logger.error("Kokoro models missing. Run: python main.py --download-voice-models")
            return
            
        try:
            from kokoro_onnx import Kokoro
            self.kokoro = Kokoro(self.kokoro_model, self.kokoro_voices)
            logger.info("Kokoro TTS initialized from local files.")
        except Exception as e:
            logger.error("Failed to load Kokoro locally: %s", e)

    def _init_piper(self):
        if not os.path.exists(self.piper_model) or not os.path.exists(self.piper_config):
            logger.error("Piper models missing. Run: python main.py --download-voice-models")
            return
            
        try:
            from piper.voice import PiperVoice
            self.piper = PiperVoice.load(self.piper_model, self.piper_config)
            logger.info("Piper TTS initialized from local files.")
        except Exception as e:
            logger.error("Failed to load Piper fallback: %s", e)

    def speak(self, text: str) -> None:
        if not text:
            return
        
        print(f"Friday: {text}")
        
        if self.engine_name == "kokoro" and self.kokoro is not None:
            try:
                self._speak_kokoro(text)
                return
            except Exception as e:
                logger.warning("Kokoro TTS failed during synthesis: %s", e)
        
        if self.fallback_engine == "piper" and self.piper is not None:
            try:
                self._speak_piper(text)
            except Exception as e:
                logger.error("Piper TTS fallback failed during synthesis: %s", e)

    def _speak_kokoro(self, text: str):
        samples, sample_rate = self.kokoro.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        sd.play(samples, sample_rate)
        sd.wait()

    def _speak_piper(self, text: str):
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            self.piper.synthesize(text, wav_file)
        wav_io.seek(0)
        data, fs = sf.read(wav_io)
        sd.play(data, fs)
        sd.wait()
