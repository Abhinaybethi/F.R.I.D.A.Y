"""
Phase 21 Gate & Integration Test Suite.

Verifies:
1. FORGET confirmation state machine invariants & prompt formatting.
2. Memory deduplication (case, whitespace, duplicate prevention, distinct preservation).
3. Web search workflow (structured results, short-term context isolation).
4. System safety invariant assertions (dry_run=True, allow_real_execution=False).
"""
import sqlite3
from contextlib import closing
import pytest
from unittest.mock import patch, MagicMock

from friday.core.conversation import ConversationManager
from friday.core.state import ConversationState
from friday.intent.models import Action, Intent
from friday.safety.validator import validate, Policy
from friday.safety.confirmation import format_confirmation_prompt
from friday.tools.memory import remember, forget, recall, _init_db, _get_db_path


@pytest.fixture(autouse=True)
def setup_db():
    _init_db()
    with closing(sqlite3.connect(_get_db_path())) as conn:
        with conn:
            conn.execute("DELETE FROM memories")


class TestForgetConfirmationGate:
    def test_forget_policy_is_confirm(self):
        intent = Intent(action=Action.FORGET, target="the sky is blue", confidence=0.95, intent_confidence=0.95, target_confidence=0.95)
        policy = validate(intent)
        assert policy == Policy.CONFIRM

    def test_forget_prompt_contains_exact_target(self):
        intent = Intent(action=Action.FORGET, target="the sky is blue")
        prompt = format_confirmation_prompt(intent)
        assert prompt == "Do you want me to forget 'the sky is blue'?"

    def test_forget_flow_yes_deletes_memory(self):
        # Insert a memory first
        remember("favorite color is blue", dry_run=False)
        rec = recall("favorite color")
        assert rec["success"] is True

        cm = ConversationManager(dry_run=False, allow_real_execution=True)
        cm.start_session()

        # 1. FORGET request
        resp1, cont1 = cm.handle_transcript("forget favorite color is blue")
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION
        assert "forget 'favorite color is blue'" in resp1

        # 2. Confirm YES
        resp2, cont2 = cm.handle_transcript("yes")
        assert cm.state == ConversationState.LISTENING
        assert "forgotten" in resp2.lower()

        # 3. Verify deleted
        rec2 = recall("favorite color")
        assert rec2["success"] is False

    def test_forget_flow_no_cancels_without_deletion(self):
        remember("cat name is Luna", dry_run=False)
        cm = ConversationManager(dry_run=False, allow_real_execution=False)
        cm.start_session()

        # FORGET request
        cm.handle_transcript("forget cat name is Luna")
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

        # Decline NO
        resp, cont = cm.handle_transcript("no")
        assert "Cancelled" in resp
        assert cm.state == ConversationState.LISTENING

        # Verify memory remains
        rec = recall("cat name")
        assert rec["success"] is True

    def test_forget_flow_stop_cancels_without_deletion(self):
        remember("dog name is Max", dry_run=False)
        cm = ConversationManager(dry_run=False, allow_real_execution=False)
        cm.start_session()

        cm.handle_transcript("forget dog name is Max")
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

        # Say STOP
        resp, cont = cm.handle_transcript("stop")
        assert cont is False
        assert cm.state == ConversationState.STOPPING

        # Memory remains intact
        rec = recall("dog name")
        assert rec["success"] is True

    def test_yes_outside_waiting_state_deletes_nothing(self):
        remember("project path is code", dry_run=False)
        cm = ConversationManager(dry_run=False, allow_real_execution=False)
        cm.start_session()

        # Unsolicited "yes" utterance in LISTENING state
        resp, cont = cm.handle_transcript("yes")
        assert cm.state != ConversationState.WAITING_FOR_CONFIRMATION

        rec = recall("project path")
        assert rec["success"] is True

    def test_unknown_confirmation_response_blocks_deletion(self):
        remember("secret code is 1234", dry_run=False)
        cm = ConversationManager(dry_run=False, allow_real_execution=False)
        cm.start_session()

        cm.handle_transcript("forget secret code is 1234")
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

        # Random utterance
        resp, cont = cm.handle_transcript("what is the weather outside")
        assert "say yes, no, or cancel" in resp.lower()
        assert cm.state == ConversationState.WAITING_FOR_CONFIRMATION

        rec = recall("secret code")
        assert rec["success"] is True


class TestMemoryDeduplication:
    def test_duplicate_memory_prevented(self):
        res1 = remember("the ocean is deep", dry_run=False)
        assert res1["success"] is True

        # Duplicate call with varying case & whitespace
        res2 = remember("  The OCEAN is   DEEP ", dry_run=False)
        assert res2["success"] is True
        assert res2.get("duplicate") is True
        assert "already" in res2["spoken_message"].lower()

    def test_distinct_key_values_preserved(self):
        res1 = remember("favorite_food: pizza", dry_run=False)
        assert res1["success"] is True

        res2 = remember("favorite_food: sushi", dry_run=False)
        assert res2["success"] is True
        assert res2.get("duplicate") is not True


class TestWebSearchWorkflow:
    def test_search_results_in_short_term_context(self):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        resp, cont = cm.handle_transcript("search for python tutorials")
        assert cm.context.last_tool_result is not None
        assert "results" in cm.context.last_tool_result
        assert len(cm.context.last_tool_result["results"]) > 0

    def test_search_content_not_automatically_persisted_to_long_term_memory(self):
        cm = ConversationManager(dry_run=True, allow_real_execution=False)
        cm.start_session()

        cm.handle_transcript("search for python tutorials")

        # Recall should find no SQLite memory entry created automatically
        rec = recall("python tutorials")
        assert rec["success"] is False


class TestPhase21SafetyDefaultsGate:
    def test_safety_defaults(self):
        cm = ConversationManager()
        assert cm.dry_run is True
        assert cm.allow_real_execution is False
