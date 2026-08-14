"""
System Tray Status Overlay Manager for F.R.I.D.A.Y. (Phase 14-17).

Provides formatted tray tooltips, icon identifiers, and menu action hooks for system integration.
"""
from typing import Union
from friday.core.state import ConversationState


class SystemTrayIndicator:
    @staticmethod
    def get_tray_tooltip(state: Union[ConversationState, str]) -> str:
        state_str = state.name if isinstance(state, ConversationState) else str(state).upper()
        return f"F.R.I.D.A.Y. - [{state_str}]"

    @staticmethod
    def get_tray_icon_name(state: Union[ConversationState, str]) -> str:
        state_str = state.name if isinstance(state, ConversationState) else str(state).upper()

        if state_str == "LISTENING":
            return "icon_listening.ico"
        elif state_str in ("PROCESSING", "EXECUTING"):
            return "icon_busy.ico"
        elif state_str == "RESPONDING":
            return "icon_speaking.ico"
        elif state_str == "PAUSED":
            return "icon_paused.ico"
        else:
            return "icon_idle.ico"
