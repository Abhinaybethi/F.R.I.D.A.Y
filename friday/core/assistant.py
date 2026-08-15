"""
Friday — main orchestrator.

Pipeline:
    Wake word → listen_once() → ConversationManager → tool/response
"""
import yaml

from friday.voice.session_manager import VoiceSessionManager
from friday.voice.text_to_speech import TextToSpeech
from friday.core.wake_word import WakeWordListener
from friday.core.conversation import ConversationManager, ConversationState
from friday.utils.logger import get_logger
from friday.utils.config_validator import validate_config


class Friday:
    def __init__(self, config_path: str = "config.yaml"):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}
        except Exception as e:
            raw_config = {}

        _, self.config, warnings = validate_config(raw_config)

        log_cfg = self.config.get("logging", {})
        self.logger = get_logger(
            "friday",
            log_file=log_cfg.get("file", "logs/friday.log"),
            level=log_cfg.get("level", "INFO"),
        )
        for w in warnings:
            self.logger.warning("[STARTUP] Config warning: %s", w)

        voice_cfg = self.config.get("voice", {})
        tts_cfg = voice_cfg.get("tts", {})
        self.tts = TextToSpeech(
            engine=tts_cfg.get("engine", "piper"),
            fallback_engine=tts_cfg.get("fallback_engine", "kokoro"),
            voice=tts_cfg.get("voice", "af_heart"),
            speed=tts_cfg.get("speed", 1.0),
            device=tts_cfg.get("device", "auto"),
        )
        self.tts.warmup()

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
        self._permissions = tools_cfg.get("permissions", {})

        self.conversation_manager = ConversationManager(
            dry_run=self._dry_run,
            allow_real_execution=self._allow_real_execution,
            permissions=self._permissions,
        )
        from friday.voice.async_session import AsyncVoiceSessionManager
        self.async_session = AsyncVoiceSessionManager(self.session_manager, self.tts)

    def pause_listening(self):
        """Pause voice command processing without shutting down streams."""
        if self.conversation_manager.state != ConversationState.PAUSED:
            self.conversation_manager.state_machine.transition_to(ConversationState.PAUSED)
            self.logger.info("Listening paused.")

    def resume_listening(self):
        """Resume voice command processing from PAUSED state."""
        if self.conversation_manager.state == ConversationState.PAUSED:
            self.conversation_manager.state_machine.transition_to(ConversationState.LISTENING)
            self.logger.info("Listening resumed.")

    # ------------------------------------------------------------------
    def _handle(self, transcript: str) -> bool:
        """
        Route one transcript through the conversation manager.
        Returns False when the user asks to stop/exit.
        """
        if self.conversation_manager.state == ConversationState.PAUSED:
            return True

        response, keep_running = self.conversation_manager.handle_transcript(transcript)
        if response:
            self.async_session.start_barge_in_listener()
            self.tts.speak(response)
            self.async_session.stop_barge_in_listener()
        return keep_running

    def run(self):
        self.tts.speak("Friday online. Listening...")

        with self.session_manager:
            self.conversation_manager.start_session()
            while True:
                if self.conversation_manager.state == ConversationState.PAUSED:
                    import time
                    time.sleep(0.1)
                    continue

                self.wake_word_listener.wait_for_wake_word()

                import uuid
                from friday.utils.logger import request_id_var
                req_id = uuid.uuid4().hex[:8]
                request_id_var.set(req_id)
                self.logger.info("New request started.")

                transcript = self.session_manager.listen_once()

                # Debounce background noise / empty STT fragments
                if not transcript or len(transcript.strip()) < 2:
                    self.logger.info("Ignoring empty transcript.")
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
