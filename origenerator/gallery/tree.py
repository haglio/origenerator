from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app_support.gallery_rows import source_of

from origenerator.gallery.enhance import enhancement_recency
from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW
from origenerator.gallery.groups import (
    AllGroup,
    LoraGroup,
    MediaGroup,
    ModelGroup,
    SettingsGroup,
    SourceImageGroup,
    WorkflowGroup,
    child_groups,
    rows_under,
)
from origenerator.gallery.keys import (
    folder_id,
    lora_key,
    model_key,
    settings_key,
    source_image_key,
)
from origenerator.gallery.labels import (
    _source_image_label,
    item_type_label,
    lora_label,
    model_label,
    workflow_label,
)
from origenerator.gallery.moments import BEFORE_EVERY_RECORD, moment_of
from origenerator.gallery.non_ai import leaf_folder_label
from origenerator.gallery.output import (
    is_in_progress,
    item_type_of,
    makes_flicks,
    media_type_of_row,
)
from origenerator.gallery.signatures import (
    _grouping_version,
    _input_image_config,
    canonical_settings,
    enhance_settings,
    folder_signature,
    is_image_conditioned,
    lora_signature,
    made_from_an_image,
    model_signature,
    parse_params,
    settings_only,
    start_image_entry,
)
from origenerator.gallery.source_image import build_image_config_index
from origenerator.generation_state import GenerationSource, in_sight
from origenerator.media import ItemType, MediaType
from origenerator.output_files import produced_output
from origenerator.workflows.non_ai import FOLDER_KINDS, folder_kind, non_ai_folder


def _group_by_creation(newest_first, key):
    oldest_first: dict = {}
    for row in reversed(newest_first):
        oldest_first.setdefault(key(row), []).append(row)
    return [(k, rows[::-1]) for k, rows in reversed(oldest_first.items())]


def in_alphabetical_order(folders: list) -> list:
    return sorted(folders, key=lambda folder: (folder.label.startswith("("), folder.label.casefold()))


def settings_folder_key(row: dict, image_index: dict | None = None) -> str:
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    return settings_key(
        media_type, workflow_name,
        folder_signature(workflow_name, row.get("params_json"), image_index,
                         workflow_version=row.get("workflow_version")),
    )



def folder_key_for(workflow_name: str, params: dict, image_index: dict | None = None,
                   workflow_version: str | None = None) -> str:
    row = {"workflow_name": workflow_name, "params_json": json.dumps(params)}
    if workflow_version is not None:
        row["workflow_version"] = workflow_version
    return settings_folder_key(row, image_index)

def folder_key_at_level(row: dict, level: str, image_index: dict | None = None) -> str:
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    params_json = row.get("params_json")
    if level == "media":
        return item_type_of(row)
    if level == "workflow":
        return f"{media_type}/{workflow_name}"
    if level == "model":
        return model_key(media_type, workflow_name, model_signature(workflow_name, params_json))
    if level == "lora":
        return lora_key(media_type, workflow_name, _lora_place(workflow_name, params_json))
    if level == "source_image":
        return source_image_key(media_type, workflow_name,
                                _source_image_place(workflow_name, params_json, image_index))
    if level == "settings":
        return settings_folder_key(row, image_index)
    raise ValueError(f"unknown folder level: {level!r}")


def media_folder_holding(key: str) -> str:
    filed_as, _, below = key.partition("/")
    a_flick_s = filed_as == MediaType.VIDEO and any(
        makes_flicks(name) for name in (below, below.rpartition("/")[0]) if name)
    return ItemType.FLICK if a_flick_s else filed_as


def folder_chain(row: dict, image_index: dict | None = None) -> tuple[str, ...]:
    workflow_name = row.get("workflow_name") or "unknown"
    levels = ("media", "workflow", *_levels_between(media_type_of_row(row), workflow_name),
              "settings")
    return (ALL_KEY, *(folder_key_at_level(row, level, image_index) for level in levels))


def _levels_between(media_type: str, workflow_name: str) -> tuple[str, ...]:
    if not _files_by_model_and_lora(workflow_name):
        return ()
    return ("model", "lora",
            *(("source_image",) if _grows_source_images(media_type, workflow_name) else ()))


def _files_by_model_and_lora(workflow_name: str) -> bool:
    return non_ai_folder(workflow_name) is None


def _grows_source_images(media_type: str, workflow_name: str) -> bool:
    return media_type == MediaType.VIDEO and made_from_an_image(workflow_name)


def _lora_place(workflow_name: str, params_json: str | None) -> str:
    return json.dumps([model_signature(workflow_name, params_json),
                       lora_signature(workflow_name, params_json)])


def _source_image_place(workflow_name: str, params_json: str | None,
                        image_index: dict | None) -> str:
    image = _input_image_config(parse_params(params_json).get("input_image"), image_index,
                                identify=True)
    return json.dumps([_lora_place(workflow_name, params_json), image])


def legacy_parentless_folder_key(row: dict, level: str, image_index: dict | None = None) -> str:
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    params_json = row.get("params_json")
    if level == "lora":
        return lora_key(media_type, workflow_name, lora_signature(workflow_name, params_json))
    return source_image_key(media_type, workflow_name, _input_image_config(
        parse_params(params_json).get("input_image"), image_index, identify=True))


def legacy_settings_folder_key(row: dict) -> str:
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(settings_only(parse_params(row.get("params_json"))), sort_keys=True)
    return settings_key(media_type, workflow_name, signature)


def _preenhance_settings(workflow_name: str, params: dict) -> dict:
    return {
        **canonical_settings(workflow_name, params),
        **enhance_settings(workflow_name, params),
    }


def legacy_preframe_settings_folder_key(row: dict) -> str:
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(
        _preenhance_settings(workflow_name, parse_params(row.get("params_json"))),
        sort_keys=True, default=str,
    )
    return settings_key(media_type, workflow_name, signature)


def legacy_preversion_settings_folder_key(row: dict, image_index: dict | None = None) -> str:
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    params = parse_params(row.get("params_json"))
    settings = _preenhance_settings(workflow_name, params)
    if is_image_conditioned(workflow_name):
        settings = {
            **settings,
            "input_image_config": _input_image_config(params.get("input_image"), image_index),
        }
    signature = json.dumps(settings, sort_keys=True, default=str)
    return settings_key(media_type, workflow_name, signature)


def legacy_preenhance_settings_folder_keys(rows, image_index: dict | None = None) -> set[str]:
    keys = set()
    for row in rows:
        media_type = media_type_of_row(row)
        workflow_name = row.get("workflow_name") or "unknown"
        params = parse_params(row.get("params_json"))
        settings = {
            **_preenhance_settings(workflow_name, params),
            "workflow_version": _grouping_version(workflow_name, row.get("workflow_version")),
        }
        if is_image_conditioned(workflow_name):
            settings = {
                **settings,
                "input_image_config": _input_image_config(params.get("input_image"), image_index),
            }
        keys.add(settings_key(media_type, workflow_name,
                               json.dumps(settings, sort_keys=True, default=str)))
    return keys


def _overlay(label: str, key: str, folder_meta: dict) -> tuple[str, bool]:
    meta = folder_meta.get(key, {})
    return (meta.get("custom_name") or label, bool(meta.get("starred")))


def _folders_where(tree: list, wanted: Callable[[object], bool]) -> list:
    found: list = []

    def walk(groups):
        for group in groups:
            if wanted(group):
                found.append(group)
            walk(child_groups(group))

    walk(tree)
    return found


def favorite_folders(tree: list[MediaGroup]) -> list:
    return _folders_where(tree, lambda group: group.favorite)


def leaf_folders(tree: list[MediaGroup]) -> list[SettingsGroup]:
    return _folders_where(tree, lambda group: isinstance(group, SettingsGroup))


_HOLDING_EVERYTHING = (AllGroup, MediaGroup)


@dataclass(frozen=True)
class NamedFolder:
    key: str
    name: str
    prompt_ids: tuple[str, ...]


def named_folders(
    tree: list, folder_meta: dict[str, dict] | None = None, custom_collections=()
) -> list[NamedFolder]:
    folders: list[NamedFolder] = []
    folder_meta = folder_meta or {}

    def name(group, label: str):
        folders.append(NamedFolder(group.key, label,
                                   tuple(row["prompt_id"] for row in rows_under(group))))

    def walk(groups):
        for group in groups:
            label = folder_meta.get(group.key, {}).get("custom_name")
            if not label and not isinstance(group, _HOLDING_EVERYTHING):
                label = group.label
            if label:
                name(group, label)
            walk(child_groups(group))

    walk(tree)
    for folder in custom_collections:
        name(folder, folder.label)
    return folders


def recent_generations(rows: list[dict], *, bumped=None) -> list[dict]:
    listed = [
        row for row in rows
        if source_of(row) != GenerationSource.EXPERIMENT and in_sight(row)
        and produced_output(row)
    ]
    if bumped is None:
        bumped = enhancement_recency(rows)
    return sorted(listed, reverse=True, key=lambda row: row_recency(row, bumped))


def row_recency(row: dict, bumped: dict[str, tuple[datetime, int]]) -> tuple[datetime, int]:
    enhanced_at, enhanced_by = bumped.get(row.get("prompt_id"), (BEFORE_EVERY_RECORD, 0))
    return (max(_joined_the_library_at(row), enhanced_at),
            max(row.get("id") or 0, enhanced_by))


def _joined_the_library_at(row: dict) -> datetime:
    found_on_disk = source_of(row) == GenerationSource.IMPORTED
    return moment_of(row.get("created_at") if found_on_disk else row.get("completed_at"))


FOLDERS_A_SITTING_REACHES = 20


def recently_worked_folders(
    trees: dict[str, list], rows: list[dict], limit: int = FOLDERS_A_SITTING_REACHES,
    *, bumped=None,
) -> set[tuple[str, str]]:
    if bumped is None:
        bumped = enhancement_recency(rows)
    ranked: list[tuple[tuple[datetime, int], tuple[str, str]]] = []

    def walk(group, shape: str) -> None:
        children = child_groups(group)
        if children:
            for child in children:
                walk(child, shape)
            return
        freshest = max(
            (row_recency(row, bumped) for row in getattr(group, "rows", ())),
            default=None,
        )
        if freshest is not None:
            ranked.append((freshest, (shape, group.key)))

    for shape, model in trees.items():
        for group in model:
            walk(group, shape)
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    return {folder for _freshest, folder in ranked[:limit]}


def favorite_generations(newest_first: list[dict]) -> list[dict]:
    return [row for row in newest_first if row.get("starred") and produced_output(row)]


def enhanced_generations(rows: list[dict], is_enhanced) -> list[dict]:
    return [row for row in placeable_rows(rows) if produced_output(row) and is_enhanced(row)]


def unreviewed_experiments(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if row.get("source") == GenerationSource.EXPERIMENT
        and row.get("experiment_verdict") is None
        and produced_output(row)
    ]


@dataclass(frozen=True)
class _Tier:
    media_type: str
    workflow_name: str
    folder_meta: dict
    image_index: dict
    name_of: Callable[[str], str]
    kept: KeptFolders

    def kept_folder(self, key, rows: list[dict], make: Callable, *made_from):
        return self.kept.kept(key, rows, make, *made_from,
                              depends_on=self._start_images_of(rows))

    def _start_images_of(self, rows: list[dict]) -> tuple:
        if not made_from_an_image(self.workflow_name):
            return ()
        entries = (start_image_entry(row.get("params_json"), self.image_index) for row in rows)
        return tuple((entry, entry and self.name_of(entry.prompt_id)) for entry in entries)


def _leaf_label(workflow_name: str, key: str, rows: list[dict]) -> str:
    if non_ai_folder(workflow_name) is None:
        return folder_id(key)
    return leaf_folder_label(rows[0])


def _build_settings_groups(tier: _Tier, rows: list[dict]) -> list[SettingsGroup]:
    grouped = _group_by_creation(
        rows, lambda r: folder_signature(tier.workflow_name, r.get("params_json"),
                                         tier.image_index,
                                         workflow_version=r.get("workflow_version"))
    )
    groups = []
    for sig, sig_rows in grouped:
        key = settings_key(tier.media_type, tier.workflow_name, sig)
        label, favorite = _overlay(_leaf_label(tier.workflow_name, key, sig_rows), key,
                                   tier.folder_meta)
        groups.append(tier.kept_folder(key, sig_rows, SettingsGroup, key, label, sig_rows, favorite))
    return groups


@dataclass(frozen=True)
class _Level:
    cls: type
    signature: Callable
    key_for: Callable
    label_for: Callable
    children_for: Callable


def _grouped_folders(tier: _Tier, rows, level: _Level):
    groups = []
    for sig, sub_rows in _group_by_creation(rows, level.signature):
        key = level.key_for(sig)
        groups.append(tier.kept_folder(key, sub_rows, _folder_at, tier, level, key, sub_rows))
    return groups


def _folder_at(tier: _Tier, level: _Level, key, rows: list[dict]):
    params = parse_params(rows[0].get("params_json"))
    label, favorite = _overlay(level.label_for(params), key, tier.folder_meta)
    return level.cls(key, label, level.children_for(rows), favorite)


def _build_model_groups(tier: _Tier, rows: list[dict]) -> list[ModelGroup]:
    return in_alphabetical_order(_grouped_folders(tier, rows, _Level(
        cls=ModelGroup,
        signature=lambda r: model_signature(tier.workflow_name, r.get("params_json")),
        key_for=lambda sig: model_key(tier.media_type, tier.workflow_name, sig),
        label_for=lambda params: model_label(tier.workflow_name, params),
        children_for=lambda sub: _build_lora_groups(tier, sub),
    )))


def _build_lora_groups(tier: _Tier, rows: list[dict]) -> list[LoraGroup]:
    return in_alphabetical_order(_grouped_folders(tier, rows, _Level(
        cls=LoraGroup,
        signature=lambda r: _lora_place(tier.workflow_name, r.get("params_json")),
        key_for=lambda sig: lora_key(tier.media_type, tier.workflow_name, sig),
        label_for=lambda params: lora_label(tier.workflow_name, params),
        children_for=lambda sub: _build_leaves(tier, sub),
    )))


def _build_leaves(tier: _Tier, rows: list[dict]) -> list:
    if _grows_source_images(tier.media_type, tier.workflow_name):
        return _build_source_image_groups(tier, rows)
    return _build_settings_groups(tier, rows)


def _build_source_image_groups(tier: _Tier, rows: list[dict]) -> list[SourceImageGroup]:
    return _grouped_folders(tier, rows, _Level(
        cls=SourceImageGroup,
        signature=lambda r: _source_image_place(tier.workflow_name, r.get("params_json"),
                                                tier.image_index),
        key_for=lambda sig: source_image_key(tier.media_type, tier.workflow_name, sig),
        label_for=lambda params: _source_image_label(params, tier.image_index, tier.name_of),
        children_for=lambda sub: _build_settings_groups(tier, sub),
    ))


def placeable_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows_with_a_folder(rows) if in_sight(row)]


def is_an_enhance_being_made(row: dict) -> bool:
    return row.get("workflow_name") == ENHANCE_WORKFLOW and is_in_progress(row)


def rows_with_a_folder(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if (produced_output(row) or is_in_progress(row))
        and not is_an_enhance_being_made(row)
        and row.get("source") != GenerationSource.BASE_RENDER
    ]


def start_frame_index(rows: list[dict]) -> dict:
    return build_image_config_index(
        [row for row in rows_with_a_folder(rows)
         if media_type_of_row(row) == MediaType.IMAGE and produced_output(row)]
    )


class KeptFolders:
    def __init__(self, before: KeptFolders | None = None, *, drawn_with: tuple = (),
                 named_with: object = None):
        self.drawn_with = drawn_with
        self.named_with = named_with
        self._before: dict = before.folders_drawn_with(drawn_with) if before is not None else {}
        self._now: dict = {}

    def folders_drawn_with(self, drawn_with: tuple) -> dict:
        return self._now if all_the_same(self.drawn_with, drawn_with) else {}

    def kept(self, key, parts: list, make: Callable, *made_from, depends_on: tuple = ()):
        before = self._before.get(key)
        same = (before is not None and all_the_same(before[0], parts)
                and before[1] == depends_on)
        folder = before[2] if same else make(*made_from)
        self._now[key] = (parts, depends_on, folder)
        return folder


def all_the_same(these, those) -> bool:
    return len(these) == len(those) and all(this is that for this, that in zip(these, those, strict=True))


def build_gallery_tree(
    rows: list[dict], folder_meta: dict[str, dict] | None = None,
    *, image_index: dict | None = None,
    name_of: Callable[[str], str] | None = None,
    kept: KeptFolders | None = None,
) -> list[MediaGroup]:
    folder_meta = folder_meta or {}
    if image_index is None:
        image_index = start_frame_index(rows)
    kept = kept or KeptFolders()
    rows = placeable_rows(rows)
    by_type = dict(_group_by_creation(rows, item_type_of))
    media = [_media_folder(item_type, by_type[item_type], folder_meta, image_index,
                           name_of or _unnamed, kept)
             for item_type in ItemType if item_type in by_type]
    return kept.kept("tree", media, list, media)


def _media_folder(item_type: ItemType, rows, folder_meta, image_index, name_of,
                  kept) -> MediaGroup:
    label, favorite = _overlay(item_type_label(item_type), item_type, folder_meta)
    media_type = item_type.filed_as
    workflows = []
    for wf_name, wf_rows in _group_by_creation(
        rows, lambda r: r.get("workflow_name") or "unknown"
    ):
        wf_key = f"{media_type}/{wf_name}"
        wf_label, wf_favorite = _overlay(workflow_label(wf_name), wf_key, folder_meta)
        tier = _Tier(media_type, wf_name, folder_meta, image_index, name_of, kept)
        workflows.append(tier.kept_folder(wf_key, wf_rows, _workflow_folder,
                                          tier, wf_key, wf_label, wf_rows, wf_favorite))
    workflows = sorted(in_alphabetical_order(workflows),
                       key=lambda workflow: FOLDER_KINDS.index(folder_kind(workflow.workflow_name)))
    return kept.kept(str(item_type), workflows, MediaGroup, str(item_type), label, workflows,
                     favorite)


def _workflow_folder(tier: _Tier, key: str, label: str, rows: list[dict],
                     favorite: bool) -> WorkflowGroup:
    below = (_build_model_groups if _files_by_model_and_lora(tier.workflow_name)
             else _build_settings_groups)
    return WorkflowGroup(key, tier.workflow_name, label, below(tier, rows), favorite)


def _unnamed(_prompt_id: str) -> str:
    return ""


ALL_KEY = "__all__"
ALL_LABEL = "All"


def all_group(tree_model, folder_meta: dict[str, dict] | None = None) -> AllGroup:
    label, favorite = _overlay(ALL_LABEL, ALL_KEY, folder_meta or {})
    return AllGroup(ALL_KEY, label, list(tree_model), favorite)
