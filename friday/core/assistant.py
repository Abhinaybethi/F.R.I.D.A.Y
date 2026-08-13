"""
Friday — main orchestrator.

Pipeline:
    Wake word → listen_once() → ConversationManager → tool/response
"""
import yaml

from friday.voice.session_manager import VoiceSessionManager
from friday.voice.text_to_speech import TextToSpeech
from friday.core.wake_word import WakeWordListener
from friday.core.conversation import ConversationManager
from friday.utils.logger import get_logger


class Friday:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        log_cfg = self.config.get("logging", {})
        self.logger = get_logger(
            "friday",
            log_file=log_cfg.get("file", "logs/friday.log"),
            level=log_cfg.get("level", "INFO"),
        )

        voice_cfg = self.config.get("voice", {})
        tts_cfg = voice_cfg.get("tts", {})
        self.tts = TextToSpeech(
            engine=tts_cfg.get("engine", "kokoro"),
            fallback_engine=tts_cfg.get("fallback_engine", "piper"),
            voice=tts_cfg.get("voice", "af_heart"),
            speed=tts_cfg.get("speed", 1.0),
            device=tts_cfg.get("device", "auto"),
        )

        listening_cfg = self.config.get("listening", {})
        self.session_manager = VoiceSessionManager(
            stt_config=voice_cfg.get("stt", {}),
            listening_config=listening_cfg,
            debug_config=voice_cfg.get("debug", {}),
        )

        self.wake_word_listener = WakeWordListener(
            self.session_manager, wake_word=self.config.get("wake_word", "friday")
        )

        tools_cfg = self.config.get("tools", {})
        self._dry_run = tools_cfg.get("dry_run", True)
        self._allow_real_execution = tools_cfg.get("allow_real_execution", False)

        self.conversation_manager = ConversationManager(
            dry_run=self._dry_run,
            allow_real_execution=self._allow_real_execution,
        )

    # ------------------------------------------------------------------
    def _handle(self, transcript: str) -> bool:
        """
        Route one transcript through the conversation manager.
        Returns False when the user asks to stop/exit.
        """
        response, keep_running = self.conversation_manager.handle_transcript(transcript)
        if response:
            self.tts.speak(response)
        return keep_running

    def run(self):
        self.tts.speak("Friday online. Say my name whenever you need me.")

        with self.session_manager:
            self.conversation_manager.start_session()
            while True:
                self.wake_word_listener.wait_for_wake_word()
                self.tts.speak("Yes?")

                transcript = self.session_manager.listen_once()

                if not transcript:
                    self.tts.speak("Sorry, I didn't catch that.")
                    continue

                keep_running = self._handle(transcript)
                if not keep_running:
                    break

            self.conversation_manager.stop_session()

    def shutdown(self):
        self.logger.info("Friday shutting down.")
        self.tts.stop()
        self.conversation_manager.stop_session()
        self.session_manager.stop_session()
