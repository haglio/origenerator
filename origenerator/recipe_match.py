"""Route a dropped image to an existing video's recipe by category, from prompts.

The gallery's combine panel can re-run any past i2v video's recipe (workflow +
LoRA + prompt) on a freshly dropped image. This picks *which* past video to reuse
from a chosen act — "gamma", "redacted", … — without the user hunting one down:
every candidate video already carries the prompt it was made with, and so does the
dropped image ("assume the prompt was respected", so the image's own prompt
describes what's in frame). A local LLM reads the image's prompt and the candidate
prompts and names the best-fit exemplar; a deterministic keyword match stands in
when the model is unreachable.

Qt-free and with the HTTP boundary isolated in one function, so the routing logic
stays unit-testable without a running model. Mirrors ``voice/rewrite.py``'s shape.
"""

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CATEGORIES = ("gamma", "epsilon", "zeta", "redacted", "alpha", "dancing")

# Most candidates to send the LLM in one routing call — enough that the right
# exemplar is almost always among them, capped so a huge gallery can't bloat the
# prompt. The pre-rank ensures the likeliest survive the cut.
_TOP_K = 15

# Distinctive substrings that mark a candidate prompt as depicting each act. Used
# only to steer the deterministic fallback and the pre-rank sent to the LLM — the
# model itself handles paraphrase — so the lists stay conservative (a loose match
# like a bare "bj" would fire on unrelated words) rather than exhaustive.
_CATEGORY_KEYWORDS = {
    "gamma": ("gamma", "gamma", "oral", "alpha", "redacted", "alpha form",
                "anchor in mouth", "anchor in her mouth", "anchor in mouth"),
    "epsilon": ("epsilon", "epsilon", "stroking", "jerking", "jerk off", "stroke"),
    "zeta": ("zeta", "redacted job", "zeta", "zeta", "zeta", "titty redacted",
                "zeta", "between her redacteds", "between her zeta"),
    "redacted": ("redacted", "redacted", "penetrat", "intercourse", "riding", "doggy",
                "cowsubject", "delta"),
    "alpha": ("alpha", "alpha", "redacted", "ejaculat", "redacted", "redacted on",
                "epsilon form"),
    "dancing": ("dancing", "dance", "twerk", "striptease", "strip tease", "stripping"),
}

# Function words carry no scene signal, so they'd inflate the overlap of any two
# prompts equally; dropped before comparing.
_STOPWORDS = frozenset((
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "her", "his",
    "with", "is", "are", "as", "by", "for",
))


@dataclass
class Candidate:
    """One reusable exemplar: the video's prompt_id and the prompt it was made with."""

    prompt_id: str
    prompt: str


def build_candidates(video_rows) -> list[Candidate]:
    """The matchable exemplars among ``video_rows``.

    A row contributes a candidate only when it can both be *launched* (it has a
    ``prompt_id``) and *matched* (a non-empty ``positive_prompt`` to compare against
    the dropped image's prompt). Rows missing either are dropped — a promptless
    exemplar carries no signal about which act or scene it depicts.
    """
    candidates = []
    for row in video_rows:
        pid = row.get("prompt_id")
        prompt = (row.get("positive_prompt") or "").strip()
        if pid and prompt:
            candidates.append(Candidate(pid, prompt))
    return candidates


# --- prompt scoring (fallback + LLM pre-rank) ------------------------------


def _tokenize(text: str) -> set[str]:
    """The scene-bearing word set of ``text`` — lowercased, function words dropped."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _matches_category(category: str, prompt: str) -> bool:
    """Whether ``prompt`` reads as depicting ``category`` by its keyword substrings."""
    low = prompt.lower()
    return any(kw in low for kw in _CATEGORY_KEYWORDS.get(category, ()))


def deterministic_choice(category: str, image_prompt: str, candidates: list) -> str | None:
    """The best category-matching exemplar by scene overlap, or ``None`` if none fit.

    The fallback for when the LLM is unreachable: keep only candidates whose prompt
    reads as the chosen act, then pick the one sharing the most scene words with the
    dropped image's prompt. Ties go to the earlier (newer) candidate.
    """
    image = _tokenize(image_prompt)
    best, best_overlap = None, -1
    for candidate in candidates:
        if not _matches_category(category, candidate.prompt):
            continue
        overlap = len(image & _tokenize(candidate.prompt))
        if overlap > best_overlap:
            best, best_overlap = candidate, overlap
    return best.prompt_id if best else None


def prefilter(category: str, image_prompt: str, candidates: list, k: int) -> list:
    """The ``k`` most relevant candidates to hand the LLM, best first.

    Ranks by (is-this-act, scene overlap) so exemplars of the chosen act — then the
    closest scenes — lead, and caps the list so a large gallery can't blow up the
    LLM prompt. Non-act candidates are kept as padding (the model may still spot a
    paraphrase the keyword gate missed), just ranked last.
    """
    image = _tokenize(image_prompt)
    ranked = sorted(
        candidates,
        key=lambda c: (_matches_category(category, c.prompt), len(image & _tokenize(c.prompt))),
        reverse=True,
    )
    return ranked[:k]


# --- LLM routing (message building, reply parsing, the call) ---------------


def build_messages(category: str, image_prompt: str, candidates: list, system_prompt: str) -> list:
    """The chat messages for one routing decision: the rules, then the task.

    The user turn states the act wanted, describes the dropped image (its own
    prompt), lists the candidate recipes numbered from 0, and pins the reply to
    ``{"choice": n}`` — where ``n`` indexes ``candidates`` (or ``-1`` for none).
    """
    listing = "\n".join(f"{i}. {c.prompt}" for i, c in enumerate(candidates))
    user = (
        f"Desired act: {category}\n\n"
        f"The input image shows:\n{image_prompt}\n\n"
        f"Candidate {category} clips (each is the prompt it was made from):\n{listing}\n\n"
        "Pick the ONE candidate that is really a "
        f"{category} clip AND whose scene best fits the input image. "
        'Reply with only JSON: {"choice": <the number to its left, or -1 if none fit>}'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _extract_json(content: str) -> dict:
    """Parse a JSON object out of an LLM reply, tolerating fences/preamble."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def parse_choice(completion: dict, candidates: list) -> str | None:
    """The chosen exemplar's prompt_id from a chat completion, or ``None`` for none.

    Reads ``{"choice": n}`` from the reply and maps ``n`` back onto ``candidates``.
    Returns ``None`` when the model answers ``-1`` or an out-of-range index (a
    legitimate "none of these fit"). Raises when the reply carries no usable choice
    at all — the caller treats that like any other model failure and falls back.
    """
    obj = _extract_json(completion["choices"][0]["message"]["content"])
    index = int(obj["choice"])
    if 0 <= index < len(candidates):
        return candidates[index].prompt_id
    return None


def _post_chat(base_url: str, model: str, messages: list, timeout: float) -> dict:
    """POST one chat request to the local OpenAI-compatible endpoint; return its JSON.

    The single I/O boundary — isolated so the routing above stays testable — using
    the same stdlib ``urllib`` the ComfyUI client and voice rewrite use. Low
    temperature: this is a lookup, not brainstorming.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def choose_recipe(category: str, image_prompt: str, video_rows, *, base_url: str,
                  model: str, system_prompt: str, timeout: float = 20.0) -> str | None:
    """The prompt_id of the exemplar video whose recipe best fits this drop, or None.

    Builds candidates from ``video_rows``, pre-ranks them for ``category`` against
    the dropped image's ``image_prompt``, and asks the local LLM to pick the best
    fit. Falls back to the deterministic keyword match when the model is unreachable
    or answers unusably. Returns ``None`` when there are no candidates, or when the
    model deliberately reports that none of them fit.
    """
    candidates = prefilter(category, image_prompt, build_candidates(video_rows), _TOP_K)
    if not candidates:
        return None
    try:
        completion = _post_chat(
            base_url, model, build_messages(category, image_prompt, candidates, system_prompt), timeout
        )
        chosen = parse_choice(completion, candidates)
        logger.info("recipe_match: category=%s source=llm chosen=%s", category, chosen)
        return chosen
    except Exception as exc:  # model down / unparseable: keep the feature working
        chosen = deterministic_choice(category, image_prompt, candidates)
        logger.warning(
            "recipe_match: category=%s source=fallback chosen=%s (llm failed: %s)",
            category, chosen, exc,
        )
        return chosen
