"""
Test Conversation State Machine & Transitions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from friday.core.state import ConversationState, StateMachine
from friday.core.conversation import ConversationManager


def run():
    print("=" * 60)
    print("  TEST CONVERSATION STATE MACHINE")
    print("=" * 60)

    sm = StateMachine(ConversationState.IDLE)
    passed = 0
    total = 0

    def check_transition(from_state, to_state, expect_valid=True):
        nonlocal passed, total
        total += 1
        sm._state = from_state
        try:
            sm.transition_to(to_state)
            ok = expect_valid and (sm.current_state == to_state)
        except ValueError:
            ok = not expect_valid
        status = "OK  " if ok else "FAIL"
        passed += ok
        valid_str = "valid" if expect_valid else "invalid"
        print(f"  [{status}] {from_state.name} -> {to_state.name} ({valid_str})")

    check_transition(ConversationState.IDLE, ConversationState.LISTENING, True)
    check_transition(ConversationState.LISTENING, ConversationState.PROCESSING, True)
    check_transition(ConversationState.PROCESSING, ConversationState.WAITING_FOR_CONFIRMATION, True)
    check_transition(ConversationState.WAITING_FOR_CONFIRMATION, ConversationState.EXECUTING, True)
    check_transition(ConversationState.EXECUTING, ConversationState.RESPONDING, True)
    check_transition(ConversationState.RESPONDING, ConversationState.LISTENING, True)

    # Cancel path
    check_transition(ConversationState.WAITING_FOR_CONFIRMATION, ConversationState.RESPONDING, True)

    # Stop path from any state
    check_transition(ConversationState.PROCESSING, ConversationState.STOPPING, True)
    check_transition(ConversationState.WAITING_FOR_CONFIRMATION, ConversationState.STOPPING, True)
    check_transition(ConversationState.STOPPING, ConversationState.IDLE, True)

    # Invalid transition check
    check_transition(ConversationState.IDLE, ConversationState.EXECUTING, False)

    # ConversationManager multi-turn context flow test
    cm = ConversationManager(dry_run=True, allow_real_execution=False)
    cm.start_session()

    # Turn 1: "open groom" -> WAITING_FOR_CONFIRMATION
    resp1, _ = cm.handle_transcript("open groom")
    total += 1
    t1_ok = cm.state == ConversationState.WAITING_FOR_CONFIRMATION
    passed += t1_ok
    print(f"\n  [{'OK  ' if t1_ok else 'FAIL'}] Turn 1 'open groom' -> state={cm.state.name}")

    # Turn 2: "no" -> CANCELLED -> LISTENING
    resp2, _ = cm.handle_transcript("no")
    total += 1
    t2_ok = (cm.state == ConversationState.LISTENING) and (resp2 == "Cancelled.")
    passed += t2_ok
    print(f"  [{'OK  ' if t2_ok else 'FAIL'}] Turn 2 'no' -> state={cm.state.name} | resp={resp2!r}")

    # Turn 3: "open groom" -> WAITING_FOR_CONFIRMATION
    resp3, _ = cm.handle_transcript("open groom")

    # Turn 4: "cancel" -> CANCELLED -> LISTENING
    resp4, _ = cm.handle_transcript("cancel")
    total += 1
    t4_ok = (cm.state == ConversationState.LISTENING) and (resp4 == "Cancelled.")
    passed += t4_ok
    print(f"  [{'OK  ' if t4_ok else 'FAIL'}] Turn 4 'cancel' -> state={cm.state.name} | resp={resp4!r}")

    # Turn 5: "stop" -> STOPPING -> False
    resp5, keep_running = cm.handle_transcript("stop")
    total += 1
    t5_ok = (not keep_running) and (cm.state == ConversationState.STOPPING)
    passed += t5_ok
    print(f"  [{'OK  ' if t5_ok else 'FAIL'}] Turn 5 'stop' -> state={cm.state.name} | keep_running={keep_running}")

    print("=" * 60)
    print(f"  {passed}/{total} passed")
    print("=" * 60 + "\n")
    return passed == total


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
