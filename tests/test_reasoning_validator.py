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
