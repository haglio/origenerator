"""The one way this app asks the local model for an answer: Ollama's own chat door,
the one that takes how much the model reads at once, which its OpenAI-shaped door
does not, and a question carrying notes on a whole collection needs."""
from __future__ import annotations

import json
import re
import urllib.request

_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)


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
    return _post(base_url, payload, timeout)


def let_go(*, base_url: str, model: str, timeout: float = 30.0) -> None:
    # Ollama unloads a model at once when asked nothing and told to keep it no longer.
    _post(base_url, {"model": model, "messages": [], "keep_alive": "0"}, timeout)


def _post(base_url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())
