"""The one way this app asks the local model for an answer: one POST to the
OpenAI-compatible chat endpoint on this machine, over stdlib ``urllib``."""
from __future__ import annotations

import json
import urllib.request


def answer_of(completion: dict) -> dict:
    """The JSON object in a completion's reply, past any fence or preamble."""
    content = completion["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def ask_json(messages: list[dict], *, base_url: str, model: str, temperature: float,
             timeout: float) -> dict:
    """The completion for ``messages``; raises on a transport or decode error."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
        "reasoning_effort": "none",
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())
