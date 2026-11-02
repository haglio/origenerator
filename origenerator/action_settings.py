from __future__ import annotations

import json
from collections import defaultdict

from origenerator.content import genau_flick_word, load_content

_CONTENT = load_content()

CATEGORIES: tuple[str, ...] = tuple(_CONTENT["actions"])

VIDEO = "video"
GENAU = "genau"

_CURATED_BY_INTENT: dict[str, dict] = {
    VIDEO: _CONTENT.get("pinned_kino_settings") or {},
    GENAU: _CONTENT.get("pinned_genau_settings") or {},
}


def pinned_settings(category: str, intent: str = VIDEO) -> dict | None:
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
    # Deferred: the workflow registry import pulls in the whole workflow package
    from origenerator.workflows import WORKFLOW_REGISTRY  # noqa: PLC0415 — keeps this module light

    workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
    return bool(workflow and workflow.looping)


def lane_of(row) -> str:
    return GENAU if loops(row) else VIDEO

_SETTINGS_EXCLUDE = frozenset((
    "positive_prompt", "negative_prompt", "input_image",
    "seed", "noise_seed", "filename_prefix", "batch_size",
    "width", "height", "length", "frame_count", "frame_rate",
    "start_at_step", "end_at_step",
))


def _hashable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _settings_signature(row: dict):
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
    return row.get("created_at") or ""


def _action_settings_groups(category: str, video_rows, *, loop_only: bool = False) -> dict:
    groups = defaultdict(list)
    for row in video_rows:
        if action_of(row) != category:
            continue
        if loop_only and not loops(row):
            continue
        groups[_settings_signature(row)].append(row)
    return groups


def action_of(row: dict) -> str:
    return row.get("action") or row.get("image_state") or ""


def no_past_video(action: str, lane: str) -> str:
    what = f"looping “{action}” {genau_flick_word()}" if lane == GENAU else f"“{action}” video"
    return f"no past {what} to take settings from yet"


def as_sentence(said: str) -> str:
    return said[:1].upper() + said[1:]


def available_categories(video_rows, intent: str = VIDEO) -> set[str]:
    loop_only = intent == GENAU
    return {c for c in CATEGORIES
            if pinned_settings(c, intent) is not None
            or any(action_of(row) == c and (not loop_only or loops(row))
                   for row in video_rows)}


def most_used_video(category: str, video_rows, intent: str = VIDEO) -> str | None:
    groups = _action_settings_groups(category, video_rows, loop_only=intent == GENAU)
    if not groups:
        return None
    best = max(groups.values(), key=lambda g: (len(g), max(_created(r) for r in g)))
    return max(best, key=_created)["prompt_id"]
