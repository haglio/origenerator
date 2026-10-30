"""The one way the app asks the local model for an answer: Ollama's own chat
door, which is the one that takes how much the model reads at once."""
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
        return _Resp({"message": {"role": "assistant", "content": '{"answer": 1}'}, "done": True})

    with patch.object(local_llm.urllib.request, "urlopen", urlopen):
        answer = local_llm.ask([{"role": "user", "content": "hi"}], **kwargs)
    return sent, answer


def test_a_question_goes_to_ollamas_chat_door_and_its_answer_comes_back_whole():
    sent, answer = _asked(base_url="http://localhost:11434/", model="m", temperature=0.2,
                          timeout=7)

    assert sent["url"] == "http://localhost:11434/api/chat"
    assert (sent["body"]["model"], sent["body"]["options"]["temperature"], sent["timeout"]) == (
        "m", 0.2, 7)
    assert sent["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert sent["body"]["stream"] is False
    assert sent["body"]["format"] == "json"
    assert answer == {"message": {"role": "assistant", "content": '{"answer": 1}'}, "done": True}


def test_the_answer_is_the_json_object_the_model_replied_with():
    completion = {"message": {"content": '{"positive": "a woman", "negative": "b"}'}}

    assert local_llm.answer_of(completion) == {"positive": "a woman", "negative": "b"}


def test_the_answer_is_found_past_a_fence_or_a_preamble_around_it():
    completion = {"message": {
        "content": 'Sure —\n```json\n{"positive": "a", "negative": "b"}\n```'}}

    assert local_llm.answer_of(completion) == {"positive": "a", "negative": "b"}


def test_the_local_model_is_asked_not_to_think_before_it_answers():
    sent, _answer = _asked(base_url="http://x", model="m", temperature=0.1, timeout=1)

    assert sent["body"]["think"] is False


def test_a_question_asked_in_words_rather_than_json_names_no_format():
    sent, _answer = _asked(base_url="http://x", model="m", temperature=0.6, timeout=1,
                           json_answer=False)

    assert "format" not in sent["body"]


def test_a_question_can_say_how_much_the_model_reads_how_long_it_answers_and_how_long_it_stays():
    sent, _answer = _asked(base_url="http://x", model="m", temperature=0.6, timeout=1,
                           reads_tokens=40960, answers_tokens=600, stays_loaded="0")

    assert sent["body"]["options"]["num_ctx"] == 40960
    assert sent["body"]["options"]["num_predict"] == 600
    assert sent["body"]["keep_alive"] == "0"


def test_a_question_that_leaves_those_unsaid_leaves_them_to_the_model():
    sent, _answer = _asked(base_url="http://x", model="m", temperature=0.6, timeout=1)

    assert sent["body"]["options"] == {"temperature": 0.6}
    assert "keep_alive" not in sent["body"]


def test_the_words_of_an_answer_come_back_without_the_models_thinking():
    completion = {"message": {"content": "<think>\nhmm\n</think>\n\nNotes: subjects recur."}}

    assert local_llm.text_of(completion) == "Notes: subjects recur."


def test_how_much_a_question_took_is_read_off_the_answer():
    assert local_llm.tokens_read({"prompt_eval_count": 24303}) == 24303
    assert local_llm.tokens_read({}) == 0
