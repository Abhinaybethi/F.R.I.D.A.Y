"""
Friday — main orchestrator.

Stateful, wake-gated voice lifecycle by default (per the interaction spec):

    IDLE -> WAKE_DETECTED -> COMMAND_LISTENING (bare wake: "Yes?" + window)
         -> PROCESSING -> EXECUTING -> SPEAKING -> IDLE

Pipeline:
    wake word -> _command_after_wake() -> _process_transcript()
        -> ConversationManager -> deterministic router / reasoner -> tool/response

With `voice.wake_word_required: false`, the assistant is hands-free and every
legible transcript streams straight into the same pipeline as text mode.
"""
import os
import yaml

from friday.voice.session_manager import VoiceSessionManager, _NO_SPEECH
from friday.voice.text_to_speech import TextToSpeech
from friday.core.wake_word import WakeWordListener
from friday.core.conversation import ConversationManager, ConversationState
from friday.voice.state_machine import VoiceState, VoiceStateMachine
from friday.intent.normalizer import normalize
from friday.reasoning.interface import Reasoner
from friday.reasoning.local_reasoner import OllamaReasoner
from friday.reasoning.llamacpp_reasoner import LlamaCppReasoner
from friday.reasoning.llamacpp_server import LlamaCppServerManager
from friday.utils.logger import get_logger
from friday.utils.config_validator import validate_config


def _build_reasoner(reasoning_cfg: dict) -> Reasoner:
    """Construct the configured local reasoning provider.

    Priority: FRIDAY_REASONING_PROVIDER env var > config.yaml reasoning.provider.
    """
    env_provider = os.environ.get("FRIDAY_REASONING_PROVIDER", "").strip().lower()
    provider = env_provider or reasoning_cfg.get("provider", "llamacpp")

    if provider == "ollama":
        endpoint = reasoning_cfg.get("endpoint") or "http://localhost:11434/api/generate"
        model = reasoning_cfg.get("model") or "llama3:latest"
        return OllamaReasoner(endpoint=endpoint, model=model)

    base_url = reasoning_cfg.get("endpoint") or "http://127.0.0.1:8080"
    model = reasoning_cfg.get("model") or "C:\\AI\\models\\Bonsai-8B-Q1_0.gguf"
    timeout = float(reasoning_cfg.get("timeout", 30))
    return LlamaCppReasoner(base_url=base_url, model=model, timeout=timeout)


class Friday:
    def __init__(self, config_path: str = "config.yaml", text_mode: bool = False):
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

        self.text_mode = text_mode
        # Explicit voice lifecycle state machine (IDLE/WAKE/CMD/PROCESS/EXECUTING/SPEAKING).
        self.voice_state = VoiceStateMachine()

        tools_cfg = self.config.get("tools", {})
        self._dry_run = tools_cfg.get("dry_run", True)
        self._allow_real_execution = tools_cfg.get("allow_real_execution", False)
        self._permissions = tools_cfg.get("permissions", {})
        # Wake-gated by default per the interaction spec: background/non-wake
        # speech is ignored in IDLE. Set `voice.wake_word_required: false` for
        # a hands-free assistant (commands stream straight into the pipeline).
        voice_cfg_top = self.config.get("voice", {})
        self._wake_word_required = bool(voice_cfg_top.get("wake_word_required", True))

        reasoning_cfg = self.config.get("reasoning", {})
        self.reasoner = _build_reasoner(reasoning_cfg)
        provider = reasoning_cfg.get("provider", "llamacpp")

        # Manage the llama.cpp server lifecycle when llamacpp provider is selected.
        self.server_manager = None
        if provider == "llamacpp":
            server_cfg = reasoning_cfg.get("server", {})
            self.server_manager = LlamaCppServerManager(
                base_url=reasoning_cfg.get("endpoint") or "http://127.0.0.1:8080",
                model_path=reasoning_cfg.get("model") or "C:\\AI\\models\\Bonsai-8B-Q1_0.gguf",
                executable=server_cfg.get("executable", "llama-server"),
                context_size=int(server_cfg.get("context_size", 2048)),
                auto_start=bool(server_cfg.get("auto_start", True)),
                startup_timeout=float(server_cfg.get("startup_timeout", 60)),
            )
            skip_start = os.environ.get("FRIDAY_SKIP_LLAMACPP_STARTUP", "").strip().lower() in ("1", "true", "yes")
            if skip_start:
                self.logger.info("[STARTUP] Skipping llama.cpp server auto-start (env override)")
            elif self.server_manager.start():
                self.logger.info("[STARTUP] Reasoner server ready")
            else:
                self.logger.warning("[STARTUP] llama.cpp reasoning server unavailable")
                self.logger.warning("[STARTUP] Deterministic commands remain operational")

        self.logger.info(
            "[STARTUP] Reasoning provider: %s (model=%s endpoint=%s)",
            provider, self.reasoner.model, getattr(self.reasoner, "base_url", None) or getattr(self.reasoner, "endpoint", None),
        )

        self.conversation_manager = ConversationManager(
            dry_run=self._dry_run,
            allow_real_execution=self._allow_real_execution,
            permissions=self._permissions,
            reasoner=self.reasoner,
            conversation_timeout_seconds=voice_cfg_top.get("conversation_timeout_seconds", 300),
        )

        # Text mode skips all voice components (mic/VAD/STT/TTS/wake-word).
        self.tts = None
        self.session_manager = None
        self.wake_word_listener = None
        self.async_session = None
        if not self.text_mode:
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
    def _process_transcript(self, transcript: str) -> tuple[str, bool]:
        """
        Route one transcript through the real conversation manager pipeline.

        Returns (response_text, keep_running). This is the single shared entry
        point used by both the voice loop and text mode.
        """
        if self.conversation_manager.state == ConversationState.PAUSED:
            return "", True

        self.logger.info("[ASSISTANT] Processing request: %r", transcript)
        response, keep_running = self.conversation_manager.handle_transcript(transcript)
        self.logger.info("[ASSISTANT] Final response: %r", response)
        return response, keep_running

    def _handle(self, transcript: str) -> bool:
        """
        Route one transcript through the conversation manager and speak the reply.
        Returns False when the user asks to stop/exit.
        """
        if self.conversation_manager.state == ConversationState.PAUSED:
            return True

        response, keep_running = self._process_transcript(transcript)
        self.voice_state.transition_to(VoiceState.EXECUTING)
        if response and self.tts is not None:
            self.voice_state.transition_to(VoiceState.SPEAKING)
            self.async_session.start_barge_in_listener()
            self.tts.speak(response)
            self.async_session.stop_barge_in_listener()
        return keep_running

    def run_text(self):
        """
        Interactive text (non-voice) loop. Reuses the exact Assistant ->
        ConversationManager -> router -> reasoner/tool pipeline as the voice
        assistant, but reads commands from stdin instead of a microphone.
        """
        self.conversation_manager.start_session()
        print("F.R.I.D.A.Y. text mode. Type 'exit' or 'quit' to leave.")
        import uuid
        from friday.utils.logger import request_id_var

        while True:
            try:
                line = input("You: ")
            except EOFError:
                break

            line = line.strip()
            if not line:
                continue

            if line.lower() in ("exit", "quit"):
                break

            req_id = uuid.uuid4().hex[:8]
            request_id_var.set(req_id)
            self.logger.info("New request started: %r", line)

            response, keep_running = self._process_transcript(line)

            if response:
                print(f"Friday: {response}")

            if not keep_running:
                break

        self.conversation_manager.stop_session()

    def _is_legible(self, text: str) -> bool:
        """True when a transcript is real speech a command could be made of."""
        if not text:
            return False
        stripped = text.strip().lower()
        if len(stripped) < 2 or stripped == _NO_SPEECH.lower():
            return False
        norm = normalize(stripped)
        return bool(norm) and norm != "no clear speech detected"

    def _ack_wake(self):
        """Brief acknowledgment after a bare wake word ('friday' -> 'Yes?')."""
        if self.tts is not None:
            try:
                self.logger.info("[WAKE] Acknowledging wake word.")
                self.tts.speak("Yes?")
            except Exception as e:
                self.logger.warning("[WAKE] TTS acknowledgment failed: %s", e)

    def _strip_wake_prefix(self, text: str) -> str:
        """
        Remove a leading wake phrase if present ("hey friday open chrome" ->
        "open chrome"; "friday" -> ""). Non-empty results are already clean
        commands and the empty result means the bare wake word was spoken.
        """
        wake_cfg = (self.config.get("wake_word") or "").strip().lower()
        if not wake_cfg or not text:
            return text
        stripped = text.strip()
        lowered = stripped.lower()
        for prefix in (f"hey {wake_cfg}", wake_cfg):
            if lowered == prefix:
                return ""
            if lowered.startswith(prefix) and stripped[len(prefix):len(prefix) + 1] in ("", " ", ",", "."):
                return stripped[len(prefix):].lstrip(" ,.")
        return text

    def _command_after_wake(self, wake_text: str) -> str:
        """
        Convert a wake-word transcript into a CLEAN normalized command.

        One-shot:  "hey friday open chrome"  -> "open chrome"
        Two-stage: "friday" then command -> speaks "Yes?", opens a bounded
        command window and returns the command so a pause between wake word and
        command (common after VAD segmentation) is NOT lost to the wake gate.

        Returns the normalized command string, or "" when nothing legible
        was heard within the command window (caller returns to wake listening).
        """
        wake_cfg = (self.config.get("wake_word") or "").strip().lower()
        bare_forms = (wake_cfg, f"hey {wake_cfg}")

        norm = normalize(wake_text)

        # One-shot: wake phrase + command spoken together.
        if norm and norm not in bare_forms:
            self.logger.info("[WAKE] Wake word detected — extracted command: %r", norm)
            return norm

        # Bare wake word ("friday") — acknowledge and open a short command
        # window so the user can say the command right after (two-stage).
        self.voice_state.transition_to(VoiceState.COMMAND_LISTENING)
        self._ack_wake()
        self.logger.info("[WAKE] Wake word detected — awaiting command.")
        max_attempts = int(self.config.get("listening", {}).get("wake_command_attempts", 3))
        listened = 0
        while listened < max_attempts:
            transcript = self.session_manager.listen_once()
            if not self._is_legible(transcript):
                listened += 1
                continue
            candidate = normalize(transcript)
            if not candidate or candidate in bare_forms:
                listened += 1
                continue
            self.logger.info("[WAKE] Command captured: %r", candidate)
            return candidate

        self.logger.info("[WAKE] No command within window; returning to wake-word listening.")
        return ""

    def run(self):
        self.tts.speak("Friday online. Listening...")

        with self.session_manager:
            self.conversation_manager.start_session()
            while True:
                if self.conversation_manager.state == ConversationState.PAUSED:
                    import time
                    time.sleep(0.1)
                    continue

                # In confirmation state, bypass wake word listening and directly capture confirmation answer
                if self.conversation_manager.state == ConversationState.WAITING_FOR_CONFIRMATION:
                    self.logger.info("Waiting for confirmation response...")
                    transcript = self.session_manager.listen_once()
                else:
                    # Active session? Then no wake word is required for each
                    # command — stay in COMMAND_LISTENING until it expires.
                    session_active = self.conversation_manager.session.is_active()
                    wake_cfg = (self.config.get("wake_word") or "").strip()

                    if self._wake_word_required and self.wake_word_listener and wake_cfg and not session_active:
                        # Wake-gated standby. Only leave IDLE once the wake
                        # phrase is heard (one-shot "hey friday open chrome" or
                        # two-stage: "friday" -> "Yes?" -> command).
                        wake_text = self.wake_word_listener.wait_for_wake_word()
                        if not wake_text:
                            # No legible wake transcript; keep listening.
                            self.voice_state.transition_to(VoiceState.IDLE)
                            continue
                        self.logger.info("[WAKE] Heard: %r", wake_text)
                        self.voice_state.transition_to(VoiceState.WAKE_DETECTED)
                        # Opening the session keeps subsequent commands hands-free.
                        self.conversation_manager.session.start()
                        self.logger.info("[SESSION] Active session started")
                        transcript = self._command_after_wake(wake_text)
                        if not transcript:
                            # Bare wake, then silence/illegible -> back to standby.
                            self.voice_state.transition_to(VoiceState.IDLE)
                            continue
                    else:
                        # Hands-free: active session (or wake permanently disabled).
                        self.voice_state.transition_to(
                            VoiceState.COMMAND_LISTENING if session_active else VoiceState.IDLE
                        )
                        transcript = self.session_manager.listen_once()
                        if session_active:
                            stripped = self._strip_wake_prefix(transcript)
                            if stripped == "" and transcript:
                                # Bare wake repeated mid-session — re-ack now, keep listening.
                                self._ack_wake()
                                continue
                            transcript = stripped

                import uuid
                from friday.utils.logger import request_id_var
                req_id = uuid.uuid4().hex[:8]
                request_id_var.set(req_id)
                self.logger.info("New request started: %r", transcript)

                # Debounce background noise / empty STT fragments / no-legible-speech
                if not self._is_legible(transcript):
                    self.logger.info("[VOICE] Speech detected but no legible transcript; returning to listening.")
                    self.voice_state.transition_to(
                        VoiceState.COMMAND_LISTENING
                        if self.conversation_manager.session.is_active() else VoiceState.IDLE
                    )
                    continue

                self.voice_state.transition_to(VoiceState.PROCESSING)
                keep_running = self._handle(transcript)
                if not keep_running:
                    self.voice_state.transition_to(VoiceState.IDLE)
                    break
                # While the session is active, loop back to command listening —
                # do NOT return to wake-word detection after every response.
                if self.conversation_manager.session.is_active():
                    self.voice_state.transition_to(VoiceState.COMMAND_LISTENING)
                else:
                    self.voice_state.transition_to(VoiceState.IDLE)

            self.conversation_manager.stop_session()

    def shutdown(self):
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self.logger.info("[SHUTDOWN] Friday shutting down.")
        if self.tts is not None:
            self.tts.stop()
        self.conversation_manager.stop_session()
        if self.session_manager is not None:
            self.session_manager.stop_session()
        if self.async_session is not None:
            self.async_session.stop_barge_in_listener()
        if self.server_manager is not None:
            if self.server_manager.is_owned():
                self.logger.info("[SHUTDOWN] Stopping llama.cpp server started by F.R.I.D.A.Y.")
                self.server_manager.stop()
            else:
                self.logger.info("[SHUTDOWN] Leaving pre-existing llama.cpp server untouched (not owned by F.R.I.D.A.Y).")
