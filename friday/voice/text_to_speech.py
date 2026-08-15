import io
import os
import wave
import time
import re
import yaml
import soundfile as sf
import sounddevice as sd

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class TextToSpeech:
    def __init__(self, engine="piper", fallback_engine="kokoro", voice="af_heart", speed=1.0, device="auto"):
        self.engine_name = engine
        self.fallback_engine = fallback_engine
        self.voice = voice
        self.speed = speed
        self.kokoro = None
        self.piper = None
        self._is_speaking = False
        import threading
        self.abort_event = threading.Event()
        
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        tts_cfg = config.get("voice", {}).get("tts", {})
        self.kokoro_model = tts_cfg.get("kokoro_model", "models/tts/kokoro/kokoro-v1.0.int8.onnx")
        self.kokoro_voices = tts_cfg.get("kokoro_voices", "models/tts/kokoro/voices-v1.0.bin")
        self.piper_model = tts_cfg.get("piper_model", "models/tts/piper/en_US-lessac-low.onnx")
        self.piper_config = tts_cfg.get("piper_config", "models/tts/piper/en_US-lessac-low.onnx.json")
        
        if engine == "kokoro" or fallback_engine == "kokoro":
            self._init_kokoro()
        if engine == "piper" or fallback_engine == "piper":
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

    def warmup(self) -> None:
        """Pre-synthesizes a single short token to pre-load ONNX sessions and avoid cold-start latency on first turn."""
        try:
            if self.piper is not None:
                wav_io = io.BytesIO()
                with wave.open(wav_io, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(self.piper.config.sample_rate)
                    self.piper.synthesize_wav("a", wav_file)
            elif self.kokoro is not None:
                self.kokoro.create("a", voice=self.voice, speed=1.0, lang="en-us")
            logger.info("TTS model pre-warming completed.")
        except Exception as e:
            logger.warning("TTS model pre-warming skipped: %s", e)

    def _clean_for_speech(self, text: str) -> str:
        if not text:
            return ""
        
        # Remove dry-run prefix just in case some string bypasses the structured message
        text = text.replace("[DRY RUN] ", "")
                
        # Remove http/https urls
        text = re.sub(r"https?://[^\s]+", "the website", text)
        return text.strip()

    def stop(self):
        self.abort_event.set()
        sd.stop()
        
    def is_speaking(self):
        return self._is_speaking

    def speak(self, text: str) -> None:
        if not text:
            return
            
        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return
            
        print(f"Friday: {clean_text}")
        
        self.abort_event.clear()
        self._is_speaking = True
        
        try:
            if self.engine_name == "kokoro" and self.kokoro is not None:
                try:
                    self._speak_kokoro(clean_text)
                    return
                except Exception as e:
                    logger.warning("Kokoro TTS failed during synthesis: %s", e)
            elif self.engine_name == "piper" and self.piper is not None:
                try:
                    self._speak_piper(clean_text)
                    return
                except Exception as e:
                    import traceback
                    logger.warning("Piper TTS failed during synthesis: %s\n%s", e, traceback.format_exc())
            
            # Fallbacks
            if self.fallback_engine == "kokoro" and self.kokoro is not None:
                try:
                    self._speak_kokoro(clean_text)
                    return
                except Exception as e:
                    logger.error("Kokoro fallback failed: %s", e)
            elif self.fallback_engine == "piper" and self.piper is not None:
                try:
                    self._speak_piper(clean_text)
                    return
                except Exception as e:
                    logger.error("Piper fallback failed: %s", e)
        finally:
            self._is_speaking = False

    def _play_interruptible(self, data, fs):
        duration = len(data) / fs
        sd.play(data, fs)

        # Wait until duration has passed or abort_event is set
        aborted = self.abort_event.wait(duration)
            
        if aborted:
            sd.stop()
        else:
            sd.wait()

    def _speak_kokoro(self, text: str):
        t0 = time.time()
        samples, sample_rate = self.kokoro.create(text, voice=self.voice, speed=self.speed, lang="en-us")
        t1 = time.time()
        duration = len(samples) / sample_rate
        rtf = (t1 - t0) / duration if duration > 0 else 0
        logger.info("[TTS] Kokoro synthesis=%.2fs audio=%.2fs RTF=%.2f", t1 - t0, duration, rtf)
        
        self._play_interruptible(samples, sample_rate)

    def _speak_piper(self, text: str):
        t0 = time.time()
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.piper.config.sample_rate)
            self.piper.synthesize_wav(text, wav_file)
        wav_io.seek(0)
        data, fs = sf.read(wav_io)
        t1 = time.time()
        duration = len(data) / fs
        rtf = (t1 - t0) / duration if duration > 0 else 0
        logger.info("[TTS] Piper synthesis=%.2fs audio=%.2fs RTF=%.2f", t1 - t0, duration, rtf)
        
        self._play_interruptible(data, fs)
