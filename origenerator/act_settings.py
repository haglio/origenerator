"""Pick the settings for a dropdown act, mined from the gallery.

An act's videos are the ones launched as that act, grouped by their settings, and the
chosen one supplies its full params to re-run on a dropped image.
:func:`most_used_video` is the act's most-used; :func:`pinned_settings` sits above it,
for an act the overlay pins; :func:`available_categories` says which acts either
could answer; :func:`starting_settings` is the lane's own workflow as it starts.
Each is asked for one lane, its *intent*: :data:`VIDEO` or :data:`GENAU`.
"""
from __future__ import annotations

import json
from collections import defaultdict

from origenerator.content import genau_flick_word, load_content

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


_STARTING_WORKFLOWS = {VIDEO: "wan22_i2v", GENAU: "wan22_flf2v_loop"}


def starting_settings(intent: str) -> dict:
    return in_its_lane({"params": {"positive_prompt": "", "negative_prompt": ""}}, intent)


def in_its_lane(settings: dict, intent: str) -> dict:
    return settings if settings.get("workflow") else {**settings, "workflow": _STARTING_WORKFLOWS[intent]}


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


def _act_settings_groups(category: str, video_rows, *, loop_only: bool = False) -> dict:
    """The act's videos grouped by settings signature; ``loop_only`` keeps just the
    ones a looping workflow made (see :func:`loops`)."""
    groups = defaultdict(list)
    for row in video_rows:
        if act_of(row) != category:
            continue
        if loop_only and not loops(row):
            continue
        groups[_settings_signature(row)].append(row)
    return groups


def act_of(row: dict) -> str:
    """The act ``row`` shows, because somebody said so: a video's is the act it was
    launched as, a picture's the action it was sorted as, and "" means nobody has
    said. Never read off the prompt."""
    return row.get("act") or row.get("picture_state") or ""


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
