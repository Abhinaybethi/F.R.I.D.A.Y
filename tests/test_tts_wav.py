import io
import wave
from types import SimpleNamespace

from friday.voice.text_to_speech import TextToSpeech


class _FakePiper:
    """Mimics piper's behaviour of re-applying WAV format on every call."""

    def __init__(self) -> None:
        self.config = SimpleNamespace(sample_rate=16000)
        self.calls = 0

    def synthesize_wav(self, text: str, wav_file, set_wav_format: bool = True) -> None:
        wav_file.setframerate(self.config.sample_rate)
        wav_file.setsampwidth(2)
        wav_file.setnchannels(1)
        wav_file.writeframes(b"\x00\x00" * 100)
        self.calls += 1


def test_multi_sentence_wav_does_not_reuse_writer():
    tts = object.__new__(TextToSpeech)
    tts.engine_name = "piper"
    tts.fallback_engine = "kokoro"
    tts.piper = _FakePiper()
    tts.kokoro = None
    tts.voice = "af_heart"
    tts.speed = 1.0

    wav = tts.synthesize_wav("First sentence. Second sentence.")

    with wave.open(io.BytesIO(wav), "rb") as wav_file:
        assert wav_file.getnframes() == 200
        assert wav_file.getframerate() == 16000
    assert tts.piper.calls == 2
