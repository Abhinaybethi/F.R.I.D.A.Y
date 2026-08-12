"""
Cross-platform application open/close control.

Spoken app names are first looked up in data/app_aliases.json (editable by
you) to map e.g. "chrome" to the right command/path for your OS. If no
alias is found, Friday falls back to asking the OS to resolve the name
directly - this works for many built-in apps (notepad, calculator, etc.)
out of the box.

Safety: a small list of core OS processes is protected from "close" voice
commands, so a misheard command can't accidentally destabilize your
system.
"""
import json
import os
import platform
import subprocess

import psutil

from friday.utils.logger import get_logger

logger = get_logger(__name__)

ALIASES_PATH = os.path.join("data", "app_aliases.json")

PROTECTED_PROCESSES = {
    "explorer.exe", "finder", "systemuiserver", "loginwindow",
    "csrss.exe", "winlogon.exe", "wininit.exe", "dwm.exe",
    "kernel_task", "windowserver", "services.exe", "smss.exe",
}


def _load_aliases() -> dict:
    if not os.path.exists(ALIASES_PATH):
        return {}
    with open(ALIASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve(spoken_name: str):
    aliases = _load_aliases()
    spoken_name = spoken_name.lower().strip()
    os_key = "windows" if platform.system() == "Windows" else "mac"

    entry = aliases.get(spoken_name)
    if entry and os_key in entry:
        return entry[os_key]
    return None


def open_application(spoken_name: str) -> bool:
    target = _resolve(spoken_name) or spoken_name
    system = platform.system()

    try:
        if system == "Windows":
            os.startfile(target)  # resolves .exe names via the App Paths registry too
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            subprocess.Popen([target])
        return True
    except Exception as e:
        logger.warning("Failed to open '%s' (resolved to '%s'): %s", spoken_name, target, e)
        return False


def close_application(spoken_name: str) -> bool:
    target = (_resolve(spoken_name) or spoken_name).lower()
    target_basename = target.split("/")[-1].split("\\")[-1]
    closed_any = False

    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info["name"] or "").lower()
            if pname in PROTECTED_PROCESSES:
                continue
            if target_basename in pname or target in pname:
                proc.terminate()
                closed_any = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return closed_any
