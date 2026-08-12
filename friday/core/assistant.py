"""
Friday - main orchestrator.

Loads config, wires together voice I/O, the LLM brain, web search, and the
command router, then runs the listen -> route -> respond loop.
"""
import yaml

from friday.voice.session_manager import VoiceSessionManager
from friday.voice.text_to_speech import TextToSpeech
from friday.core.wake_word import WakeWordListener
from friday.core.command_router import CommandRouter
from friday.brain.llm_client import LLMClient
from friday.brain.web_search import WebSearch
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

        brain_cfg = self.config.get("brain", {})
        self.llm_client = LLMClient(
            base_url=brain_cfg.get("ollama_url", "http://localhost:11434"),
            model=brain_cfg.get("ollama_model", "llama3.2"),
        )
        self.web_search = WebSearch()

        self.router = CommandRouter(self.tts, self.llm_client, self.web_search)
        self._listening_cfg = listening_cfg

    def run(self):
        self.tts.speak("Friday online. Say my name whenever you need me.")

        if not self.llm_client.is_available():
            self.logger.warning(
                "Ollama isn't reachable at startup. Knowledge answers will "
                "rely on web search only until Ollama is running. See README."
            )

        # Open the microphone once for the entire session.
        self.session_manager.start_session()

        while True:
            self.wake_word_listener.wait_for_wake_word()
            self.tts.speak("Yes?")

            command = self.session_manager.listen_once()

            if not command:
                self.tts.speak("Sorry, I didn't catch that.")
                continue

            keep_running = self.router.route(command)
            if not keep_running:
                break

    def shutdown(self):
        self.logger.info("Friday shutting down.")
        self.session_manager.stop_session()
