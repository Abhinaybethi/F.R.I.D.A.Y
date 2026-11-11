"""
UNIT TEST — Asynchronous turn safety.

The voice pipeline has no asynchronous transcription-with-turn-IDs: STT runs
synchronously per turn and stale *audio* is handled by AudioInput.drain().
The staleness hazards that DO exist here, and are locked in deterministically:

  * stale queued mic chunks are discarded between utterances (drain)
  * a transcript processed after session expiry must not inherit pre-expiry
    topic/entity context (clear_ephemeral on expiry)
  * per-turn history pairing stays consistent regardless of the order in
    which callers deliver utterances
  * barge-in capture is consumed exactly once (take_barge_in_audio reset)

No hardware, no sleeps beyond bounded queue timeouts, no network.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pytest

from friday.core.conversation import ConversationManager
from friday.reasoning.interface import Reasoner
from friday.voice import audio_input as audio_input_module


class RecordingReasoner(Reasoner):
    def __init__(self):
        self.seen = []

    def is_available(self):
        return True

    def health(self):
        return "mock"

    def request(
        self, transcript, context, mode="action", retrieval_context: str = ""
    ) -> dict:
        self.seen.append(transcript)
        return {"type": "response", "text": "Understood."}

    def close(self):
        pass


def _cm(active_session: bool = True):
    reasoner = RecordingReasoner()
    cm = ConversationManager(
        dry_run=True, allow_real_execution=False, reasoner=reasoner
    )
    cm.start_session()
    if active_session:
        # The voice pipeline (friday/core/assistant.py) owns session.start();
        # manager-only callers must activate it explicitly for expiry logic.
        cm.session.start()
    return cm, reasoner


# ---------------------------------------------------------------------------
# Stale audio chunk draining
# ---------------------------------------------------------------------------


def _fake_audio(n_chunks: int):
    """AudioInput without hardware: chunks pushed straight into the queue."""
    audio = audio_input_module.AudioInput.__new__(audio_input_module.AudioInput)
    import queue as _q

    audio.sample_rate = 16000
    audio.chunk_size = 512
    audio.queue = _q.Queue()
    audio.stream = None
    for i in range(n_chunks):
        audio.queue.put(np.zeros(512, dtype=np.float32) + i)
    return audio


def test_drain_discards_all_stale_chunks():
    audio = _fake_audio(7)
    audio.drain()
    assert audio.queue.empty()


def test_drain_on_empty_queue_is_safe():
    audio = _fake_audio(0)
    audio.drain()  # must not raise
    assert audio.queue.empty()


def test_chunks_queued_after_drain_survive():
    audio = _fake_audio(3)
    audio.drain()
    audio.queue.put(np.ones(512, dtype=np.float32))
    assert audio.queue.qsize() == 1


# ---------------------------------------------------------------------------
# Transcript arriving after its turn went stale (session expired)
# ---------------------------------------------------------------------------


def test_late_transcript_after_expiry_does_not_inherit_stale_topic():
    cm, _reasoner = _cm()

    # Establish a topic the normal way.
    resp1, _ = cm.handle_transcript("What is the RAG pipeline?")
    assert resp1
    stale_topic = cm.context.active_topic
    assert stale_topic, "precondition: topic tracked before expiry"

    # Simulate the session going stale while an old transcription is pending:
    # back-date the inactivity timer past the timeout (deterministic clock).
    cm.session.last_interaction_at -= cm.session.timeout_seconds + 1

    # The late segment finally arrives.
    resp2, keep = cm.handle_transcript("What about it?")
    assert keep is True
    assert resp2  # a clarification is a normal response

    # The expired session's TOPIC can never ground the late segment: expiry
    # cleared it before the late turn was routed. The session itself stays
    # inactive after expiry — re-activation is the wake-word layer's job
    # (assistant.py); touch() only refreshes the timer for when that happens.
    assert cm.context.active_topic == ""
    assert not cm.session.is_active()


def test_expiry_retains_history_by_design_recorded():
    """Recorded limitation: cross-turn history survives session expiry.

    ``clear_ephemeral`` deliberately keeps some context across sessions
    (docstring: search/media "optionally-reusable"); conversation history is
    also retained, so an anaphoric turn right after expiry can still resolve
    from pre-expiry turns. Topic-anchored grounding is cleared (see the test
    above); if history should also expire, ``clear_ephemeral`` must be
    changed consciously and this test updated with it.
    """
    cm, _reasoner = _cm()
    cm.handle_transcript("What is the RAG pipeline?")
    cm.session.last_interaction_at -= cm.session.timeout_seconds + 1
    cm.handle_transcript("What about it?")

    assert cm.context.active_topic == ""
    assert cm.context.history, "history is retained across expiry (recorded)"


def test_late_transcript_within_active_session_still_resolves():
    cm, reasoner = _cm()
    cm.handle_transcript("What is the RAG pipeline?")
    resp2, _ = cm.handle_transcript("What about it?")
    assert resp2
    # Active session: the follow-up WAS grounded on the live topic.
    assert "rag pipeline" in reasoner.seen[-1].lower()


def test_new_turn_resets_pending_resolution_state():
    cm, _ = _cm()
    cm.handle_transcript("What is the RAG pipeline?")
    cm.handle_transcript("What is the Eiffel Tower?")
    # The second turn must have replaced the first turn's resolution state.
    assert cm.context.last_transcript == "What is the Eiffel Tower?"
    assert (
        "eiffel" in (cm.context.last_resolved_query or "").lower()
        or cm.context.last_resolution_status == "not_needed"
    )


# ---------------------------------------------------------------------------
# Out-of-order delivery — per-turn pairing integrity
# ---------------------------------------------------------------------------


def test_history_pairs_each_transcript_with_its_own_response():
    """Two utterances delivered in reverse order still pair correctly."""
    cm, _ = _cm()
    answers = iter(["ANSWER_ALPHA", "ANSWER_BETA"])

    class OrderedReasoner(RecordingReasoner):
        def request(
            self, transcript, context, mode="action", retrieval_context: str = ""
        ) -> dict:
            self.seen.append(transcript)
            return {"type": "response", "text": next(answers)}

    reasoner = OrderedReasoner()
    cm.reasoner = reasoner

    # Deliver B's transcript BEFORE A's (caller-side reordering), but each
    # handle_transcript call is one complete turn: the pairing of transcript
    # to response inside history must never cross.
    resp_b, _ = cm.handle_transcript("What is the Eiffel Tower?")
    resp_a, _ = cm.handle_transcript("What is the RAG pipeline?")

    assert resp_b == "ANSWER_ALPHA"
    assert resp_a == "ANSWER_BETA"

    last = cm.context.history[-1]
    prior = cm.context.history[-2]
    assert last["transcript"] == "What is the RAG pipeline?"
    assert last["response"] == "ANSWER_BETA"
    assert prior["transcript"] == "What is the Eiffel Tower?"
    assert prior["response"] == "ANSWER_ALPHA"


def test_stale_segment_quality_rejection_does_not_record_a_turn():
    """Noise rejected by the quality gate must not enter history or reach the model."""
    cm, reasoner = _cm()
    cm.handle_transcript("What is the RAG pipeline?")
    before = len(cm.context.history)
    resp, keep = cm.handle_transcript("no jes")
    assert keep is True
    assert resp  # clarification, not silence
    assert len(cm.context.history) == before + 1  # clarification is a normal turn...
    # ...but the noisy fragment never reached the reasoner.
    assert all("no jes" not in s.lower() for s in reasoner.seen)


# ---------------------------------------------------------------------------
# Barge-in capture consumption
# ---------------------------------------------------------------------------


def test_barge_in_capture_consumed_exactly_once():
    from friday.voice.async_session import AsyncVoiceSessionManager

    class _FakeTTS:
        def is_speaking(self):
            return False

        def stop(self):
            pass

    class _FakeSM:
        audio = _fake_audio(0)

        class vad:
            @staticmethod
            def is_speech(_chunk):
                return False

    mgr = AsyncVoiceSessionManager(_FakeSM(), _FakeTTS())
    mgr._barge_in_chunks = [b"c1", b"c2"]
    mgr._barge_in_triggered = True

    first = mgr.take_barge_in_audio()
    second = mgr.take_barge_in_audio()
    assert first == [b"c1", b"c2"]
    assert second == []
    assert mgr.is_barge_in_triggered() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-header"])
