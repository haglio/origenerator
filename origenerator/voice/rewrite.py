"""Rewrite the current image-generation prompt from a spoken instruction.

Calls a local, OpenAI-compatible chat endpoint (Ollama's ``/v1``, LM Studio,
llama.cpp, …) over stdlib ``urllib`` — the same no-extra-dependency HTTP the
ComfyUI client uses. A local model is chosen deliberately: it applies edits to
explicit prompts without the refusals a hosted model may raise, and nothing
leaves the machine. Message-building and response-parsing are split out as pure
functions so the request shape can be unit-tested without a server.
"""

import json
import urllib.request


def build_messages(current_prompt: str, instruction: str, system_prompt: str) -> list[dict]:
    """The chat messages for one rewrite: the editing rules, then the current
    prompt and the spoken change as the user turn."""
    user = (
        f"Current prompt:\n{current_prompt}\n\n"
        f"Spoken instruction:\n{instruction}\n\n"
        "Reply with only the full revised prompt."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def parse_completion(data: dict) -> str:
    """The assistant text from an OpenAI-compatible chat completion response."""
    return data["choices"][0]["message"]["content"].strip()


def rewrite_prompt(current_prompt: str, instruction: str, *, base_url: str, model: str,
                   system_prompt: str, timeout: float = 30.0) -> str:
    """Ask the local LLM to apply ``instruction`` to ``current_prompt`` and return
    the revised prompt. Raises on transport or decode errors so the caller can
    surface them rather than silently keeping the old prompt."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": build_messages(current_prompt, instruction, system_prompt),
        "temperature": 0.7,
        "stream": False,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read())
    return parse_completion(data)
