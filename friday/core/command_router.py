"""
Routes a recognized voice command to the right skill handler.

Uses simple, transparent rule-based matching (keywords / regex) rather than
a black-box intent classifier, so it's easy to extend: add a new `elif`
block here and a matching function in friday/skills/.
"""
import re

from friday.skills import app_skill, file_skill, system_skill, knowledge_skill
from friday.utils.logger import get_logger

logger = get_logger(__name__)


class CommandRouter:
    def __init__(self, tts, llm_client, web_search):
        self.tts = tts
        self.llm_client = llm_client
        self.web_search = web_search

    def route(self, command: str) -> bool:
        """Handles a command. Returns False if the command means "stop/exit"."""
        if not command:
            return True

        command = command.strip().lower()

        # --- exit ---
        if re.search(r"\b(stop|exit|quit|shut down|goodbye)\b", command):
            self.tts.speak("Goodbye.")
            return False

        # --- open a file or folder (checked before generic "open ...") ---
        m = re.search(r"open file (.+)", command) or re.search(r"open folder (.+)", command)
        if m:
            self.tts.speak(file_skill.open_path(m.group(1).strip()))
            return True

        # --- open an application ---
        m = re.search(r"open (?:the )?(.+)", command)
        if m:
            self.tts.speak(app_skill.open_app(m.group(1).strip()))
            return True

        # --- close an application ---
        m = re.search(r"close (?:the )?(.+)", command)
        if m:
            self.tts.speak(app_skill.close_app(m.group(1).strip()))
            return True

        # --- find a file ---
        m = re.search(r"find file (.+)", command) or re.search(r"search for file (.+)", command)
        if m:
            self.tts.speak(file_skill.find_file(m.group(1).strip()))
            return True

        # --- create a folder ---
        m = re.search(r"create (?:a )?folder (?:called |named )?(.+)", command)
        if m:
            self.tts.speak(file_skill.create_folder(m.group(1).strip()))
            return True

        # --- system info ---
        if "what time is it" in command or "current time" in command:
            self.tts.speak(system_skill.current_time())
            return True

        if "battery" in command:
            self.tts.speak(system_skill.battery_status())
            return True

        m = re.search(r"set volume to (\d+)", command)
        if m:
            self.tts.speak(system_skill.set_volume(int(m.group(1))))
            return True

        # --- explicit web search ---
        m = re.search(r"search (?:the web |online )?for (.+)", command)
        if m:
            self.tts.speak(knowledge_skill.web_search_answer(m.group(1).strip(), self.web_search))
            return True

        # --- general knowledge question, or anything unmatched -> LLM brain ---
        self.tts.speak(knowledge_skill.answer_question(command, self.llm_client, self.web_search))
        return True
