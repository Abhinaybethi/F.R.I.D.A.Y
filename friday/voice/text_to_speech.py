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

    def synthesize_wav(self, text: str) -> bytes:
        """Render *text* to a single WAV byte string without playing it.

        The dashboard's ``/api/voice/speak`` endpoint returns these bytes to
        the browser for playback, so this path must never touch the local
        output device. Each sentence is synthesized into its own buffer and
        the raw frames are concatenated: Piper re-applies the WAV format on
        every ``synthesize_wav`` call, which makes a shared writer invalid.
        """
        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return b""

        engine = None
        if self.engine_name == "piper" and self.piper is not None:
            engine = "piper"
        elif self.engine_name == "kokoro" and self.kokoro is not None:
            engine = "kokoro"
        elif self.fallback_engine == "piper" and self.piper is not None:
            engine = "piper"
        elif self.fallback_engine == "kokoro" and self.kokoro is not None:
            engine = "kokoro"
        elif self.piper is not None:
            engine = "piper"
        elif self.kokoro is not None:
            engine = "kokoro"

        if engine == "piper":
            return self._synthesize_wav_piper(clean_text)
        if engine == "kokoro":
            return self._synthesize_wav_kokoro(clean_text)
        raise RuntimeError("No TTS engine is available to synthesize speech.")

    def _synthesize_wav_piper(self, text: str) -> bytes:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()] or [text]
        config = getattr(self.piper, "config", None)
        sample_rate = int(getattr(config, "sample_rate", 22050) or 22050)
        channels = 1
        sampwidth = 2
        frames = bytearray()

        for sentence in sentences:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(sampwidth)
                wav_file.setframerate(sample_rate)
                self.piper.synthesize_wav(sentence, wav_file)
            buffer.seek(0)
            with wave.open(buffer, "rb") as wav_file:
                channels = wav_file.getnchannels()
                sampwidth = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frames.extend(wav_file.readframes(wav_file.getnframes()))

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sampwidth)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(frames))
        return output.getvalue()

    def _synthesize_wav_kokoro(self, text: str) -> bytes:
        import numpy as np

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()] or [text]
        chunks = []
        sample_rate = 24000
        for sentence in sentences:
            samples, sample_rate = self.kokoro.create(
                sentence, voice=self.voice, speed=self.speed, lang="en-us"
            )
            chunks.append(np.asarray(samples, dtype=np.float32).reshape(-1))

        data = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
        buffer = io.BytesIO()
        sf.write(buffer, data, int(sample_rate), format="WAV", subtype="PCM_16")
        return buffer.getvalue()

    def speak(self, text: str) -> None:
        if not text:
            return

        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return

        logger.info("[TTS] Speaking response: %r", clean_text)
        print(f"Friday: {clean_text}")

        self.abort_event.clear()
        self._is_speaking = True

        try:
            units, synth_seconds, playback_seconds = self._synthesize(clean_text)
        finally:
            self._is_speaking = False

        # Per-request aggregation so a response's TTS work is attributable to
        # a single request_id (P10). Fallback only re-synthesizes when the
        # primary engine produced ZERO units (never a partial response).
        from friday.utils.logger import request_id_var
        req = request_id_var.get()
        logger.info(
            "[TTS] response complete: request_id=%s units=%d synthesis=%.0fms "
            "playback_total=%.0fms",
            req, units, synth_seconds * 1000.0, playback_seconds * 1000.0,
        )

    def _synthesize(self, text: str):
        """
        Run the primary engine, falling back ONLY when it produced no audio
        (units == 0). Returns (units, synthesis_seconds, playback_seconds).
        """
        primaries = []
        if self.engine_name == "kokoro" and self.kokoro is not None:
            primaries.append(("kokoro", self._speak_kokoro))
        elif self.engine_name == "piper" and self.piper is not None:
            primaries.append(("piper", self._speak_piper))

        fallbacks = []
        if self.fallback_engine == "kokoro" and self.kokoro is not None:
            fallbacks.append(("kokoro", self._speak_kokoro))
        elif self.fallback_engine == "piper" and self.piper is not None:
            fallbacks.append(("piper", self._speak_piper))

        tried = set()
        for name, method in primaries + fallbacks:
            if name in tried:
                continue
            tried.add(name)
            try:
                units, synth_seconds, playback_seconds = method(text)
            except Exception as e:
                logger.warning("TTS %s failed during synthesis: %s", name, e)
                continue
            if units and units > 0:
                return units, synth_seconds, playback_seconds
        return 0, 0.0, 0.0

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
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()] or [text]
        units = 0
        synth_seconds = 0.0
        playback_seconds = 0.0
        for s in sentences:
            if self.abort_event.is_set():
                break
            try:
                t0 = time.time()
                samples, sample_rate = self.kokoro.create(s, voice=self.voice, speed=self.speed, lang="en-us")
                if self.abort_event.is_set():
                    break
                t1 = time.time()
                duration = len(samples) / sample_rate
                rtf = (t1 - t0) / duration if duration > 0 else 0
                logger.info("[TTS] Kokoro synthesis=%.2fs audio=%.2fs RTF=%.2f", t1 - t0, duration, rtf)
                synth_seconds += t1 - t0
                playback_seconds += duration

                self._play_interruptible(samples, sample_rate)
                units += 1
            except Exception as e:
                logger.warning("[TTS] Kokoro failed mid-response at unit %d: %s", units + 1, e)
                break
            if self.abort_event.is_set():
                break
        return units, synth_seconds, playback_seconds

    def _speak_piper(self, text: str):
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()] or [text]
        units = 0
        synth_seconds = 0.0
        playback_seconds = 0.0
        for s in sentences:
            if self.abort_event.is_set():
                break
            try:
                t0 = time.time()
                wav_io = io.BytesIO()
                with wave.open(wav_io, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(self.piper.config.sample_rate)
                    self.piper.synthesize_wav(s, wav_file)
                if self.abort_event.is_set():
                    break
                wav_io.seek(0)
                data, fs = sf.read(wav_io)
                t1 = time.time()
                duration = len(data) / fs
                rtf = (t1 - t0) / duration if duration > 0 else 0
                logger.info("[TTS] Piper synthesis=%.2fs audio=%.2fs RTF=%.2f", t1 - t0, duration, rtf)
                synth_seconds += t1 - t0
                playback_seconds += duration

                self._play_interruptible(data, fs)
                units += 1
            except Exception as e:
                logger.warning("[TTS] Piper failed mid-response at unit %d: %s", units + 1, e)
                break
            if self.abort_event.is_set():
                break
        return units, synth_seconds, playback_seconds
