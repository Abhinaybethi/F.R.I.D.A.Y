"""
Application control skill: open/close apps by spoken name.
"""
from friday.system_control import app_control


def open_app(spoken_name: str) -> str:
    success = app_control.open_application(spoken_name)
    if success:
        return f"Opening {spoken_name}."
    return (f"I couldn't find an application called {spoken_name}. "
            f"You can add it to data/app_aliases.json.")


def close_app(spoken_name: str) -> str:
    success = app_control.close_application(spoken_name)
    if success:
        return f"Closing {spoken_name}."
    return f"{spoken_name} doesn't seem to be running."
