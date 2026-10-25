"""Pick the settings for a dropdown act, mined from the gallery, in two tiers.

An act's videos are the ones launched as that act, grouped by their settings, and the
chosen one supplies its full params to re-run on a dropped image.
:func:`scene_matched_video` asks the local LLM which group's starting scene fits;
:func:`most_used_video` falls back to the act's most-used; :func:`pinned_settings` sits
above both, for an act the overlay pins; :func:`available_categories` says which
acts any tier could answer. Every tier is asked for one *intent* (:data:`VIDEO` or
:data:`GENAU`), which chooses the overlay table consulted and, for ``GENAU``,
narrows mining to videos a looping workflow made.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from collections import defaultdict

from origenerator.content import genau_flick_word, load_content

logger = logging.getLogger(__name__)

_CONTENT = load_content()

# Library vocabulary, so the overlay's (content.example.json documents the shape).
CATEGORIES: tuple[str, ...] = tuple(_CONTENT["acts"])

# What the settings are chosen for. A long-form video for the Satellite Funestras,
# or a Genau flick — one complete cycle, looping end to end, scrubbed against the
# device's phase rather than played. Both are "an act on this image", so they share
# every tier here; what differs is which overlay table is consulted and, for GENAU,
# that only a looping workflow's videos can be mined.
VIDEO = "video"
GENAU = "genau"

# An act named here runs its pinned workflow+params instead of whatever mining
# would pick, which is the way out for an act whose past videos all share a
# weakness. One table per intent, because the key is the act alone.
_CURATED_BY_INTENT: dict[str, dict] = {
    VIDEO: _CONTENT.get("pinned_kino_settings") or {},
    GENAU: _CONTENT.get("pinned_genau_settings") or {},
}


def pinned_settings(category: str, intent: str = VIDEO) -> dict | None:
    """The overlay's hand-tuned ``intent`` settings for ``category``, else ``None``
    -- including for a malformed entry, so the caller falls back to mining rather
    than failing the act."""
    spec = _CURATED_BY_INTENT.get(intent, {}).get(category)
    if not isinstance(spec, dict) or not spec.get("workflow"):
        return None
    return spec


def loops(row) -> bool:
    """Whether a looping workflow made ``row`` — its last frame meeting its first,
    which only such a video can supply Genau settings from. The registry import is
    deferred: it pulls in the whole workflow package."""
    from origenerator.workflows import WORKFLOW_REGISTRY  # noqa: PLC0415 — keeps this module light

    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
    return bool(workflow and workflow.looping)

# Params that are no part of the settings: the prompt, the start frame, the seeds, the
# bookkeeping, and the values derived rather than chosen (the output size, the clip
# length, the dual-sampler split points). Excluding them keeps the signature on the
# real levers, so one setup on different frames groups as one.
_SETTINGS_EXCLUDE = frozenset((
    "positive_prompt", "negative_prompt", "input_image",
    "seed", "noise_seed", "filename_prefix", "batch_size",
    "width", "height", "length", "frame_count", "frame_rate",
    "start_at_step", "end_at_step",
))


def _hashable(value):
    """A stable, hashable stand-in for a param value (lists/dicts → sorted JSON)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _settings_signature(row: dict):
    """A hashable key for a row's model+params settings, ignoring the free-text prompt,
    the input image and the seeds — so the same setup on different frames counts as
    one."""
    try:
        params = json.loads(row.get("params_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        params = {}
    if not isinstance(params, dict):
        params = {}
    settings = tuple(sorted(
        (k, _hashable(v)) for k, v in params.items() if k not in _SETTINGS_EXCLUDE
    ))
    return (row.get("workflow_name") or "", settings)


def _created(row) -> str:
    """A row's creation timestamp for recency ordering (missing sorts oldest)."""
    return row.get("created_at") or ""


def _act_settings_groups(category: str, video_rows, *, require_scene: bool = False,
                         loop_only: bool = False) -> dict:
    """The act's videos grouped by settings signature. ``require_scene`` also drops
    rows with no ``start_scene`` — nothing for the LLM to situation-match on.
    ``loop_only`` keeps just the ones a looping workflow made (see :func:`_loops`)."""
    groups = defaultdict(list)
    for row in video_rows:
        if act_of(row) != category:
            continue
        if require_scene and not (row.get("start_scene") or "").strip():
            continue
        if loop_only and not loops(row):
            continue
        groups[_settings_signature(row)].append(row)
    return groups


def act_of(row: dict) -> str:
    """The act ``row`` shows, because somebody said so: a video's is the act it was
    launched as, an image's the action it was sorted as, and "" means nobody has
    said. Never read off the prompt."""
    return row.get("act") or row.get("image_state") or ""


def no_past_video(act: str, lane: str) -> str:
    what = f"looping “{act}” {genau_flick_word()}" if lane == GENAU else f"“{act}” video"
    return f"no past {what} to take settings from yet"


def as_sentence(said: str) -> str:
    return said[:1].upper() + said[1:]


def available_categories(video_rows, intent: str = VIDEO) -> set[str]:
    """The acts a picked dropdown entry can actually answer: those ``video_rows``
    holds at least one usable video of (settings can be mined), plus those the
    overlay pins ``intent`` settings for (nothing to mine — the settings are
    pinned). The panel greys out the rest, so an act that could only ever answer
    "no past video yet" is never offered.

    Under ``GENAU`` only a looping workflow's videos count toward the mined half:
    a long-form video of the act is real, but its settings cannot make a Genau flick.
    """
    loop_only = intent == GENAU
    return {c for c in CATEGORIES
            if pinned_settings(c, intent) is not None
            or any(act_of(row) == c and (not loop_only or loops(row))
                   for row in video_rows)}


def most_used_video(category: str, video_rows, intent: str = VIDEO) -> str | None:
    """The prompt_id of the exemplar for ``category``'s most-used settings, or
    ``None`` when the gallery holds no video of the act. Most used is the settings under the most
    of the user's videos of it, ties to the more recent, shown by its newest."""
    groups = _act_settings_groups(category, video_rows, loop_only=intent == GENAU)
    if not groups:
        return None
    best = max(groups.values(), key=lambda g: (len(g), max(_created(r) for r in g)))
    return max(best, key=_created)["prompt_id"]


# --- situation-aware pick (LLM over the groups' starting scenes) -----------


def _settings_representatives(category: str, video_rows, *, loop_only: bool = False) -> list:
    """One representative video per settings group among ``category``'s videos: each group's
    newest row that carries a ``start_scene`` to match on."""
    groups = _act_settings_groups(category, video_rows, require_scene=True, loop_only=loop_only)
    return [max(group, key=_created) for group in groups.values()]


def build_scene_messages(category: str, image_scene: str, representatives: list, system_prompt: str) -> list:
    """The chat messages for one situation match: the rules, then the dropped image's
    scene and each candidate video shown by the starting scene it's made for."""
    listing = "\n".join(f"{i}. {r.get('start_scene')}" for i, r in enumerate(representatives))
    user = (
        f"Desired act: {category}\n\n"
        f"The input image's scene:\n{image_scene}\n\n"
        f"Candidate {category} videos, each shown by the starting scene it is made for:\n{listing}\n\n"
        "Pick the number whose starting scene best matches the input image's "
        "situation — whether the subject is already in frame, and if so whose hand(s) are "
        "on it (hers, his, or neither). "
        'Reply with only JSON: {"choice": <the number, or -1 if none fit>}'
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


def parse_choice(completion: dict, options: list) -> str | None:
    """The chosen video's prompt_id from a chat completion, or ``None`` for none.

    ``{"choice": n}`` indexes ``options``; ``-1`` or out of range → ``None`` (a
    legitimate "none of these fit"). Raises on a reply with no usable choice, which
    the caller treats like any other model failure."""
    obj = _extract_json(completion["choices"][0]["message"]["content"])
    index = int(obj["choice"])
    if 0 <= index < len(options):
        return options[index]["prompt_id"]
    return None


def _post_chat(base_url: str, model: str, messages: list, timeout: float) -> dict:
    """POST one chat request to the local OpenAI-compatible endpoint; return its
    JSON. The single I/O boundary, at a low temperature: a lookup."""
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


def scene_matched_video(category: str, image_scene: str, video_rows, *, base_url: str,
                        model: str, system_prompt: str, timeout: float = 20.0,
                        intent: str = VIDEO) -> str | None:
    """The prompt_id of the video whose starting scene best fits the dropped
    image, or ``None`` when the act has no scored video, the model reports no fit,
    or the call fails -- and the caller falls back to :func:`most_used_video`."""
    representatives = _settings_representatives(
        category, video_rows, loop_only=intent == GENAU,
    )
    if not representatives:
        return None
    try:
        completion = _post_chat(
            base_url, model,
            build_scene_messages(category, image_scene, representatives, system_prompt),
            timeout,
        )
        chosen = parse_choice(completion, representatives)
        logger.info("act_settings: category=%s scene-match chosen=%s of %d videos",
                    category, chosen, len(representatives))
        return chosen
    except Exception as exc:  # model down / unparseable: caller falls back to most_used_video
        logger.warning("act_settings: category=%s scene-match failed (%s)", category, exc)
        return None
