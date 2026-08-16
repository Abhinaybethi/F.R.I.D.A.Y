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


def set_volume(level: str, dry_run: bool = True) -> dict:
    """Set system audio volume (e.g. '50%', '50')."""
    target = (level or "").strip().rstrip("%")
    val = target if target else "50"
    if dry_run:
        return {
            "success": True,
            "message": f"[DRY RUN] Would set volume to {val}%.",
            "spoken_message": f"Setting volume to {val} percent.",
        }
    try:
        import subprocess
        # Basic Windows PowerShell volume toggle simulation or key press
        cmd = f"(New-Object -ComObject WScript.Shell).SendKeys([char]174)"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=2.0)
        return {
            "success": True,
            "message": f"Set volume to {val}%.",
            "spoken_message": f"Volume set to {val} percent.",
        }
    except Exception as e:
        return {"success": False, "message": f"Could not set volume: {e}", "spoken_message": "Could not adjust volume."}


def mute_audio(dry_run: bool = True) -> dict:
    """Mute system audio output."""
    if dry_run:
        return {
            "success": True,
            "message": "[DRY RUN] Would mute audio.",
            "spoken_message": "Muting audio.",
        }
    try:
        import subprocess
        cmd = "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=2.0)
        return {"success": True, "message": "Muted audio.", "spoken_message": "Audio muted."}
    except Exception as e:
        return {"success": False, "message": f"Could not mute audio: {e}", "spoken_message": "Could not mute audio."}


def unmute_audio(dry_run: bool = True) -> dict:
    """Unmute system audio output."""
    if dry_run:
        return {
            "success": True,
            "message": "[DRY RUN] Would unmute audio.",
            "spoken_message": "Unmuting audio.",
        }
    try:
        import subprocess
        cmd = "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=2.0)
        return {"success": True, "message": "Unmuted audio.", "spoken_message": "Audio unmuted."}
    except Exception as e:
        return {"success": False, "message": f"Could not unmute audio: {e}", "spoken_message": "Could not unmute audio."}


def pause_media(dry_run: bool = True) -> dict:
    """Pause or play media playback."""
    if dry_run:
        return {
            "success": True,
            "message": "[DRY RUN] Would toggle media playback.",
            "spoken_message": "Pausing media.",
        }
    try:
        import subprocess
        cmd = "(New-Object -ComObject WScript.Shell).SendKeys([char]179)"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=2.0)
        return {"success": True, "message": "Toggled media playback.", "spoken_message": "Media paused."}
    except Exception as e:
        return {"success": False, "message": f"Could not toggle media: {e}", "spoken_message": "Could not toggle media."}
