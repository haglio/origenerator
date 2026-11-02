from __future__ import annotations

import json
import logging
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from origenerator.gallery.enhance_graph import graph_version_params
from origenerator.gallery.enhance_settings import (
    ENHANCE_SETTING_KEYS,
    ENHANCE_WORKFLOW,
    MATCH_SOURCE_MODEL,
    EnhanceSettings,
    describe_enhance_params,
    full_settings,
    version_settings,
)
from origenerator.gallery.groups import rows_under
from origenerator.gallery.moments import BEFORE_EVERY_RECORD, moment_of
from origenerator.gallery.output import (
    frame_names_of,
    media_type_of_row,
    output_file_reference,
    row_output_files,
)
from origenerator.gallery.signatures import _frame_name, parse_params
from origenerator.gallery.source_image import source_image_id_for
from origenerator.generation_state import GenerationSource, source_of
from origenerator.media import MediaType
from origenerator.output_files import parse_file_list, produced_output
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import (
    DEFAULT_FIX_DENOISE,
    FIX_MAX,
    FIX_STEP,
    detail_fixes_of,
    fixable_parts,
)

logger = logging.getLogger(__name__)

_ALWAYS_ENHANCED = ("sdxl_t2i", "sdxl_pose_transfer")

@dataclass(frozen=True)
class EnhanceVersion:
    index: int
    label: str
    file: dict
    params: dict = field(default_factory=dict)

    @property
    def settings(self) -> str:
        return describe_enhance_params(self.params)

    @property
    def is_original(self) -> bool:
        return self.index == 0


def original_files_of(row: dict) -> list[dict]:
    stored = parse_file_list(row.get("original_files"))
    if stored:
        return stored
    return [f for f in row_output_files(row) if f.get("role") == "original"]


def enhancement_versions(row: dict) -> list[EnhanceVersion]:
    files = row_output_files(row)
    if not files:
        return []
    history = {
        entry.get("filename"): entry
        for entry in parse_file_list(row.get("enhance_history"))
        if isinstance(entry, dict)
    }
    inline = ({} if row.get("original_files")
              else version_settings(parse_params(row.get("params_json"))))

    def versions_of(enhanced: list[dict]) -> list[EnhanceVersion]:
        count = len(enhanced)
        return [version(count - i, count, f) for i, f in enumerate(enhanced)]

    def version(index: int, count: int, f: dict) -> EnhanceVersion:
        entry = history.get(f.get("filename")) or {}
        params = entry.get("params") if isinstance(entry.get("params"), dict) else inline
        return EnhanceVersion(index, f"Enhancement {index}/{count}", f, version_settings(params))

    originals = original_files_of(row)
    if originals and len(files) > len(originals):
        versions = versions_of(files[:len(files) - len(originals)])
        versions.append(EnhanceVersion(0, "Original", originals[0]))
        return versions
    if not originals and history:
        enhanced = [f for f in files if f.get("filename") in history]
        if enhanced:
            return versions_of(enhanced)
    if is_enhanced_row(row):
        return versions_of(files[:1])
    return []


def enhanced_version_of(image_ref: str | None, image: dict) -> str | None:
    plain = {_frame_name(f.get("filename")) for f in original_files_of(image)}
    enhanced = output_file_reference(row_output_files(image))
    if _frame_name(image_ref) not in plain or _frame_name(enhanced) in plain:
        return None
    return enhanced


def is_enhanced_row(row: dict) -> bool:
    if media_type_of_row(row) != MediaType.IMAGE:
        return False
    if original_files_of(row):
        return True
    if parse_file_list(row.get("enhance_history")):
        return True
    workflow = row.get("workflow_name") or ""
    if workflow == ENHANCE_WORKFLOW:
        return True
    params = parse_params(row.get("params_json"))
    if "enhance" in params:
        return bool(params["enhance"])
    return workflow in _ALWAYS_ENHANCED and "enhance_denoise" in params


def displayed_versions(row: dict, upscale: Path | None = None) -> list[EnhanceVersion]:
    files = row_output_files(row)
    if media_type_of_row(row) != MediaType.IMAGE:
        if upscale is None or not files:
            return []
        return [EnhanceVersion(1, "Evolved", {"filename": upscale.name, "path": str(upscale)}),
                EnhanceVersion(0, "Original", files[0])]
    versions = enhancement_versions(row)
    if versions:
        return versions
    return [EnhanceVersion(0, "Original", files[0])] if files else []


def remove_enhance_versions(row: dict, filenames) -> dict:
    doomed = {name for name in filenames if name}
    files = row_output_files(row)
    kept = [f for f in files if f.get("filename") not in doomed]
    if len(kept) == len(files) or not kept:
        return {}
    originals = [f for f in parse_file_list(row.get("original_files"))
                 if f.get("filename") not in doomed]
    history = [e for e in parse_file_list(row.get("enhance_history"))
               if isinstance(e, dict) and e.get("filename") not in doomed]
    original_names = {f.get("filename") for f in original_files_of(row)}
    if not [f for f in kept if f.get("filename") not in original_names]:
        originals, history = [], []
        kept = [{k: v for k, v in f.items() if k != "role"} for f in kept]
    return {
        "output_files": json.dumps(kept),
        "original_files": json.dumps(originals) if originals else None,
        "enhance_history": json.dumps(history) if history else None,
    }


def is_enhanceable_row(row: dict) -> bool:
    return media_type_of_row(row) == MediaType.IMAGE and produced_output(row)


def enhance_target_id(enhance_row: dict, image_rows) -> str | None:
    stamped = enhance_row.get("enhance_of")
    if stamped:
        return stamped if any(r.get("prompt_id") == stamped for r in image_rows) else None
    input_image = parse_params(enhance_row.get("params_json")).get("input_image")
    candidates = [r for r in image_rows if r.get("prompt_id") != enhance_row.get("prompt_id")]
    return source_image_id_for(input_image, candidates)


def enhance_run_targets_row(enhance_of: str | None, input_image: str | None,
                            row: dict) -> bool:
    if enhance_of:
        return row.get("prompt_id") == enhance_of
    return enhance_targets_row(input_image, row)


def _enhances_in_flight(rows) -> tuple[set[str], set[str]]:
    ids, names = set(), set()
    for row in rows:
        if (row.get("workflow_name") or "") != ENHANCE_WORKFLOW:
            continue
        if row.get("enhance_of"):
            ids.add(row["enhance_of"])
            continue
        name = _frame_name(parse_params(row.get("params_json")).get("input_image"))
        if name:
            names.add(name)
    return ids, names


def version_matching_settings(row: dict, settings: EnhanceSettings | None) -> int | None:
    return version_matching_params(row, enhance_params_for(row, settings))


def version_matching_params(row: dict, wanted: dict | None) -> int | None:
    if wanted is None:
        return None
    for position, version in enumerate(enhancement_versions(row)):
        if version.params and same_enhancement(version.params, wanted):
            return position
    return None


def same_enhancement(params: dict, other: dict) -> bool:
    return full_settings(params) == full_settings(other)


def most_used_enhancements(rows, count: int) -> list[dict]:
    uses = Counter(json.dumps(_settings_as_offered(row, version.params), sort_keys=True)
                   for row in rows for version in enhancement_versions(row) if version.params)
    return [json.loads(settings) for settings, _uses in uses.most_common(count)]


def _settings_as_offered(row: dict, params: dict) -> dict:
    held_on_the_pane = full_settings(params)
    if held_on_the_pane["checkpoint"] == model_matching_the_source(row):
        held_on_the_pane["checkpoint"] = MATCH_SOURCE_MODEL
    return full_settings(held_on_the_pane)


def model_matching_the_source(row: dict) -> str:
    checkpoint = parse_params(row.get("params_json")).get("checkpoint")
    if isinstance(checkpoint, str) and checkpoint:
        return checkpoint
    return WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params()["checkpoint"]


def models_matching_the_sources(rows) -> frozenset[str]:
    return frozenset(model_matching_the_source(row) for row in rows if is_enhanceable_row(row))


def models_matching_a_folders_sources(folder) -> frozenset[str] | None:
    if folder is None:
        return None
    models: set[str] = set()
    for row in rows_under(folder):
        if is_enhanceable_row(row):
            models.add(model_matching_the_source(row))
            if len(models) > 1:
                return None
    return frozenset(models)


def enhance_targets_row(input_image: str | None, row: dict) -> bool:
    name = _frame_name(input_image)
    if not name:
        return False
    return name in {_frame_name(f.get("filename")) for f in row_output_files(row)}


def enhancement_recency(rows) -> dict[str, tuple[datetime, int]]:
    holders: dict[str, str] = {}
    for row in rows:
        if media_type_of_row(row) != MediaType.IMAGE:
            continue
        for name in frame_names_of(row.get("output_files")):
            holders.setdefault(name, row.get("prompt_id"))
    recency: dict[str, tuple[datetime, int]] = {}
    asked = sorted((row["id"], row["created_at"]) for row in rows
                   if isinstance(row.get("id"), int) and row.get("created_at"))
    asked_ids = [row_id for row_id, _stamp in asked]

    def asked_around(run_id):
        next_asked = min(bisect_left(asked_ids, run_id), len(asked) - 1)
        return asked[next_asked][1] if asked else None

    def note(prompt_id, finished, run_id):
        if isinstance(run_id, int):
            recency[prompt_id] = max(recency.get(prompt_id, (BEFORE_EVERY_RECORD, 0)),
                                     (moment_of(finished or asked_around(run_id)), run_id))

    for row in rows:
        if (row.get("workflow_name") or "") == ENHANCE_WORKFLOW and moves_its_image(row):
            target = row.get("enhance_of")
            if not target:
                name = _frame_name(parse_params(row.get("params_json")).get("input_image"))
                target = holders.get(name) if name else None
            if target is not None and target != row.get("prompt_id"):
                note(target, row.get("completed_at"), row.get("id"))
        for entry in parse_file_list(row.get("enhance_history")):
            if isinstance(entry, dict):
                note(row.get("prompt_id"), entry.get("finished_at"), entry.get("run_id"))
    return recency


def moves_its_image(enhance_row: dict) -> bool:
    return source_of(enhance_row) != GenerationSource.BACKFILL


def rows_awaiting_enhancement(folder_rows, enhance_rows) -> list[dict]:
    in_flight_ids, in_flight_names = _enhances_in_flight(enhance_rows)
    awaiting = []
    for row in folder_rows:
        if not is_enhanceable_row(row) or is_enhanced_row(row):
            continue
        if row.get("prompt_id") in in_flight_ids:
            continue
        names = {_frame_name(f.get("filename")) for f in row_output_files(row)}
        if names & in_flight_names:
            continue
        awaiting.append(row)
    return awaiting


def enhance_params_for(row: dict, settings: EnhanceSettings | None = None) -> dict | None:
    files = original_files_of(row) or row_output_files(row)
    input_ref = output_file_reference(files)
    if input_ref is None:
        return None
    params = dict(WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params())
    src = parse_params(row.get("params_json"))
    params["input_image"] = input_ref
    params["positive_prompt"] = src.get("positive_prompt") or row.get("positive_prompt") or ""
    params["negative_prompt"] = src.get("negative_prompt") or row.get("negative_prompt") or ""
    params["checkpoint"] = model_matching_the_source(row)
    for key, value in (settings.params if settings else {}).items():
        if key not in ENHANCE_SETTING_KEYS:
            continue
        if key == "checkpoint" and value == MATCH_SOURCE_MODEL:
            continue
        params[key] = value
    return params


def fix_params_for(row: dict, parts, settings: EnhanceSettings | None = None) -> dict | None:
    wanted = fixable_parts(parts)
    if not wanted:
        return None
    newest = next((lvl for lvl in enhancement_versions(row)
                   if not lvl.is_original and lvl.params), None)
    base = EnhanceSettings(params=dict(newest.params)) if newest is not None else settings
    params = enhance_params_for(row, base)
    if params is None:
        return None
    configured = detail_fixes_of(settings.params if settings else {})
    already = detail_fixes_of(newest.params) if newest is not None else {}
    params["enhance_detail_fixes"] = dict(already, **{
        part.name: (min(round(already[part.name] + FIX_STEP, 2), FIX_MAX)
                    if part.name in already
                    else configured.get(part.name, DEFAULT_FIX_DENOISE))
        for part in wanted})
    asked = {part.name for part in wanted}
    carried = (newest.params.get("enhance_fix_prompts") if newest is not None else None) or {}
    given = (settings.params.get("enhance_fix_prompts") if settings else None) or {}
    params["enhance_fix_prompts"] = {
        **{name: prompts for name, prompts in carried.items() if name not in asked},
        **{name: prompts for name, prompts in given.items() if name in asked},
    }
    return params


def enhance_file_stem() -> str:
    prefix = WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params().get(
        "filename_prefix", "")
    return str(prefix).rsplit("/", 1)[-1]


def is_enhance_product_row(row: dict) -> bool:
    if row.get("source") == GenerationSource.BASE_RENDER:
        return False
    if original_files_of(row) or parse_file_list(row.get("enhance_history")):
        return False
    files = row_output_files(row)
    if not files:
        return False
    stem = enhance_file_stem()
    return all((f.get("filename") or "").startswith(f"{stem}_") for f in files)


def enhance_version_params(row: dict) -> dict:
    params = parse_params(row.get("params_json"))
    version = version_settings(params)
    for key, value in graph_version_params(row, ENHANCE_SETTING_KEYS).items():
        version.setdefault(key, value)
    return version
