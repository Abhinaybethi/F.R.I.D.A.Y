"""
Test Command Understanding & Robust Transcript Interpretation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.intent.router import route
from friday.intent.models import Action
from friday.safety.validator import validate, Policy


def run():
    print("=" * 60)
    print("  TEST COMMAND UNDERSTANDING & ROBUSTNESS")
    print("=" * 60)

    cases = [
        # Normal safe commands
        ("open chrome", Action.OPEN_APP, "chrome", Policy.SAFE),
        ("open youtube", Action.OPEN_WEBSITE, "youtube", Policy.SAFE),
        ("search for python tutorials", Action.SEARCH_WEB, "python tutorials", Policy.SAFE),
        ("what time is it", Action.GET_TIME, "", Policy.SAFE),
        ("open downloads", Action.OPEN_FOLDER, "download", Policy.SAFE),

        # Phonetic candidates -> CONFIRM
        ("open groom", Action.OPEN_APP, "chrome", Policy.CONFIRM),
        ("open grove", Action.OPEN_APP, "chrome", Policy.CONFIRM),
        ("open groan", Action.OPEN_APP, "chrome", Policy.CONFIRM),
        ("openvscode", Action.OPEN_APP, "vscode", Policy.CONFIRM),

        # Unrelated / hallucinated speech -> UNKNOWN -> REJECT
        ("blood growing", Action.UNKNOWN, "", Policy.REJECT),
        ("million dollars", Action.UNKNOWN, "", Policy.REJECT),
        ("slowest youtube", Action.UNKNOWN, "", Policy.REJECT),
        ("i hope and you do", Action.UNKNOWN, "", Policy.REJECT),
        ("and grown", Action.UNKNOWN, "", Policy.REJECT),
        ("and it was chrome", Action.UNKNOWN, "", Policy.REJECT),
    ]

    passed = 0
    total = len(cases)

    for text, expected_action, expected_target, expected_policy in cases:
        intent = route(text)
        policy = validate(intent)

        ok_action = intent.action == expected_action
        ok_target = (not expected_target) or (intent.target == expected_target)
        ok_policy = policy == expected_policy

        ok = ok_action and ok_target and ok_policy
        status = "OK  " if ok else "FAIL"
        passed += ok

        print(f"  [{status}] {text!r:<30} -> {intent.action.name:<12} target={intent.target!r:<10} policy={policy.name}")
        if not ok:
            print(f"         Expected: action={expected_action.name} target={expected_target!r} policy={expected_policy.name}")

    print("=" * 60)
    print(f"  {passed}/{total} passed")
    print("=" * 60 + "\n")
    return passed == total


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
