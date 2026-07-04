"""rewrite_prompt — turn a spoken instruction into an edited image prompt via a
local OpenAI-compatible chat endpoint."""

import json
from unittest.mock import patch

from origenerator.voice import rewrite


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_build_messages_carries_the_prompt_and_instruction():
    messages = rewrite.build_messages("a cat", "make it a dog", "SYSTEM RULES")
    assert messages[0] == {"role": "system", "content": "SYSTEM RULES"}
    assert "a cat" in messages[1]["content"]
    assert "make it a dog" in messages[1]["content"]


def test_parse_completion_extracts_and_strips_the_message():
    data = {"choices": [{"message": {"content": "  a dog running  "}}]}
    assert rewrite.parse_completion(data) == "a dog running"


def test_rewrite_prompt_posts_to_the_chat_endpoint_and_returns_the_text():
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _Resp({"choices": [{"message": {"content": "a dog"}}]})

    with patch.object(rewrite.urllib.request, "urlopen", _fake_urlopen):
        out = rewrite.rewrite_prompt(
            "a cat", "make it a dog",
            base_url="http://localhost:11434/v1", model="llama3.1",
            system_prompt="SYSTEM RULES",
        )

    assert out == "a dog"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["body"]["model"] == "llama3.1"
    assert captured["body"]["stream"] is False
    assert "a cat" in captured["body"]["messages"][1]["content"]
