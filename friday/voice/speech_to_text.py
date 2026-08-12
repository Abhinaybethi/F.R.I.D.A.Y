import time
import numpy as np

from faster_whisper import WhisperModel

from friday.utils.logger import get_logger

logger = get_logger(__name__)

# Silent 1-second audio used for the warm-up run after model load.
# Runs CTranslate2 kernel compilation so the first real utterance is not penalised.
_WARMUP_AUDIO = np.zeros(16000, dtype=np.float32)


def _cuda_is_usable() -> bool:
    """Return True only when CUDA and the required DLLs are genuinely available."""
    try:
        import ctypes
        ctypes.cdll.LoadLibrary("cublas64_12.dll")
    except (OSError, AttributeError):
        return False
    try:
        import ctypes
        ctypes.cdll.LoadLibrary("cudnn_ops64_9.dll")
    except (OSError, AttributeError):
        return False
    return True


class SpeechToText:
    """
    Wrapper around faster-whisper.

    Decoding parameters are tuned for low-latency voice-assistant commands:

    Parameter                  Value   Reason
    -------------------------  ------  -------------------------------------------
    beam_size                  1       Greedy decode is 2-4× faster than beam=5 for
                                       short commands with negligible accuracy loss.
    temperature                0       Single deterministic pass; no fallback retries.
    condition_on_previous_text False   Isolated utterances — prior context wastes time
                                       and can introduce hallucinations between commands.
    language                   en      Explicit; skips language-detection overhead.
    vad_filter                 False   We apply our own Silero VAD before calling
                                       transcribe(); double-VAD adds latency with no gain.
    """

    def __init__(
        self,
        model_size: str = "small.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
    ):
        self.language = language
        self.model_size = model_size
        self.model: WhisperModel | None = None

        # Resolve device BEFORE loading the model so we never touch CUDA if it's broken
        if device == "auto":
            if _cuda_is_usable():
                device = "cuda"
                compute_type = "float16"
                logger.info("[STT] CUDA DLLs found — using GPU.")
            else:
                device = "cpu"
                compute_type = "int8"
                logger.info("[STT] CUDA DLLs not found — using CPU int8.")

        self.active_device = device
        self.active_compute = compute_type

        self.model = self._load_model(device, compute_type)

        logger.info(
            "[STT] Model: %s | Device: %s | Compute: %s",
            model_size,
            self.active_device.upper(),
            self.active_compute,
        )

        # Warm-up: trigger CTranslate2 kernel compilation now so the first
        # real utterance does not absorb the JIT overhead (which causes RTF outliers).
        if self.model is not None:
            self._warmup()

    # ------------------------------------------------------------------
    def _load_model(self, device: str, compute_type: str) -> WhisperModel | None:
        try:
            logger.info(
                "[STT] Loading faster-whisper '%s' on %s / %s ...",
                self.model_size, device, compute_type,
            )
            m = WhisperModel(self.model_size, device=device, compute_type=compute_type)
            logger.info("[STT] Model loaded successfully.")
            return m
        except Exception as e:
            if device != "cpu":
                logger.warning(
                    "[STT] Load on %s failed (%s). Falling back to CPU int8.", device, e
                )
                self.active_device = "cpu"
                self.active_compute = "int8"
                return self._load_model("cpu", "int8")
            logger.error("[STT] CPU model load also failed: %s", e)
            return None

    def _warmup(self):
        """
        Run one silent transcription to force CTranslate2 to compile its CPU kernels.
        This ensures the first real utterance does not incur first-inference overhead.
        """
        logger.info("[STT] Running warm-up transcription to pre-compile kernels ...")
        t0 = time.perf_counter()
        try:
            segs, _ = self.model.transcribe(
                _WARMUP_AUDIO,
                language=self.language,
                beam_size=1,
                temperature=0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            # Consume the generator — transcription is lazy
            _ = "".join(s.text for s in segs)
        except Exception as e:
            logger.warning("[STT] Warm-up failed (non-fatal): %s", e)
        elapsed = time.perf_counter() - t0
        logger.info("[STT] Warm-up complete in %.2fs.", elapsed)

    # ------------------------------------------------------------------
    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        """
        Transcribe ``audio`` (float32, 16 kHz, mono).

        Returns
        -------
        (text, rtf)
            text  — lower-cased transcript, or "" if nothing was recognised.
            rtf   — transcription_time / audio_duration (lower is faster).
        """
        if self.model is None or audio is None or len(audio) == 0:
            return "", 0.0

        audio_sec = len(audio) / 16000
        t0 = time.perf_counter()

        try:
            segs, _ = self.model.transcribe(
                audio,
                language=self.language,
                beam_size=1,
                temperature=0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            text = "".join(s.text for s in segs).strip().lower()
        except Exception as e:
            err = str(e)
            logger.error("[STT] Transcription error: %s", err)
            # Handle unexpected CUDA failures mid-session
            if any(kw in err.lower() for kw in ("cublas", "cudnn", "cuda", "dll")):
                logger.warning("[STT] CUDA failed mid-transcription — reloading on CPU.")
                self.active_device = "cpu"
                self.active_compute = "int8"
                self.model = self._load_model("cpu", "int8")
                if self.model:
                    self._warmup()
                    try:
                        segs, _ = self.model.transcribe(
                            audio,
                            language=self.language,
                            beam_size=1,
                            temperature=0,
                            condition_on_previous_text=False,
                            vad_filter=False,
                        )
                        text = "".join(s.text for s in segs).strip().lower()
                    except Exception as e2:
                        logger.error("[STT] CPU retry failed: %s", e2)
                        return "", 0.0
                else:
                    return "", 0.0
            else:
                return "", 0.0

        elapsed = time.perf_counter() - t0
        rtf = elapsed / audio_sec if audio_sec > 0 else 0.0
        logger.info(
            "[STT] Done | audio=%.1fs | transcription=%.2fs | RTF=%.2f",
            audio_sec, elapsed, rtf,
        )
        return text, rtf
