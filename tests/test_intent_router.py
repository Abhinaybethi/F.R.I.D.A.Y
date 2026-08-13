"""
Intent Router Test
==================
Tests the router against raw strings — including known imperfect STT transcripts.
No actual computer actions are executed here.

Run:
    python tests/test_intent_router.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from friday.intent.router import route
from friday.intent.models import Action
from friday.safety.validator import validate, Policy

# ---------------------------------------------------------------------------
# Test cases: (input_text, expected_action_name, note)
# ---------------------------------------------------------------------------
CASES = [
    # --- Perfect STT ---
    ("open chrome",                  "OPEN_APP",      "exact"),
    ("launch chrome",                "OPEN_APP",      "alias"),
    ("start chrome",                 "OPEN_APP",      "alias"),
    ("close chrome",                 "CLOSE_APP",     "exact"),
    ("quit chrome",                  "CLOSE_APP",     "alias"),
    ("open youtube",                 "OPEN_WEBSITE",  "exact"),
    ("go to youtube",                "OPEN_WEBSITE",  "explicit"),
    ("search for python tutorials",  "SEARCH_WEB",    "exact"),
    ("look up python tutorials",     "SEARCH_WEB",    "alias"),
    ("what time is it",              "GET_TIME",      "exact"),
    ("what time is it now",          "GET_TIME",      "variant"),
    ("what's the time",              "GET_TIME",      "contraction"),
    ("find my resume",               "FIND_FILE",     "exact"),
    ("open my downloads folder",     "OPEN_FOLDER",   "exact"),
    ("open downloads",               "OPEN_FOLDER",   "short"),
    ("open vscode",                  "OPEN_APP",      "exact"),
    ("open vs code",                 "OPEN_APP",      "spaced"),
    ("close youtube",                "UNKNOWN",       "website not app -> UNKNOWN"),
    ("open github",                  "OPEN_WEBSITE",  "exact"),

    # --- Imperfect STT transcripts (known small.en failures) ---
    ("open grove",                   "OPEN_APP",      "STT: open chrome"),
    ("openvscode",                   "OPEN_APP",      "STT: open vs code (compound)"),
    ("what is it now what time is it now", "UNKNOWN",      "STT: double-transcription -> correct reject"),

    # --- Should REJECT ---
    ("blood growing",                "UNKNOWN",       "STT: close chrome hallucination"),
    ("on youtube",                   "UNKNOWN",       "STT: close youtube hallucination"),
    ("million dollars",              "UNKNOWN",       "STT: hallucination"),
]


def _policy_label(policy: Policy) -> str:
    labels = {Policy.SAFE: "SAFE   ", Policy.CONFIRM: "CONFIRM", Policy.REJECT: "REJECT "}
    return labels[policy]


def _section(title: str):
    print(f"\n{'-' * 56}")
    print(f"  {title}")
    print(f"{'-' * 56}")


def run():
    _section("INTENT ROUTER TEST")

    passed = 0
    for text, expected_action, note in CASES:
        intent = route(text)
        policy = validate(intent)

        ok = intent.action.name == expected_action
        status = "OK  " if ok else "FAIL"
        passed += ok

        print(f"\n  [{status}] {text!r}  ({note})")
        print(f"         Action   : {intent.action.name}")
        if intent.target:
            print(f"         Target   : {intent.target!r}")
        print(f"         Conf     : intent={intent.intent_confidence:.2f}  "
              f"target={intent.target_confidence:.2f}  "
              f"overall={intent.confidence:.2f}")
        print(f"         Policy   : {_policy_label(policy)}", end="")
        if intent.requires_confirmation:
            print("  (needs confirmation)", end="")
        print()
        if not ok:
            print(f"         Expected : {expected_action}")

    total = len(CASES)
    _section(f"{passed}/{total} passed")

    return passed == total


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
