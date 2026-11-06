from __future__ import annotations

import json
from collections import defaultdict

from funestra.video_families import normalized_text

from origenerator.action_vocabulary import vocabulary
from origenerator.animation_names import Animation, animation_of, named
from origenerator.content import genau_flick_word, load_content
from origenerator.media import MediaType

_CONTENT = load_content()

VIDEO = "video"
GENAU = "genau"

_CURATED_BY_INTENT: dict[str, dict] = {
    VIDEO: _CONTENT.get("pinned_kino_settings") or {},
    GENAU: _CONTENT.get("pinned_genau_settings") or {},
}


def pinned_settings(name: str, intent: str = VIDEO) -> dict | None:
    animation = named(name)
    pinned_as = (animation.name, *animation.checked) if animation.checked else (animation.action,)
    table = _CURATED_BY_INTENT.get(intent, {})
    return next((spec for said in pinned_as if (spec := _pinned_as(table, said)) is not None),
                None)


def _pinned_as(table: dict, said: str) -> dict | None:
    heard = normalized_text(said)
    spec = next((spec for key, spec in table.items() if normalized_text(key) == heard), None)
    return spec if isinstance(spec, dict) and spec.get("workflow") else None


_STARTING_WORKFLOWS = {VIDEO: "wan22_i2v", GENAU: "wan22_flf2v_loop"}


def starting_settings(intent: str) -> dict:
    return in_its_lane({"params": {"positive_prompt": "", "negative_prompt": ""}}, intent)


def in_its_lane(settings: dict, intent: str) -> dict:
    return settings if settings.get("workflow") else {**settings, "workflow": _STARTING_WORKFLOWS[intent]}


def loops(row) -> bool:
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


def _action_settings_groups(name: str, video_rows, *, loop_only: bool = False) -> dict:
    words = vocabulary(MediaType.VIDEO)
    groups = defaultdict(list)
    for row in video_rows:
        if animation_of(row, words) != name:
            continue
        if loop_only and not loops(row):
            continue
        groups[_settings_signature(row)].append(row)
    return groups


def no_past_video(action: str, lane: str) -> str:
    what = f"looping “{action}” {genau_flick_word()}" if lane == GENAU else f"“{action}” video"
    return f"no past {what} to take settings from yet"


def as_sentence(said: str) -> str:
    return said[:1].upper() + said[1:]


def available_categories(video_rows, intent: str = VIDEO, checked=()) -> set[str]:
    words = vocabulary(MediaType.VIDEO)
    made = {animation_of(row, words) for row in video_rows if intent != GENAU or loops(row)}
    return {action for action in words.buttons
            if (name := Animation(action, tuple(checked)).name) in made
            or pinned_settings(name, intent) is not None}


def most_used_video(name: str, video_rows, intent: str = VIDEO) -> str | None:
    groups = _action_settings_groups(name, video_rows, loop_only=intent == GENAU)
    if not groups:
        return None
    best = max(groups.values(), key=lambda g: (len(g), max(_created(r) for r in g)))
    return max(best, key=_created)["prompt_id"]
