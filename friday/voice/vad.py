import os
import yaml
import numpy as np
import onnxruntime as ort

from friday.utils.logger import get_logger

logger = get_logger(__name__)


class VoiceActivityDetector:
    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5):
        self.sample_rate = sample_rate
        self.threshold = threshold
        
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            
        model_path = config.get("voice", {}).get("vad", {}).get("model_path", "models/vad/silero_vad.onnx")
        
        if not os.path.exists(model_path):
            logger.error("Silero VAD model not found: %s\nRun: python main.py --download-voice-models", model_path)
            self.session = None
        else:
            try:
                self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                logger.info("Silero VAD initialized from local file.")
            except Exception as e:
                logger.error("Failed to load Silero VAD: %s", e)
                self.session = None
        self.reset_states()

    def reset_states(self):
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        if self.session is None:
            return False
            
        if audio_chunk.ndim == 1:
            audio_chunk = np.expand_dims(audio_chunk, axis=0)
            
        inputs = {
            'x': audio_chunk.astype(np.float32),
            'h': self._h,
            'c': self._c
        }
        try:
            out, self._h, self._c = self.session.run(None, inputs)
            return out[0][0] > self.threshold
        except Exception as e:
            logger.error("VAD inference error: %s", e)
            return False
