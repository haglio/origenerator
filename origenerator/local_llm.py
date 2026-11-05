from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

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


@dataclass(frozen=True)
class _Answering:
    temperature: float
    json_answer: bool = True
    reads_tokens: int | None = None
    answers_tokens: int | None = None
    stays_loaded: str | None = None

    def options(self) -> dict:
        options: dict = {"temperature": self.temperature}
        if self.reads_tokens is not None:
            options["num_ctx"] = self.reads_tokens
        if self.answers_tokens is not None:
            options["num_predict"] = self.answers_tokens
        return options


def ask(messages: list[dict], *, base_url: str, model: str, timeout: float, **how) -> dict:
    answering = _Answering(**how)
    payload: dict = {"model": model, "messages": messages, "stream": False, "think": False,
                     "options": answering.options()}
    if answering.json_answer:
        payload["format"] = "json"
    if answering.stays_loaded is not None:
        payload["keep_alive"] = answering.stays_loaded
    return _post(base_url, payload, timeout)


def let_go(*, base_url: str, model: str, timeout: float = 30.0, opened=None) -> None:
    # Ollama unloads a model at once when asked nothing and told to keep it no longer.
    _post(base_url, {"model": model, "messages": [], "keep_alive": "0"}, timeout, opened)


def _post(base_url: str, payload: dict, timeout: float, opened=None) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with (opened or urllib.request.urlopen)(request, timeout=timeout) as response:
        return json.loads(response.read())
