"""The one way this app asks the local model for an answer: one POST to Ollama's
own chat door on this machine, over stdlib ``urllib``.

Ollama's door rather than its OpenAI-shaped one, because only its own takes how
much the model reads at once (``num_ctx``): a question that carries notes on a
whole collection is far longer than the default window, and the OpenAI shape has
no way to say so.
"""
from __future__ import annotations

import json
import re
import urllib.request

_THINKING = re.compile(r"<think>.*?</think>", re.S)


def answer_of(completion: dict) -> dict:
    content = text_of(completion)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def text_of(completion: dict) -> str:
    return _THINKING.sub("", completion["message"]["content"]).strip()


def tokens_read(completion: dict) -> int:
    return int(completion.get("prompt_eval_count") or 0)


def ask(messages: list[dict], *, base_url: str, model: str, temperature: float,
        timeout: float, json_answer: bool = True, reads_tokens: int | None = None,
        answers_tokens: int | None = None, stays_loaded: str | None = None) -> dict:
    options: dict = {"temperature": temperature}
    if reads_tokens is not None:
        options["num_ctx"] = reads_tokens
    if answers_tokens is not None:
        options["num_predict"] = answers_tokens
    payload: dict = {"model": model, "messages": messages, "stream": False, "think": False,
                     "options": options}
    if json_answer:
        payload["format"] = "json"
    if stays_loaded is not None:
        payload["keep_alive"] = stays_loaded
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())
