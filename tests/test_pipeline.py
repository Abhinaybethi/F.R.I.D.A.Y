"""
End-to-End Pipeline Test (Dry Run)
==================================
Traces raw STT transcripts through the full architecture:
  Transcript -> Intent -> Target -> Confidence -> Validation -> Tool -> Result

No actual execution is performed.
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.intent.router import route
from friday.safety.validator import validate
from friday.tools import registry

TEST_TRANSCRIPTS = [
    "open chrome",
    "open grove",
    "blood growing",
    "open youtube",
    "search for python tutorials",
    "find my resume",
    "what time is it",
]


def run():
    print("\n" + "=" * 70)
    print("  END-TO-END PIPELINE DRY RUN TEST")
    print("=" * 70)

    for text in TEST_TRANSCRIPTS:
        intent = route(text)
        policy = validate(intent)
        tool_res = registry.execute(intent, dry_run=True, allow_real_execution=False)

        print(f"\nTranscript : {text!r}")
        print(f"  Intent   : {intent.action.name}")
        print(f"  Target   : {intent.target!r}")
        print(f"  Conf     : {intent.confidence:.2f}")
        print(f"  Policy   : {policy.name}")
        print(f"  Result   : {tool_res.get('message')}")

    print("\n" + "=" * 70)
    print("  Pipeline dry run test completed.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run()
