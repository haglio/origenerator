"""Nest a flat list of generations into the gallery's folder tree.

The gallery view organizes generations as nested folders: Images or
Videos -> workflow -> model -> LoRA -> [source image] -> settings group
(rows sharing every setting except per-instance ones: the seed,
and — for an I2V workflow — the specific start-frame *file*. A re-roll
regenerates that frame, so the raw filename is per-instance; but the
*configuration* that produced the frame is not, so it is folded back into the
settings key. Two i2v videos built from re-rolls of one image stay together,
while two built from differently configured images split apart. The enhance
tail's params are excluded too, so an enhanced render and its unenhanced twin
land in one folder — enhancement is a finish on an image, not another image).

A workflow that has produced both kinds gets a folder under each. That split
is what lets the source-image level stay a property of *videos* alone: it
grows under a video workflow folder, while a still an image-conditioned workflow
happened to output (an imported PNG under a video prefix) sits under Images and
is grouped like any other image.

Each level below the workflow is a *projection* of that settings key onto one
facet, splitting a folder into sub-folders that differ in that facet alone: model
(always), LoRA (always — collapsed to a single "(no LoRA)" folder when the
workflow declares no LoRA keys, so every branch nests the same depth), and — for
videos — the source image a video animates, i.e. which image its start frame is
(:func:`_input_image_config`). The settings group is the full key, so it nests
beneath every projection. This module owns the grouping logic with no Qt
dependency so it can be unit-tested directly.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from origenerator.gallery.enhance import enhancement_recency, is_enhanced_row
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
    MEDIA_LABELS,
    _source_image_label,
    lora_label,
    model_label,
    workflow_label,
)
from origenerator.gallery.moments import BEFORE_EVERY_RECORD, moment_of
from origenerator.gallery.output import (
    is_in_progress,
    media_type_of_row,
    produced_output,
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
)
from origenerator.gallery.source_image import build_image_config_index
from origenerator.generation_state import GenerationSource, in_sight, source_of
from origenerator.media import MediaType


def _group_by_creation(newest_first, key):
    oldest_first: dict = {}
    for row in reversed(newest_first):
        oldest_first.setdefault(key(row), []).append(row)
    return [(k, rows[::-1]) for k, rows in reversed(oldest_first.items())]


def settings_folder_key(row: dict, image_index: dict | None = None) -> str:
    """The key of the settings-folder leaf a row belongs to in the gallery tree.

    Mirrors how :func:`build_gallery_tree` keys that leaf — media type, workflow
    name, folder signature — so an in-flight row (which has no output yet and so
    never appears in the tree itself) can still be matched to the folder it joins.
    ``image_index`` must be the same one the tree was built with (see
    :func:`build_image_config_index`) so an image-conditioned row keys to the same
    leaf its start frame's configuration places it in.
    """
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
    """The key of the ``level``-tier folder ``row`` belongs to, recomputed from the
    row under the *current* key formulas.

    A favorite stores its tier and a representative row under it; recomputing here
    re-derives the folder's key so a star or custom name follows the folder even
    after a key formula changes — the silent orphaning the reconcile undoes.
    ``image_index`` (see :func:`build_image_config_index`) lets the source-image
    and settings tiers resolve an image-conditioned row's start-frame config the
    way the tree does."""
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    params_json = row.get("params_json")
    if level == "media":
        return media_type
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


def folder_chain(row: dict, image_index: dict | None = None) -> tuple[str, ...]:
    workflow_name = row.get("workflow_name") or "unknown"
    levels = ("media", "workflow", "model", "lora",
              *(("source_image",) if _grows_source_images(media_type_of_row(row), workflow_name)
                else ()),
              "settings")
    return (ALL_KEY, *(folder_key_at_level(row, level, image_index) for level in levels))


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
    """The settings-folder key ``row`` had under the pre-normalization formula:
    ``settings_only`` hashed with sort_keys, before :func:`canonical_settings`.

    One historical key formula shift that orphaned favorites made before it. The
    reconcile recomputes this to re-point such a stale star or name onto the row's
    current settings folder."""
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(settings_only(parse_params(row.get("params_json"))), sort_keys=True)
    return settings_key(media_type, workflow_name, signature)


def _preenhance_settings(workflow_name: str, params: dict) -> dict:
    """A row's settings the way every formula predating the enhancement split
    computed them: the settings with the enhance tail's params still folded in.

    Each legacy key below is a snapshot of a formula that ran while enhancement
    was part of a row's identity, so all three rebuild from this rather than from
    :func:`canonical_settings`, which no longer carries those params."""
    return {
        **canonical_settings(workflow_name, params),
        **enhance_settings(workflow_name, params),
    }


def legacy_preframe_settings_folder_key(row: dict) -> str:
    """The settings-folder key an image-conditioned row had before its start
    frame's configuration was folded into the key — :func:`canonical_settings`
    hashed with the input image dropped entirely (the pre-frame-config formula).

    The reconcile recomputes this to re-point a star or name made before that
    change onto the row's current settings folder."""
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(
        _preenhance_settings(workflow_name, parse_params(row.get("params_json"))),
        sort_keys=True, default=str,
    )
    return settings_key(media_type, workflow_name, signature)


def legacy_preversion_settings_folder_key(row: dict, image_index: dict | None = None) -> str:
    """The settings-folder key ``row`` had before the workflow generation was
    folded into the signature: canonical settings plus (for an image-conditioned
    row) its start-frame configuration, but no ``workflow_version``.

    The third historical formula shift. The reconcile recomputes this to
    re-point a star or name made under it — one made since the last reconcile,
    so its stored identity was never backfilled — onto the row's current
    settings folder. Equal to :func:`legacy_preframe_settings_folder_key` for
    workflows that aren't image-conditioned."""
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
    """The settings-folder keys a folder's ``rows`` were split across before
    the enhancement layer left the signature: today's key with the enhance tail's
    params folded back in.

    The fourth historical formula shift, and the only one that *merged* folders —
    an enhanced render and its unenhanced twin used to be two. So this takes the
    whole row list and returns a key per distinct enhance setting found among
    them, rather than one key from a single row: a star sitting on either old
    folder must find its way to the merged one. The reconcile recomputes these to
    re-point a star or name made under that formula — one made since the last
    reconcile, so its stored identity was never backfilled."""
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
    """Apply a folder's saved custom name and star, returning (label, favorited)."""
    meta = folder_meta.get(key, {})
    return (meta.get("custom_name") or label, bool(meta.get("starred")))


def favorite_folders(tree: list[MediaGroup]) -> list:
    """Every favorited folder in ``tree``, at any depth, in top-down tree order.

    Powers the gallery's Favorites collection: a folder is favorited in place (its
    position in the tree never changes) and collected here so all favorites —
    however deeply nested — are reachable from one spot.
    """
    found: list = []

    def walk(groups):
        for group in groups:
            if group.favorite:
                found.append(group)
            walk(child_groups(group))

    walk(tree)
    return found


def folder_names_by_row(
    tree: list, folder_meta: dict[str, dict] | None = None, custom_collections=()
) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    folder_meta = folder_meta or {}

    def credit(group, name: str):
        for row in rows_under(group):
            names.setdefault(row["prompt_id"], []).append(name)

    def walk(groups):
        for group in groups:
            name = folder_meta.get(group.key, {}).get("custom_name")
            if not name and isinstance(group, (SettingsGroup, SourceImageGroup)):
                name = group.label
            if name:
                credit(group, name)
            walk(child_groups(group))

    walk(tree)
    for folder in custom_collections:
        credit(folder, folder.label)
    return names


def recent_generations(rows: list[dict], *, bumped=None) -> list[dict]:
    """Every row with a result, newest first — the whole of the Latest collection's list.

    Made here or found on disk alike. Made here is a Generate tab or a gallery
    re-roll -- or, with no run under it at all, a single cycle cut out of a
    video for the Genau lane (``source`` ``"stroke_trim"``): a cut is something
    the app just made for you, it lands in the settings folder of the video it
    came from rather than anywhere you would think to go looking, and left off
    here there is nowhere at all that says it happened. Found on disk is a file
    ComfyUI wrote that no instance of this app queued (``source``
    ``"imported"``): it arrives at the launch that finds it, and that is when it
    is looked for on Latest. An experiment has a collection of its own and is left
    out. As in the tree, only rows that produced an output file appear — the
    collection is a gallery of results, so a failed or in-flight run with nothing to
    show doesn't surface.

    An image being enhanced, or lately enhanced, sits where the *enhancement*
    falls in that order rather than where its own generation does
    (:func:`~origenerator.gallery.enhance.enhancement_recency`). An enhancement
    has no tile of its own here — it is a version of an image, not an item beside
    one — so if it did not move the image, the work would be listed nowhere and
    the image being worked on could sit a thousand tiles down, unfindable. What
    an image is having done to it is the newest thing about it.

    Nothing is capped here: the collection keeps going as far back as the user has ever
    generated, and the pane draws a page of tiles at a time as it's scrolled into
    (:meth:`~origenerator.gui.gallery_pane.GalleryPane.follow_the_scroll`).
    """
    listed = [
        row for row in rows
        if source_of(row) != GenerationSource.EXPERIMENT and in_sight(row)
        and produced_output(row)
    ]
    if bumped is None:
        bumped = enhancement_recency(rows)
    return sorted(listed, reverse=True, key=lambda row: row_recency(row, bumped))


def row_recency(row: dict, bumped: dict[str, tuple[datetime, int]]) -> tuple[datetime, int]:
    """Where ``row`` falls in the library's order: when it landed, then the id
    it was asked under — each its own or its newest enhancement's, whichever is later.

    ``bumped`` is :func:`~origenerator.gallery.enhance.enhancement_recency` over
    the same rows. An image being enhanced is being worked on now, so it counts
    as the newest thing in the library rather than as whenever it was generated
    — which is what puts it at the head of the Latest collection and what marks the
    folder it sits in as lately worked in.
    """
    enhanced_at, enhanced_by = bumped.get(row.get("prompt_id"), (BEFORE_EVERY_RECORD, 0))
    return (max(_joined_the_library_at(row), enhanced_at),
            max(row.get("id") or 0, enhanced_by))


def _joined_the_library_at(row: dict) -> datetime:
    found_on_disk = source_of(row) == GenerationSource.IMPORTED
    return moment_of(row.get("created_at") if found_on_disk else row.get("completed_at"))


# How many folders the tree of contents marks as lately worked in. A sitting
# reaches a handful of folders; marks past that stop picking anything out, and
# every folder marked is no folder marked.
RECENTLY_WORKED_COUNT = 20


def recently_worked_folders(
    trees: dict[str, list], rows: list[dict], limit: int = RECENTLY_WORKED_COUNT,
    *, bumped=None,
) -> set[tuple[str, str]]:
    """The ``(shape, folder key)`` pairs of the folders worked in most recently.

    A folder no longer moves when a generation lands in it — it is placed by the
    row that made it, so the tree of contents keeps the order the settings were
    tried in (:func:`build_gallery_tree`). That order says nothing about where
    the work has lately been, which is the other thing the tree is read for, so
    the freshest folders are marked where they stand instead of floating up.

    Only the folders the generations themselves sit in are ranked — the ones
    with nothing nested under them. A folder of folders is fresh whenever
    anything anywhere under it is, which is nearly always, so a mark on one
    would say nothing about it.

    A folder's recency is the newest row in it, by :func:`row_recency`. Shape by
    shape, because both shapes draw the same folder key over rows of their own
    shape: portrait work must not light the landscape copy of a folder nothing
    portrait-shaped ever touched.
    """
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


def favorite_generations(rows: list[dict]) -> list[dict]:
    """Every favorited image or video that produced an output, newest first — the
    individual favorites the Favorites collection gathers alongside favorited folders.

    Any produced row the user favorited qualifies, imported files included (unlike
    the Latest collection, which is app-made results only). ``rows`` arrive newest-first
    (the caller lists them by descending id), so the result is too.
    """
    return [row for row in rows if row.get("starred") and produced_output(row)]


def enhanced_generations(rows: list[dict]) -> list[dict]:
    return [row for row in placeable_rows(rows) if produced_output(row) and is_enhanced_row(row)]


def unreviewed_experiments(rows: list[dict]) -> list[dict]:
    """The finished experiments awaiting the user's verdict, newest first — the
    Experiments collection's review queue. Only completed results qualify: a failed
    experiment has nothing to judge, and an in-flight one shows as a live tile."""
    return [
        row for row in rows
        if row.get("source") == GenerationSource.EXPERIMENT
        and row.get("experiment_verdict") is None
        and produced_output(row)
    ]


@dataclass(frozen=True)
class _Tier:
    """What every folder level under one workflow is built against.

    The media type and the workflow name are the two halves of every key below;
    ``folder_meta`` is the names and stars the folders carry; ``image_index``
    resolves a start frame to the image it is. All four used to travel as four
    parameters through five builders that each handed them on untouched, and
    every builder's `children_for` lambda had to list them again.
    """

    media_type: str
    workflow_name: str
    folder_meta: dict
    image_index: dict
    name_of: Callable[[str], str]


def _build_settings_groups(tier: _Tier, rows: list[dict]) -> list[SettingsGroup]:
    """The settings-group leaves under one model, LoRA, or source-image folder.

    Rows collapse by folder signature (all non-instance params, plus an i2v's
    start-frame configuration). A leaf is *named* by its key (see
    :func:`~origenerator.gallery.keys.folder_id`): the prompt it ran is a
    paragraph, and a folder name is a line.
    """
    grouped = _group_by_creation(
        rows, lambda r: folder_signature(tier.workflow_name, r.get("params_json"),
                                         tier.image_index,
                                         workflow_version=r.get("workflow_version"))
    )
    groups = []
    for sig, sig_rows in grouped:
        key = settings_key(tier.media_type, tier.workflow_name, sig)
        label, favorite = _overlay(folder_id(key), key, tier.folder_meta)
        groups.append(SettingsGroup(
            key, label, sig_rows, favorite,
        ))
    return groups


def _grouped_folders(tier: _Tier, rows, *, signature, key_for, label_for, children_for, cls):
    """Build one folder level: order rows by ``signature``, then key + label +
    overlay each folder and recurse for its children.

    The model, LoRA, and source-image levels are the same folder-building contract
    over different projections of the settings key, so all three go through here —
    differing only in the callables.
    """
    groups = []
    for sig, sub_rows in _group_by_creation(rows, signature):
        key = key_for(sig)
        params = parse_params(sub_rows[0].get("params_json"))
        label, favorite = _overlay(label_for(params), key, tier.folder_meta)
        groups.append(cls(key, label, children_for(sub_rows), favorite))
    return groups


def _build_model_groups(tier: _Tier, rows: list[dict]) -> list[ModelGroup]:
    """The model folders under one workflow, each holding its LoRA folders."""
    return _grouped_folders(
        tier, rows, cls=ModelGroup,
        signature=lambda r: model_signature(tier.workflow_name, r.get("params_json")),
        key_for=lambda sig: model_key(tier.media_type, tier.workflow_name, sig),
        label_for=lambda params: model_label(tier.workflow_name, params),
        children_for=lambda sub: _build_lora_groups(tier, sub),
    )


def _build_lora_groups(tier: _Tier, rows: list[dict]) -> list[LoraGroup]:
    """The LoRA folders under one model, each holding its leaves.

    A workflow with no LoRA keys collapses to a single ``(no LoRA)`` folder — every
    row shares one empty LoRA signature — so a model folder nests the same way
    whether or not the pipeline uses a LoRA."""
    return _grouped_folders(
        tier, rows, cls=LoraGroup,
        signature=lambda r: _lora_place(tier.workflow_name, r.get("params_json")),
        key_for=lambda sig: lora_key(tier.media_type, tier.workflow_name, sig),
        label_for=lambda params: lora_label(tier.workflow_name, params),
        children_for=lambda sub: _build_leaves(tier, sub),
    )


def _build_leaves(tier: _Tier, rows: list[dict]) -> list:
    """A model or LoRA folder's leaves: source-image folders when the folder holds
    videos an image conditions (each holding its settings leaves), else settings
    leaves directly.

    The split is by *media type*, not just the workflow: a source image is what a
    video animates, so only a video folder grows the level. An image-conditioned
    workflow can still output a still — an imported PNG under a video prefix —
    which lands in that workflow's image folder and animates nothing, so it is
    grouped like any other image.
    """
    if _grows_source_images(tier.media_type, tier.workflow_name):
        return _build_source_image_groups(tier, rows)
    return _build_settings_groups(tier, rows)


def _build_source_image_groups(tier: _Tier, rows: list[dict]) -> list[SourceImageGroup]:
    """The source-image folders under one model/LoRA folder: videos split by the
    image they animate, each holding its settings leaves."""
    return _grouped_folders(
        tier, rows, cls=SourceImageGroup,
        signature=lambda r: _source_image_place(tier.workflow_name, r.get("params_json"),
                                                tier.image_index),
        key_for=lambda sig: source_image_key(tier.media_type, tier.workflow_name, sig),
        label_for=lambda params: _source_image_label(params, tier.image_index, tier.name_of),
        children_for=lambda sub: _build_settings_groups(tier, sub),
    )


def placeable_rows(rows: list[dict]) -> list[dict]:
    """The rows a tree has somewhere to put — what :func:`build_gallery_tree`
    nests.

    A row is included once it has something to place: it either
    :func:`produced_output` (a finished result) or :func:`is_in_progress` (a
    running/pending generation whose folder must appear at once, its live tile
    standing in until its output lands). A terminal file-less row — a failed
    generation, or a rejected experiment whose files went to the trash — is
    dropped.

    A running standalone enhance is machinery, not a generation: its result folds
    into the image it upgrades, so its transient row must not grow an "Image
    Enhance" folder while it cooks (its progress shows on the tile of the image
    it is upgrading, under that tile's "Enhancing…" scrim — the Latest collection
    gives it no tile of its own either). A completed one still in the DB — its
    source image deleted before it could fold — stays visible, so it can be found
    and deleted rather than haunting the disk invisibly. A re-derived base render
    is a repair of an existing image, not an image of its own: it folds into its
    target and vanishes, so it never earns a tile — least of all a duplicate one
    beside what it repairs.
    """
    return [row for row in rows_with_a_folder(rows) if in_sight(row)]


def rows_with_a_folder(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if (produced_output(row) or is_in_progress(row))
        and not (row.get("workflow_name") == ENHANCE_WORKFLOW and is_in_progress(row))
        and row.get("source") != GenerationSource.BASE_RENDER
    ]


def start_frame_index(rows: list[dict]) -> dict:
    """The start-frame configurations ``rows`` offer, for keying and naming the
    source-image and settings folders under an image-conditioned workflow.

    Only finished images have a file to condition an i2v's frame on, so it is
    built from those alone.

    Hand this to :func:`build_gallery_tree` wherever the tree is built from a
    *slice* of the library — one shape's rows, say. The key of a video's folder
    names the image it animates, and that image can perfectly well be on the
    other shape of the split (a portrait frame with the size unlocked to a
    landscape video, or a run placed by the size it asked for while its frame is
    measured). An index built from the slice alone misses it, and keys the folder
    to something nothing else in the app computes. The folder is still drawn — it
    is simply unreachable: every reveal, star and custom name resolves a folder
    through :func:`settings_folder_key` over the whole library, so a click on the
    queue row for a job in it finds no row and does nothing at all.
    """
    return build_image_config_index(
        [row for row in rows_with_a_folder(rows)
         if media_type_of_row(row) == MediaType.IMAGE and produced_output(row)]
    )


def build_gallery_tree(
    rows: list[dict], folder_meta: dict[str, dict] | None = None,
    *, image_index: dict | None = None,
    name_of: Callable[[str], str] | None = None,
) -> list[MediaGroup]:
    """Nest rows into Images and Videos, then workflow -> model -> LoRA ->
    [source image] -> settings folders.

    ``image_index`` is the start-frame index the source-image folders are keyed
    by, for a caller who narrowed ``rows`` — see :func:`start_frame_index`, which
    is what it must be built with. Left out, it is read from ``rows``, which is
    the right answer only where ``rows`` is the whole library.

    Every model folder holds a LoRA level; a workflow with no LoRA keys collapses
    it to a single "(no LoRA)" folder. The source-image level appears only under
    a video workflow folder (a still an image-conditioned workflow output is
    grouped like any other image). Which rows are nested at all is
    :func:`placeable_rows`. Images lead Videos; every other folder is placed by
    the oldest of its rows, newest-made first (the caller orders rows
    newest-first); neither a new generation in a folder nor a star moves it —
    favorites are gathered by :func:`favorite_folders` instead. ``folder_meta``
    (keyed by each folder's stable ``key``) overrides the default label and
    supplies the star state.

    A background experiment is nested like anything else, from the moment it
    starts running: it is a generation, so it gets the folder its settings put it
    in, and the Experiments collection is a review queue over those rows rather than a
    holding pen outside the tree.
    """
    folder_meta = folder_meta or {}
    if image_index is None:
        image_index = start_frame_index(rows)
    rows = placeable_rows(rows)
    by_kind = dict(_group_by_creation(rows, media_type_of_row))
    return [_media_folder(media_type, by_kind[media_type], folder_meta, image_index,
                          name_of or _unnamed)
            for media_type in MediaType if media_type in by_kind]


def _media_folder(media_type, rows, folder_meta, image_index, name_of) -> MediaGroup:
    label, favorite = _overlay(MEDIA_LABELS[media_type], media_type, folder_meta)
    workflows = []
    for wf_name, wf_rows in _group_by_creation(
        rows, lambda r: r.get("workflow_name") or "unknown"
    ):
        wf_key = f"{media_type}/{wf_name}"
        wf_label, wf_favorite = _overlay(workflow_label(wf_name), wf_key, folder_meta)
        tier = _Tier(media_type, wf_name, folder_meta, image_index, name_of)
        workflows.append(WorkflowGroup(
            wf_key, wf_name, wf_label,
            _build_model_groups(tier, wf_rows),
            wf_favorite,
        ))
    return MediaGroup(str(media_type), label, workflows, favorite)


def _unnamed(_prompt_id: str) -> str:
    return ""


# The row over Images and Videos, standing for the library entire: a folder
# wrapped *around* what build_gallery_tree returns, for somewhere to stand that
# means everything.
ALL_KEY = "__all__"
ALL_LABEL = "All"


def all_group(tree_model, folder_meta: dict[str, dict] | None = None) -> AllGroup:
    """Images and Videos gathered under one folder, named and favorited like any other."""
    label, favorite = _overlay(ALL_LABEL, ALL_KEY, folder_meta or {})
    return AllGroup(ALL_KEY, label, list(tree_model), favorite)
