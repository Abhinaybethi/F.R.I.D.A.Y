"""
Simple, free wake-word detection.

Rather than relying on a paid wake-word engine, Friday continuously listens
in short bursts and checks whether the configured wake word (default:
"friday") appears in what was heard. This is free and works anywhere
SpeechToText works, at the cost of being slightly less efficient than a
dedicated wake-word model like Porcupine.
"""
from friday.voice.session_manager import VoiceSessionManager
from friday.utils.logger import get_logger

logger = get_logger(__name__)


class WakeWordListener:
    def __init__(self, session: VoiceSessionManager, wake_word: str = "friday"):
        self.session = session
        self.wake_word = wake_word.lower()

    def wait_for_wake_word(self):
        """Blocks until the wake word is heard, then returns."""
        logger.info("Listening for wake word '%s'...", self.wake_word)
        while True:
            text = self.session.listen_once()
            if text and self.wake_word in text:
                logger.info("Wake word detected.")
                return
