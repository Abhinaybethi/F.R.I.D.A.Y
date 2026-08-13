"""
Test System Intents (stop, cancel, help, repeat).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.intent.router import route
from friday.intent.models import Action


def run():
    print("=" * 60)
    print("  TEST SYSTEM INTENTS")
    print("=" * 60)

    cases = [
        ("stop", Action.SYSTEM_STOP),
        ("shut down", Action.SYSTEM_STOP),
        ("exit", Action.SYSTEM_STOP),
        ("quit", Action.SYSTEM_STOP),
        ("goodbye", Action.SYSTEM_STOP),
        ("cancel", Action.SYSTEM_CANCEL),
        ("never mind", Action.SYSTEM_CANCEL),
        ("nevermind", Action.SYSTEM_CANCEL),
        ("abort", Action.SYSTEM_CANCEL),
        ("help", Action.SYSTEM_HELP),
        ("what can you do", Action.SYSTEM_HELP),
        ("options", Action.SYSTEM_HELP),
        ("commands", Action.SYSTEM_HELP),
        ("repeat", Action.SYSTEM_REPEAT),
        ("say that again", Action.SYSTEM_REPEAT),
        ("pardon", Action.SYSTEM_REPEAT),
        ("what did you say", Action.SYSTEM_REPEAT),
    ]

    passed = 0
    for text, expected_action in cases:
        intent = route(text)
        ok = intent.action == expected_action
        status = "OK  " if ok else "FAIL"
        passed += ok
        print(f"  [{status}] {text!r:<20} -> {intent.action.name}")
        if not ok:
            print(f"         Expected: {expected_action.name}")

    print("=" * 60)
    print(f"  {passed}/{len(cases)} passed")
    print("=" * 60 + "\n")
    return passed == len(cases)


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
