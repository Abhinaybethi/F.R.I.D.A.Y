"""
Simple, free wake-word detection.

Rather than relying on a paid wake-word engine, Friday continuously listens
in short bursts and checks whether the configured wake word (default:
"friday") opens what was heard. This is free and works anywhere
SpeechToText works, at the cost of being slightly less efficient than a
dedicated wake-word model like Porcupine.

Matching is delegated to :class:`friday.voice.wake.WakeMatcher` so the CLI and
the dashboard cannot disagree about what a wake word is.
"""
from friday.voice.session_manager import VoiceSessionManager
from friday.voice.wake import WakeMatcher
from friday.utils.logger import get_logger

logger = get_logger(__name__)


class WakeWordListener:
    def __init__(self, session: VoiceSessionManager, wake_word: str = "friday"):
        self.session = session
        self.wake_word = wake_word.lower()
        self._matcher = WakeMatcher(self.wake_word)

    def _opens_with_wake_word(self, text: str) -> bool:
        """True only when the utterance starts with the wake word.

        ``"hey friday open chrome"`` -> True
        ``"I asked friday about it"`` -> False (mere mention)
        """
        return self._matcher.opens_with_wake_word(text)

    def wait_for_wake_word(self) -> str:
        """Blocks until speech opening with the wake word is heard, then returns the transcript."""
        logger.info("[WAKE] Listening for wake word '%s'...", self.wake_word)
        while True:
            text = self.session.listen_once()
            if not text:
                continue
            if self._opens_with_wake_word(text):
                logger.info("[WAKE] Wake word detected in: %r", text)
                return text
            logger.info("[WAKE] Heard (no wake word, still listening): %r", text)
