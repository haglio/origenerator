"""Rewrite the current image-generation prompt pair from a spoken instruction.

Asks the local model (:mod:`origenerator.local_llm`) to edit BOTH the positive
and negative prompt with Stable-Diffusion semantics — negation goes to the
negative prompt, "more"/"less" adjust ``(term:weight)`` emphasis — driven by the
system prompt in ``config``.
"""
from __future__ import annotations

from origenerator import local_llm


def build_messages(positive: str, negative: str, instruction: str, system_prompt: str) -> list[dict]:
    """The chat messages for one rewrite: the editing rules, then the current
    prompt pair and the spoken change as the user turn."""
    user = (
        f"Positive prompt:\n{positive}\n\n"
        f"Negative prompt:\n{negative}\n\n"
        f"Spoken instruction:\n{instruction}\n\n"
        'Reply with only a JSON object with two keys: "positive", holding the whole '
        'rewritten positive prompt, and "negative", holding the whole rewritten negative prompt.'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def rewrite_prompt(positive: str, negative: str, instruction: str, *, base_url: str,
                   model: str, system_prompt: str, timeout: float = 30.0):
    """Apply ``instruction`` to the (positive, negative) prompt pair via the local
    LLM and return the revised pair. A field the model omits is left unchanged.
    Raises on transport/decode errors so the caller can surface them."""
    obj = local_llm.answer_of(local_llm.ask_json(
        build_messages(positive, negative, instruction, system_prompt),
        base_url=base_url, model=model, temperature=0.4, timeout=timeout))
    new_positive = str(obj["positive"]).strip() if "positive" in obj else positive
    new_negative = str(obj["negative"]).strip() if "negative" in obj else negative
    return new_positive, new_negative
