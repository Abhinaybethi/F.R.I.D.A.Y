"""
File and folder control skill.
"""
from friday.system_control import file_control


def open_path(spoken_path: str) -> str:
    found = file_control.open_path(spoken_path)
    if found:
        return f"Opening {spoken_path}."
    return f"I couldn't find {spoken_path}."


def find_file(name: str) -> str:
    matches = file_control.find_file(name)
    if not matches:
        return f"I couldn't find any file matching {name}."
    if len(matches) == 1:
        return f"Found it: {matches[0]}"
    return f"I found {len(matches)} matches. The first one is {matches[0]}."


def create_folder(name: str) -> str:
    path = file_control.create_folder(name)
    return f"Created folder {name} at {path}."
