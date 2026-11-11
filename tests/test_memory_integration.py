"""Integration tests: conversation loop <-> persistent memory."""
from __future__ import annotations

from friday.core.conversation import ConversationManager
from friday.memory.service import MemoryService

_ALL_PERMISSIONS = {
    "open_app": True,
    "close_app": True,
    "open_website": True,
    "search_web": True,
    "get_time": True,
    "find_file": True,
    "open_file": True,
    "open_folder": True,
}


def _memory(tmp_path, **overrides):
    config = {
        "db_path": str(tmp_path / "memory.db"),
        "vector_enabled": False,
        "summaries_enabled": True,
        "dedupe_window_seconds": 0,
    }
    config.update(overrides)
    return MemoryService.from_config(config, source="voice", vector_worker=False)


def _manager(memory):
    return ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        permissions=_ALL_PERMISSIONS,
        memory_service=memory,
    )


def test_conversation_records_a_completed_turn(tmp_path):
    memory = _memory(tmp_path)
    cm = _manager(memory)
    cm.start_session()
    sid = memory.current_session_id
    assert sid

    response, keep = cm.handle_transcript("open chrome")
    assert keep is True
    assert "chrome" in response.lower()
    memory.flush_vectors()

    payload = memory.get_session(sid)
    assert payload["session"]["turn_count"] == 1
    turn = payload["turns"][0]
    assert turn["raw_text"] == "open chrome"
    assert turn["response_text"] == response
    assert turn["intent_action"] == "OPEN_APP"
    memory.close()


def test_supplied_turn_id_makes_retries_idempotent(tmp_path):
    memory = _memory(tmp_path)
    cm = _manager(memory)
    cm.start_session()

    cm.handle_transcript("what time is it", turn_id="turn-fixed")
    cm.handle_transcript("what time is it", turn_id="turn-fixed")
    assert memory.store.count("messages") == 1
    memory.close()


def test_explicit_session_end_is_not_recorded_as_a_turn(tmp_path):
    memory = _memory(tmp_path)
    cm = _manager(memory)
    cm.start_session()

    response, _ = cm.handle_transcript("goodbye")
    assert response
    assert memory.store.count("messages") == 0
    assert memory.current_session_id is None
    memory.close()


def test_stop_session_closes_the_memory_session(tmp_path):
    memory = _memory(tmp_path)
    cm = _manager(memory)
    cm.start_session()
    assert memory.current_session_id is not None

    cm.stop_session()
    assert memory.current_session_id is None
    memory.close()


def test_memory_failures_never_break_the_response(tmp_path):
    class ExplodingMemory:
        enabled = True

        def start_session(self, *args, **kwargs):
            raise RuntimeError("memory down")

        def end_session(self, *args, **kwargs):
            raise RuntimeError("memory down")

        def record_turn(self, *args, **kwargs):
            raise RuntimeError("memory down")

    cm = _manager(ExplodingMemory())
    cm.start_session()  # must not raise
    response, keep = cm.handle_transcript("what time is it")
    assert keep is True
    assert ":" in response or "AM" in response or "PM" in response
    cm.stop_session()  # must not raise


def test_manager_without_memory_still_works():
    cm = ConversationManager(
        dry_run=True, allow_real_execution=False, permissions=_ALL_PERMISSIONS
    )
    cm.start_session()
    response, keep = cm.handle_transcript("what time is it")
    assert keep is True
    assert response
    cm.stop_session()
