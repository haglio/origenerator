"""The one way the app asks the local model for an answer."""
from __future__ import annotations

import json
from unittest.mock import patch

from origenerator import local_llm


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _asked(**kwargs):
    sent = {}

    def urlopen(request, timeout=None):
        sent["url"], sent["body"], sent["timeout"] = request.full_url, json.loads(request.data), timeout
        return _Resp({"choices": [{"message": {"content": '{"answer": 1}'}}]})

    with patch.object(local_llm.urllib.request, "urlopen", urlopen):
        answer = local_llm.ask_json([{"role": "user", "content": "hi"}], **kwargs)
    return sent, answer


def test_a_question_goes_to_the_chat_endpoint_and_its_answer_comes_back_whole():
    sent, answer = _asked(base_url="http://localhost:11434/v1/", model="m", temperature=0.2,
                          timeout=7)

    assert sent["url"] == "http://localhost:11434/v1/chat/completions"
    assert (sent["body"]["model"], sent["body"]["temperature"], sent["timeout"]) == ("m", 0.2, 7)
    assert sent["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert sent["body"]["response_format"] == {"type": "json_object"}
    assert answer == {"choices": [{"message": {"content": '{"answer": 1}'}}]}


def test_the_answer_is_the_json_object_the_model_replied_with():
    completion = {"choices": [{"message": {"content": '{"positive": "a woman", "negative": "b"}'}}]}

    assert local_llm.answer_of(completion) == {"positive": "a woman", "negative": "b"}


def test_the_answer_is_found_past_a_fence_or_a_preamble_around_it():
    completion = {"choices": [{"message": {
        "content": 'Sure \u2014\n```json\n{"positive": "a", "negative": "b"}\n```'}}]}

    assert local_llm.answer_of(completion) == {"positive": "a", "negative": "b"}


def test_the_local_model_is_asked_not_to_think_before_it_answers():
    sent, _answer = _asked(base_url="http://x/v1", model="m", temperature=0.1, timeout=1)

    assert sent["body"]["reasoning_effort"] == "none"
