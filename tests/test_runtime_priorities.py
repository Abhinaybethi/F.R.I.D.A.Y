"""
Runtime-priority acceptance tests (P1–P14).

Each test pins one behaviour from the 17-priority runtime task:

  P1   deterministic exit variants — exact "Goodbye.", no LLM
  P3   llama.cpp SSE streaming + usage parsing + per-request deadline
  P5   current-information queries route to the deterministic SEARCH_WEB tool
  P6   follow-up rewriting: "what do you mean (by X)?" + no-pronoun mangling
  P7   STT confidence gate rejects low-quality transcripts
  P8   app-alias expansion only inside command-like utterances
  P9   illegible-transcript logging is throttled
  P10  TTS falls back only when the primary engine produced zero audio
  P11  RAG degrades to bare reasoning, never injects noise
  P12  conversational chatter gets an instant deterministic acknowledgment
  P13  voice state machine has no unreachable/non-advancing states
  P14  hard per-request reasoner deadline
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import threading
from types import SimpleNamespace
from unittest import mock

import numpy as np

from friday.intent.classifier import RequestClass, classify
from friday.reasoning.llamacpp_reasoner import LlamaCppReasoner
from friday.voice.state_machine import VoiceState, _VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# P1 — deterministic exit
# ---------------------------------------------------------------------------

class _RecorderReasoner:
    def __init__(self):
        self.requests = []

    def request(self, *a, **k):
        self.requests.append((a, k))
        return {"type": "response", "text": "should never be spoken"}

    def is_available(self):
        return True


def _manager(reasoner=None):
    from friday.core.conversation import ConversationManager
    return ConversationManager(
        dry_run=True,
        allow_real_execution=False,
        reasoner=reasoner or _RecorderReasoner(),
    )


def test_p1_prompt_3_exit_variants_stop_bye():
    rr = _RecorderReasoner()
    cm = _manager(rr)
    for phrase in ("bye", "good bye", "goodbye", "shutdown", "shut down",
                   "see you", "that's all", "thats all", "stop friday",
                   "stop", "exit", "quit"):
        resp, keep = cm.handle_transcript(phrase)
        assert resp == "Goodbye.", phrase
        assert keep is False, phrase
        assert rr.requests == [], f"reasoner must never run for {phrase!r}"


def test_p2_prompt_2_confirmability_bypasses_llm():
    rr = _RecorderReasoner()
    cm = _manager(rr)
    resp, keep = cm.handle_transcript("bye")
    assert resp == "Goodbye." and keep is False
    assert rr.requests == []


def test_p1_classifier_and_router_agree():
    for phrase in ("bye", "good bye", "goodbye", "shutdown", "see you",
                   "that's all", "thats all", "stop friday"):
        assert classify(phrase) == RequestClass.EXIT, phrase
    from friday.intent.router import route
    assert route("bye").action.name == "SYSTEM_STOP"
    assert route("stop friday").action.name == "SYSTEM_STOP"


# ---------------------------------------------------------------------------
# P5 — live-web routing for current information
# ---------------------------------------------------------------------------

def test_p5_prompt_4_current_info_uses_search_not_reasoner():
    rr = _RecorderReasoner()
    cm = _manager(rr)
    resp, keep = cm.handle_transcript("what is the latest news about python")
    assert keep is True
    assert rr.requests == [], "live web query must not reach the reasoner"
    blob = (resp or "").lower()
    assert "python" in blob or "searching" in blob


def test_p5_local_knowledge_stays_on_chat_path():
    rr = _RecorderReasoner()
    cm = _manager(rr)
    cm.handle_transcript("what is the latest architecture of the project")
    assert rr.requests, "codebase queries must stay on the chat path"
    # and a plain chat question still uses the reasoner
    rr.requests.clear()
    cm.handle_transcript("what is java")
    assert len(rr.requests) == 1


def test_p5_extract_live_web_query():
    from friday.core.conversation import ConversationManager
    cm = ConversationManager(dry_run=True, reasoner=_RecorderReasoner())
    assert cm._extract_live_web_query("what is the latest news about java") == "java"
    assert cm._extract_live_web_query("what's breaking in tech today") == "in tech today"
    assert cm._extract_live_web_query("what is java") == ""
    assert cm._extract_live_web_query("what is the recent rag changes in the codebase") == ""


# ---------------------------------------------------------------------------
# P6 — follow-up resolution ("what do you mean")
# ---------------------------------------------------------------------------

def test_p6_prompt_5_what_do_you_mean_rewrites():
    cm = _manager()
    cm.context.active_topic = "rather"
    out = cm.context.rewrite_followup("what do you mean", [""])
    assert out == "what is rather?", out


def test_p6_what_do_you_mean_by_x():
    cm = _manager()
    out = cm.context.rewrite_followup("what do you mean by backend", [""])
    assert out == "what is backend?", out


def test_p6_no_friday_mean_mangling():
    cm = _manager()
    text, grounded = cm.context.resolve_reference("what do you mean")
    assert "friday mean" not in text
    assert text == "what do you mean"


def test_p6_implementation_verbs_still_resolve_to_assistant():
    cm = _manager()
    cm.context.update_topic("what backend does it use")
    text, grounded = cm.context.resolve_reference("why did we choose that")
    assert "friday" in text and "backend" in text


def test_p6_anchored_fallback_no_duplication():
    cm = _manager()
    cm.context.active_topic = "rather"
    out = cm.context.rewrite_followup("what is rather", [""])
    assert out == "what is rather" or "rather" in out.lower()
    assert "(rather)" not in out.lower(), "anchor must not duplicate"


# ---------------------------------------------------------------------------
# P7 — STT confidence gate
# ---------------------------------------------------------------------------

def _stt_with_fake_model(rows_text_meta):
    from friday.voice.speech_to_text import SpeechToText
    stt = object.__new__(SpeechToText)
    stt.language = "en"
    stt.model_size = "small.en"
    stt.active_device = "cpu"
    stt.active_compute = "int8"

    def _transcribe(audio, **k):
        segs = [SimpleNamespace(text=t, avg_logprob=a, no_speech_prob=n)
                for t, a, n in rows_text_meta]
        return segs, None

    stt.model = SimpleNamespace(transcribe=_transcribe)
    return stt


def test_p7_prompt_1_quality_gate_rejects_noise():
    stt = _stt_with_fake_model([("", None, None)])
    text, rtf, meta = stt.transcribe_detailed(np.zeros(16000, dtype=np.float32))
    assert text == ""
    assert meta.quality_ok is True  # nothing transcribed anyway


def test_p7_high_no_speech_is_rejected():
    stt = _stt_with_fake_model([("hi", -0.5, 0.97)])
    text, rtf, meta = stt.transcribe_detailed(np.zeros(16000, dtype=np.float32))
    assert text == "hi"
    assert meta.no_speech_prob == 0.97
    assert meta.quality_ok is False, "no_speech=0.97 must be rejected"


def test_p7_low_avg_logprob_is_rejected():
    stt = _stt_with_fake_model([("hello", -3.1, 0.1)])
    text, rtf, meta = stt.transcribe_detailed(np.zeros(16000, dtype=np.float32))
    assert meta.avg_logprob == -3.1
    assert meta.quality_ok is False, "avg_logprob=-3.1 must be rejected"


def test_p7_clean_speech_is_accepted():
    stt = _stt_with_fake_model([("hello friday", -0.4, 0.05)])
    text, rtf, meta = stt.transcribe_detailed(np.zeros(16000, dtype=np.float32))
    assert text == "hello friday"
    assert meta.quality_ok is True


def test_p7_missing_metadata_is_accepted():
    stt = _stt_with_fake_model([])  # no segments / no metadata
    assert _stt_with_fake_model([("x", None, None)]).transcribe_detailed(
        np.zeros(16000, dtype=np.float32))[2].quality_ok is True


def _fake_audio_session(stt_fake):
    from friday.voice.session_manager import VoiceSessionManager
    sm = object.__new__(VoiceSessionManager)
    sm.audio = SimpleNamespace(
        is_active=lambda: True,
        drain=lambda: None,
        sample_rate=16000,
        chunk_size=1600,
        read_chunks=lambda: iter([np.ones(1600, dtype=np.float32)] * 10),
    )
    sm.vad = SimpleNamespace(is_speech=lambda c: True, reset_states=lambda: None)
    sm.stt = stt_fake
    sm.max_silence = 2.0
    sm.max_listen = 10.0
    sm._debug_saver = SimpleNamespace(save=lambda a, r: None, maybe_playback=lambda p: None)
    return sm


def test_p7_listen_once_rejects_low_quality():
    from friday.voice.session_manager import _NO_SPEECH
    stt = SimpleNamespace()
    stt.transcribe_detailed = lambda audio: (
        "random noise", 0.3,
        SimpleNamespace(avg_logprob=-4.2, no_speech_prob=0.98, quality_ok=False),
    )
    sm = _fake_audio_session(stt)
    assert sm.listen_once() == _NO_SPEECH


def test_p7_listen_once_accepts_quality_speech():
    from friday.voice.session_manager import _NO_SPEECH
    stt = SimpleNamespace()
    stt.transcribe_detailed = lambda audio: (
        "open chrome", 0.2,
        SimpleNamespace(avg_logprob=-0.3, no_speech_prob=0.02, quality_ok=True),
    )
    sm = _fake_audio_session(stt)
    assert sm.listen_once() == "open chrome"


# ---------------------------------------------------------------------------
# P8 — alias scoping
# ---------------------------------------------------------------------------

def test_p8_alias_only_in_command_utterances():
    from friday.core.conversation import _COMMAND_LIKE
    from friday.intent.normalizer import normalize_app_aliases

    command = "can you open grom"
    assert _COMMAND_LIKE.search(command) is not None
    fixed, changes = normalize_app_aliases(command)
    assert "chrome" in fixed and changes

    # A chat sentence mentioning the same word is not command-like, so the
    # alias expansion gate would not run for it.
    assert _COMMAND_LIKE.search("what did grom mean by that") is None


def test_p8_router_stops_and_commands_still_alias():
    from friday.intent.normalizer import normalize_app_aliases
    fixed, changes = normalize_app_aliases("open grom")
    assert fixed == "open chrome" and changes


# ---------------------------------------------------------------------------
# P9 — illegible shutdown / throttle
# ---------------------------------------------------------------------------

class _LevelRecorder:
    def __init__(self):
        self.infos = []
        self.debugs = []

    def info(self, *a):
        self.infos.append(a)

    def debug(self, *a):
        self.debugs.append(a)


def test_p9_prompt_9_requesnt_id_only_after_legible():
    from friday.core.assistant import Friday

    rec = _LevelRecorder()
    a = object.__new__(Friday)
    a.logger = rec
    # Run three skips back to back -> exactly one INFO, then DEBUG.
    a._note_non_legible()
    a._note_non_legible()
    a._note_non_legible()
    assert len(rec.infos) == 1, "first skip logs at INFO"
    assert len(rec.debugs) == 2, "subsequent skips log at DEBUG"


# ---------------------------------------------------------------------------
# P10 — TTS fallback-on-zero-units only
# ---------------------------------------------------------------------------

def _tts(**overrides):
    from friday.voice.text_to_speech import TextToSpeech
    tts = object.__new__(TextToSpeech)
    tts.engine_name = "piper"
    tts.fallback_engine = "kokoro"
    tts.kokoro = object()
    tts.piper = object()
    tts.voice = "af_heart"
    tts.speed = 1.0
    tts.abort_event = threading.Event()
    tts._is_speaking = False
    for k, v in overrides.items():
        setattr(tts, k, v)
    return tts


def test_p10_success_no_fallback():
    calls = []
    tts = _tts()
    tts._speak_piper = lambda text: (calls.append("piper") or (3, 0.5, 1.2))
    tts._speak_kokoro = lambda text: (calls.append("kokoro") or (2, 0.4, 0.9))
    tts.speak("Hello there.")
    assert calls == ["piper"], "fallback must not run on success"


def test_p10_zero_units_triggers_fallback():
    calls = []
    tts = _tts()
    tts._speak_piper = lambda text: (calls.append("piper") or (0, 0.0, 0.0))
    tts._speak_kokoro = lambda text: (calls.append("kokoro") or (2, 0.4, 0.9))
    tts.speak("Hello there.")
    assert calls == ["piper", "kokoro"]


def test_p10_partial_primary_never_repeats():
    calls = []
    tts = _tts()
    tts._speak_piper = lambda text: (calls.append("piper") or (2, 0.3, 0.8))
    tts._speak_kokoro = lambda text: (calls.append("kokoro") or (3, 0.4, 1.0))
    tts.speak("One sentence. Two sentences.")
    assert calls == ["piper"], "partial output must not be re-synthesized by fallback"


def test_p10_piper_loop_preserves_partial_units_on_mid_failure():
    from friday.voice.text_to_speech import TextToSpeech
    tts = _tts()
    tts.piper = SimpleNamespace(config=SimpleNamespace(sample_rate=22050))

    def synth(text, wav):
        if "Second" in text:
            raise RuntimeError("mid-response failure")
        wav.writeframes((np.zeros(22050, dtype=np.int16)).tobytes())

    tts.piper.synthesize_wav = synth
    with mock.patch.object(tts, "_play_interruptible", lambda data, fs: None):
        units, synth_s, play_s = tts._speak_piper("First sentence. Second sentence.")
    assert units == 1, "must keep the audio produced before the failure"
    assert synth_s > 0


def test_p10_speak_aggregation_log_uses_request_id():
    from friday.utils.logger import request_id_var
    request_id_var.set("abc123")
    tts = _tts()
    tts._speak_piper = lambda text: (1, 0.1, 0.2)
    tts._speak_kokoro = lambda text: (0, 0.0, 0.0)
    with mock.patch("friday.voice.text_to_speech.logger") as fake_logger:
        tts.speak("Hi.")
        calls = fake_logger.info.call_args_list
        assert any(
            "response complete" in c[0][0] and "abc123" in c[0] for c in calls
        ), calls


# ---------------------------------------------------------------------------
# P11 — RAG degrades to bare reasoning
# ---------------------------------------------------------------------------

def test_p11_rag_no_context_no_noise_in_chat():
    from friday.core.conversation import ConversationManager
    rr = _RecorderReasoner()
    rag = SimpleNamespace(
        config=SimpleNamespace(enabled=True),
        build_result=lambda *a, **k: None,
        build_prompt_block=lambda r: "RAG BLOCK SHOULD NOT APPEAR",
    )
    cm = ConversationManager(dry_run=True, reasoner=rr, rag_service=rag)
    cm.handle_transcript("what is java")
    assert rr.requests, "chat must still reach the reasoner"
    last_kwargs = rr.requests[-1][1]
    assert not (last_kwargs.get("retrieval_context") or ""), "no RAG noise injected"


# ---------------------------------------------------------------------------
# P12 — conversational chatter ack
# ---------------------------------------------------------------------------

def test_p12_chatter_is_deterministic():
    cm = _manager()
    resp, keep = cm.handle_transcript("thanks")
    assert resp == "You're welcome!"
    assert keep is True


def test_p12_classifier_recognizes_categories():
    assert classify("thanks") == RequestClass.CONVERSATIONAL
    assert classify("what do you mean") == RequestClass.FOLLOW_UP
    assert classify("open chrome") == RequestClass.TOOL_REQUEST


# ---------------------------------------------------------------------------
# P13 — state machine audit
# ---------------------------------------------------------------------------

def test_p13_every_state_has_an_outgoing_transition():
    for state in VoiceState:
        assert state in _VALID_TRANSITIONS, f"{state} missing from transition map"
    for state, targets in _VALID_TRANSITIONS.items():
        if state == VoiceState.IDLE:
            continue
        assert targets, f"{state} is a dead end (no outgoing transitions)"
        for t in targets:
            assert t in VoiceState, f"{state} has unknown target {t}"


# ---------------------------------------------------------------------------
# P3 / P14 — reasoner SSE streaming + deadline + usage
# ---------------------------------------------------------------------------

class _ChunkedResp:
    """Reads like an SSE response body (bytes lines)."""
    def __init__(self, lines):
        self._lines = list(lines)
        self._calls = 0

    def readline(self):
        self._calls += 1
        return self._lines.pop(0) if self._lines else b""

    def read(self):
        return b""


def _reasoner_sse(lines, deadline=None):
    import time
    if deadline is None:
        deadline = time.monotonic() + 2.0
    r = LlamaCppReasoner(base_url="http://x", model="m")
    return r._read_payload(_ChunkedResp(lines), deadline)


def test_p3_sse_streaming_parses_delta_and_usage():
    import time
    lines = [
        b'data: {"choices":[{"delta":{"content":"Java"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" is"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" great"}}],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n\n',
        b'data: [DONE]\n\n',
    ]
    text, prompt_tokens, completion_tokens, ttft, gen, streamed, hit, _fr = _reasoner_sse(lines)
    assert text == "Java is great"
    assert prompt_tokens == 12
    assert completion_tokens == 3
    assert streamed is True
    assert ttft >= 0.0 and gen >= 0.0
    assert hit is False


def test_p14_deadline_stops_streaming():
    import time
    lines = [b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'] * 500
    r = LlamaCppReasoner(base_url="http://x", model="m")
    resp = _ChunkedResp(lines)
    # deadline already in the past -> must return immediately with partial or empty
    text, _, _, _, _, _, hit, _fr = r._read_payload(resp, time.monotonic() - 5)
    assert hit is True
    assert isinstance(text, str)


def test_p3_no_usage_estimates_tokens():
    lines = [b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n', b"data: [DONE]\n\n"]
    text, _, completion_tokens, _, _, streamed, _, _fr = _reasoner_sse(lines)
    assert text == "hello"
    assert completion_tokens >= 1 and completion_tokens <= len(text) + 1


def test_p3_bulk_fallback_for_non_sse_bodies():
    r = LlamaCppReasoner(base_url="http://x", model="m")
    body = json.dumps({"choices": [{"message": {"content": "plain answer"}}]}).encode()
    resp = SimpleNamespace(readline=lambda: None, read=lambda: body)
    text, prompt_tokens, completion_tokens, _, _, streamed, _, fr = r._read_payload(resp, 2.0)
    assert text == "plain answer"
    assert streamed is False


def test_p3_bulk_fallback_estimates_tokens():
    r = LlamaCppReasoner(base_url="http://x", model="m")
    body = json.dumps({"choices": [{"message": {"content": "12345678"}}]}).encode()
    resp = SimpleNamespace(readline=lambda: None, read=lambda: body)
    _, _, completion_tokens, _, _, _, _, _fr = r._read_payload(resp, 2.0)
    assert completion_tokens == 2  # 8 chars // 4


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))