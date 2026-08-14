"""System tools — date/time, no internet required."""
from datetime import datetime


def get_time() -> dict:
    """Return the current local time."""
    now = datetime.now()
    try:
        readable = now.strftime("%#I:%M %p")
    except Exception:
        readable = now.strftime("%I:%M %p").lstrip("0")
    return {
        "success": True,
        "time":    now.strftime("%H:%M:%S"),
        "message": f"It's {readable}.",
        "spoken_message": f"It's {readable}.",
    }
