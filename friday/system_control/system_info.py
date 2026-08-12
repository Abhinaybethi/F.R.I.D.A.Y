"""
Misc system info / control: battery and volume.

Volume control is OS-specific and best-effort:
  - Mac: uses `osascript`, built into macOS - no extra install needed.
  - Windows: uses `pycaw` if installed (see requirements.txt for the
    optional install line). If not installed, Friday will say so instead
    of failing silently.
"""
import platform
import subprocess

import psutil

from friday.utils.logger import get_logger

logger = get_logger(__name__)


def get_battery():
    battery = psutil.sensors_battery()
    if battery is None:
        return None, None
    return round(battery.percent), battery.power_plugged


def set_volume(level: int) -> bool:
    level = max(0, min(100, level))
    system = platform.system()

    try:
        if system == "Darwin":
            subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
            return True

        if system == "Windows":
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(level / 100.0, None)
                return True
            except ImportError:
                logger.warning("pycaw not installed; see requirements.txt for the optional install line.")
                return False
    except Exception as e:
        logger.warning("Failed to set volume: %s", e)

    return False
