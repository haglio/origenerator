"""rewrite_prompt — turn a spoken instruction into an edited positive/negative
prompt pair via a local OpenAI-compatible chat endpoint."""

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


def _reply(content):
    return _Resp({"choices": [{"message": {"content": content}}]})


def test_build_messages_carries_both_prompts_and_the_instruction():
    messages = rewrite.build_messages("a woman, tan", "blurry", "no tan lines", "SYSTEM")
    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    content = messages[1]["content"]
    assert "a woman, tan" in content and "blurry" in content and "no tan lines" in content


def test_parse_completion_extracts_the_json_object():
    data = {"choices": [{"message": {"content": '{"positive": "a woman", "negative": "tan lines"}'}}]}
    assert rewrite.parse_completion(data) == {"positive": "a woman", "negative": "tan lines"}


def test_parse_completion_tolerates_fenced_or_wrapped_json():
    data = {"choices": [{"message": {"content": 'Sure —\n```json\n{"positive": "a", "negative": "b"}\n```'}}]}
    assert rewrite.parse_completion(data) == {"positive": "a", "negative": "b"}


def test_rewrite_prompt_posts_both_prompts_and_returns_the_pair():
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return _reply('{"positive": "a woman", "negative": "tan lines"}')

    with patch.object(rewrite.urllib.request, "urlopen", _fake_urlopen):
        result = rewrite.rewrite_prompt(
            "a woman, tan", "", "no tan lines",
            base_url="http://localhost:11434/v1", model="dolphin", system_prompt="SYSTEM",
        )

    assert result == ("a woman", "tan lines")
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["body"]["model"] == "dolphin"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert "a woman, tan" in captured["body"]["messages"][1]["content"]


def test_rewrite_prompt_keeps_a_field_the_model_omits():
    with patch.object(rewrite.urllib.request, "urlopen",
                      lambda request, timeout=None: _reply('{"positive": "a man"}')):
        positive, negative = rewrite.rewrite_prompt(
            "a woman", "existing negative", "make her a man",
            base_url="http://x/v1", model="m", system_prompt="S",
        )

    assert positive == "a man" and negative == "existing negative"  # negative preserved
