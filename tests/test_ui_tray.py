"""
UNIT TEST — System Tray Status Indicator (Phase 14 P1)
======================================================
Tests SystemTrayIndicator tooltip and icon name formatting rules.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.ui.tray import SystemTrayIndicator
from friday.core.state import ConversationState


def test_system_tray_tooltip_and_icon():
    """get_tray_tooltip() and get_tray_icon_name() format strings correctly."""
    assert SystemTrayIndicator.get_tray_tooltip(ConversationState.LISTENING) == "F.R.I.D.A.Y. - [LISTENING]"
    assert SystemTrayIndicator.get_tray_icon_name(ConversationState.LISTENING) == "icon_listening.ico"
    assert SystemTrayIndicator.get_tray_icon_name(ConversationState.IDLE) == "icon_idle.ico"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--no-header"])
