import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.reasoning.validator import validate_reasoning_output

def test_validator_valid_intent():
    data = {
        "type": "intent",
        "action": "OPEN_APP",
        "target": "chrome",
        "confidence": 0.9
    }
    assert validate_reasoning_output(data) == data

def test_validator_valid_plan():
    data = {
        "type": "plan",
        "steps": [
            {"action": "OPEN_APP", "target": "chrome"}
        ],
        "confidence": 0.9
    }
    assert validate_reasoning_output(data) == data

def test_validator_unknown_action():
    data = {
        "type": "intent",
        "action": "DELETE_SYSTEM",
        "target": "chrome",
        "confidence": 0.9
    }
    assert validate_reasoning_output(data) == {"type": "unknown"}

def test_validator_shell_injection():
    data = {
        "type": "intent",
        "action": "OPEN_APP",
        "target": "chrome",
        "arguments": {
            "command": "rm -rf"
        },
        "confidence": 0.9
    }
    assert validate_reasoning_output(data) == {"type": "unknown"}

def test_validator_bad_confidence():
    data = {
        "type": "intent",
        "action": "OPEN_APP",
        "target": "chrome",
        "confidence": 1.5
    }
    assert validate_reasoning_output(data) == {"type": "unknown"}
    
    data["confidence"] = -1
    assert validate_reasoning_output(data) == {"type": "unknown"}
    
def test_validator_plan_limits():
    data = {
        "type": "plan",
        "steps": [
            {"action": "OPEN_APP", "target": "chrome"} for _ in range(6)
        ],
        "confidence": 0.9
    }
    assert validate_reasoning_output(data) == {"type": "unknown"}


def test_validator_safe_action_allowlist():
    """Reasoner may only request actions from the safe allowlist (ISSUE 5)."""
    for action in ("OPEN_APP", "OPEN_WEBSITE", "READ_WEBSITE", "SEARCH_WEB",
                   "PLAY_VIDEO", "OPEN_FILE", "OPEN_FOLDER", "FIND_FILE",
                   "GET_TIME", "GREETING"):
        data = {"type": "intent", "action": action, "target": "test",
                "confidence": 0.9}
        assert validate_reasoning_output(data) == data, action


def test_validator_rejects_unsafe_actions():
    """Destructive / state-changing actions are never model-requestable."""
    for action in ("CLOSE_APP", "FORGET", "RECALL", "REMEMBER", "SYSTEM_STOP",
                   "SET_VOLUME", "MUTE_AUDIO", "UNMUTE_AUDIO", "PAUSE_MEDIA",
                   "MINIMIZE_APP", "MAXIMIZE_APP", "TAKE_SCREENSHOT"):
        data = {"type": "intent", "action": action, "target": "test",
                "confidence": 0.9}
        assert validate_reasoning_output(data) == {"type": "unknown"}, action


def test_validator_unsafe_action_in_plan():
    """A plan containing even one unsafe step is rejected wholesale."""
    data = {
        "type": "plan",
        "steps": [
            {"action": "OPEN_APP", "target": "chrome"},
            {"action": "CLOSE_APP", "target": "chrome"},
        ],
        "confidence": 0.9
    }
    assert validate_reasoning_output(data) == {"type": "unknown"}
