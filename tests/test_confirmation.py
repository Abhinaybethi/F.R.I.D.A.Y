"""
Test Stateful Confirmation Engine and Response Parser (10 Scenarios).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.safety.confirmation import parse_confirmation_response, format_confirmation_prompt
from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState
from friday.intent.models import Action, Intent


def run():
    print("=" * 60)
    print("  TEST CONFIRMATION ENGINE (10 SCENARIOS)")
    print("=" * 60)

    passed = 0
    total = 0

    def check(name: str, condition: bool, details: str = ""):
        nonlocal passed, total
        total += 1
        status = "OK  " if condition else "FAIL"
        passed += int(condition)
        msg = f"  [{status}] Test {total}: {name}"
        if details:
            msg += f" -> {details}"
        print(msg)

    # Parser sanity check
    check("parse_confirmation_response('yes.')", parse_confirmation_response("yes.") is True)
    check("parse_confirmation_response('yeah!')", parse_confirmation_response("yeah!") is True)
    check("parse_confirmation_response('nope.')", parse_confirmation_response("nope.") is False)

    # ------------------------------------------------------------------
    # TEST 1: "open groom" while LISTENING
    # ------------------------------------------------------------------
    cm1 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm1.start_session()
    resp1, _ = cm1.handle_transcript("open groom")
    check(
        "open groom -> WAITING_FOR_CONFIRMATION",
        cm1.state == ConversationState.WAITING_FOR_CONFIRMATION and cm1.context.pending_intent is not None,
        f"Prompt: {resp1!r}",
    )

    # ------------------------------------------------------------------
    # TEST 2: "yes" while WAITING_FOR_CONFIRMATION -> CONFIRMED & execute
    # ------------------------------------------------------------------
    resp2, _ = cm1.handle_transcript("yes")
    check(
        "yes -> CONFIRMED, execute pending action, reset state to LISTENING",
        cm1.state == ConversationState.LISTENING
        and cm1.context.pending_intent is None
        and "[DRY RUN] Would open Chrome." in resp2,
        f"Response: {resp2!r}",
    )

    # ------------------------------------------------------------------
    # TEST 3: "no" while WAITING_FOR_CONFIRMATION -> Cancelled
    # ------------------------------------------------------------------
    cm3 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm3.start_session()
    cm3.handle_transcript("open groom")
    resp3, _ = cm3.handle_transcript("no")
    check(
        "no -> Cancelled",
        cm3.state == ConversationState.LISTENING and cm3.context.pending_intent is None and resp3 == "Cancelled.",
        f"Response: {resp3!r}",
    )

    # ------------------------------------------------------------------
    # TEST 4: "cancel" while WAITING_FOR_CONFIRMATION -> Cancelled
    # ------------------------------------------------------------------
    cm4 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm4.start_session()
    cm4.handle_transcript("open groom")
    resp4, _ = cm4.handle_transcript("cancel")
    check(
        "cancel -> Cancelled",
        cm4.state == ConversationState.LISTENING and cm4.context.pending_intent is None and resp4 == "Cancelled.",
        f"Response: {resp4!r}",
    )

    # ------------------------------------------------------------------
    # TEST 5: Unrelated command "open youtube" while WAITING_FOR_CONFIRMATION
    # ------------------------------------------------------------------
    cm5 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm5.start_session()
    cm5.handle_transcript("open groom")
    resp5, _ = cm5.handle_transcript("open youtube")
    check(
        "open youtube while confirmation pending -> retain pending intent & state",
        cm5.state == ConversationState.WAITING_FOR_CONFIRMATION
        and cm5.context.pending_intent is not None
        and "pending confirmation" in resp5,
        f"Response: {resp5!r}",
    )

    # ------------------------------------------------------------------
    # TEST 6: Ambiguous / unknown response while WAITING_FOR_CONFIRMATION
    # ------------------------------------------------------------------
    cm6 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm6.start_session()
    cm6.handle_transcript("open groom")
    resp6, _ = cm6.handle_transcript("random nonsense")
    check(
        "random nonsense while confirmation pending -> retain pending intent & prompt yes/no/cancel",
        cm6.state == ConversationState.WAITING_FOR_CONFIRMATION
        and cm6.context.pending_intent is not None
        and "Please say yes, no, or cancel" in resp6,
        f"Response: {resp6!r}",
    )

    # ------------------------------------------------------------------
    # TEST 7: "stop" while WAITING_FOR_CONFIRMATION -> STOPPING & exit
    # ------------------------------------------------------------------
    cm7 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm7.start_session()
    cm7.handle_transcript("open groom")
    resp7, keep_running7 = cm7.handle_transcript("stop")
    check(
        "stop while confirmation pending -> STOPPING, clear pending, exit cleanly",
        cm7.state == ConversationState.STOPPING
        and cm7.context.pending_intent is None
        and keep_running7 is False
        and resp7 == "Goodbye.",
        f"Response: {resp7!r}",
    )

    # ------------------------------------------------------------------
    # TEST 8: "yes" while LISTENING (unprompted) -> UNKNOWN / REJECT
    # ------------------------------------------------------------------
    cm8 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm8.start_session()
    resp8, _ = cm8.handle_transcript("yes")
    check(
        "yes while LISTENING (unprompted) -> UNKNOWN / REJECT",
        cm8.state == ConversationState.LISTENING and resp8 == "I didn't understand that.",
        f"Response: {resp8!r}",
    )

    # ------------------------------------------------------------------
    # TEST 9: "yeah" while WAITING_FOR_CONFIRMATION -> CONFIRMED
    # ------------------------------------------------------------------
    cm9 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm9.start_session()
    cm9.handle_transcript("open groom")
    resp9, _ = cm9.handle_transcript("yeah")
    check(
        "yeah -> CONFIRMED",
        cm9.state == ConversationState.LISTENING and "[DRY RUN] Would open Chrome." in resp9,
        f"Response: {resp9!r}",
    )

    # ------------------------------------------------------------------
    # TEST 10: "nope" while WAITING_FOR_CONFIRMATION -> Cancelled
    # ------------------------------------------------------------------
    cm10 = ConversationManager(dry_run=True, allow_real_execution=False)
    cm10.start_session()
    cm10.handle_transcript("open groom")
    resp10, _ = cm10.handle_transcript("nope")
    check(
        "nope -> Cancelled",
        cm10.state == ConversationState.LISTENING and resp10 == "Cancelled.",
        f"Response: {resp10!r}",
    )

    print("=" * 60)
    print(f"  {passed}/{total} passed")
    print("=" * 60 + "\n")
    return passed == total


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
