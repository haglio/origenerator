"""Rewrite the current image-generation prompt pair from a spoken instruction.

Calls a local, OpenAI-compatible chat endpoint over stdlib ``urllib`` (the same
no-extra-dependency HTTP the ComfyUI client uses). It edits BOTH the positive and
negative prompt with Stable-Diffusion semantics — negation goes to the negative
prompt, "more"/"less" adjust ``(term:weight)`` emphasis — driven by the system
prompt in ``config``. Message-building and JSON-parsing are split out as pure
functions so the request shape can be unit-tested without a server.
"""

import json
import urllib.request


def build_messages(positive: str, negative: str, instruction: str, system_prompt: str) -> list[dict]:
    """The chat messages for one rewrite: the editing rules, then the current
    prompt pair and the spoken change as the user turn."""
    user = (
        f"Positive prompt:\n{positive}\n\n"
        f"Negative prompt:\n{negative}\n\n"
        f"Spoken instruction:\n{instruction}\n\n"
        'Reply with only JSON: {"positive": "...", "negative": "..."}'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _extract_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")  # tolerate fences/preamble
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def parse_completion(data: dict) -> dict:
    """The JSON object the model returned (its positive/negative prompt fields)."""
    return _extract_json(data["choices"][0]["message"]["content"])


def rewrite_prompt(positive: str, negative: str, instruction: str, *, base_url: str,
                   model: str, system_prompt: str, timeout: float = 30.0):
    """Apply ``instruction`` to the (positive, negative) prompt pair via the local
    LLM and return the revised pair. A field the model omits is left unchanged.
    Raises on transport/decode errors so the caller can surface them."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": build_messages(positive, negative, instruction, system_prompt),
        "temperature": 0.4,  # editing, not brainstorming — keep it close to the source
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        obj = parse_completion(json.loads(response.read()))
    new_positive = str(obj["positive"]).strip() if "positive" in obj else positive
    new_negative = str(obj["negative"]).strip() if "negative" in obj else negative
    return new_positive, new_negative
