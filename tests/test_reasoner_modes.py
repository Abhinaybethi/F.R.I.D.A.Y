"""
Reasoner CHAT vs ACTION mode unit tests.

Verifies that knowledge questions use the natural-language chat prompt and
that concrete commands use the structured intent JSON prompt + validator.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
from unittest import mock

from friday.reasoning.llamacpp_reasoner import LlamaCppReasoner
from friday.reasoning.prompt import SYSTEM_PROMPT
from friday.reasoning.chat_prompt import CHAT_PROMPT
from friday.planning.context_resolver import ShortTermContext


class _Resp:
    status = 200

    def __init__(self, content):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": self._content}}]}).encode()


def _reasoner(captured):
    r = LlamaCppReasoner(base_url="http://127.0.0.1:8080", model="m", timeout=5)
    r.is_available = lambda: True

    def _urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _Resp(captured.pop("content", '{"type":"unknown"}'))  # always at least {}

    return r, _urlopen


def test_chat_mode_uses_chat_prompt_and_returns_natural_response():
    captured = {"content": "Java is a statically typed, object-oriented language."}
    r, urlopen = _reasoner(captured)
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen", side_effect=urlopen):
        out = r.request("what is java", ShortTermContext(), mode="chat")

    assert out == {"type": "response", "text": "Java is a statically typed, object-oriented language."}
    assert captured["payload"]["temperature"] == 0.4
    assert captured["payload"]["max_tokens"] == 512
    assert captured["payload"]["messages"][0]["content"] == CHAT_PROMPT


def test_action_mode_uses_structured_prompt_and_validator():
    captured = {
        "content": '{"type":"intent","action":"OPEN_APP","target":"chrome","confidence":0.9}'
    }
    r, urlopen = _reasoner(captured)
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen", side_effect=urlopen):
        out = r.request("open chrome", ShortTermContext(), mode="action")

    assert out["type"] == "intent"
    assert out["action"] == "OPEN_APP"
    assert out["target"] == "chrome"
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["max_tokens"] == 128
    assert captured["payload"]["messages"][0]["content"] == SYSTEM_PROMPT


def test_action_mode_rejects_destructive_actions():
    # close_app is NOT on the reasoner safe allowlist -> must be rejected,
    # even if the model hallucinates it.
    captured = {
        "content": '{"type":"intent","action":"CLOSE_APP","target":"chrome","confidence":0.9}'
    }
    r, urlopen = _reasoner(captured)
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen", side_effect=urlopen):
        out = r.request("close chrome", ShortTermContext(), mode="action")

    assert out.get("type") == "unknown", "Unsafe reasoner actions must validate to unknown"


def test_chat_mode_json_output_still_handled():
    captured = {"content": '{"type":"response","text":"Sure, I can help."}'}
    r, urlopen = _reasoner(captured)
    with mock.patch("friday.reasoning.llamacpp_reasoner.urllib.request.urlopen", side_effect=urlopen):
        out = r.request("hi there", ShortTermContext(), mode="chat")
    assert out == {"type": "response", "text": "Sure, I can help."}