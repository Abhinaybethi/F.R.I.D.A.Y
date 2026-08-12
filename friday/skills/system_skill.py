"""
System info / control skill (time, battery, volume).
"""
import datetime

from friday.system_control import system_info


def current_time() -> str:
    now = datetime.datetime.now().strftime("%I:%M %p")
    return f"It's currently {now}."


def battery_status() -> str:
    pct, plugged = system_info.get_battery()
    if pct is None:
        return "I couldn't read battery information on this device."
    state = "and it's charging" if plugged else "and it's not charging"
    return f"Battery is at {pct} percent {state}."


def set_volume(level: int) -> str:
    ok = system_info.set_volume(level)
    if ok:
        return f"Volume set to {level} percent."
    return "I couldn't change the volume on this system."
