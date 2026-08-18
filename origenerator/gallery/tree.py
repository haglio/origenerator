"""Nest a flat list of generations into the gallery's folder tree.

The gallery view organizes generations as nested folders:
media type (Images/Videos) -> workflow -> model -> LoRA -> [source image] ->
settings group (rows sharing every setting except per-instance ones: the seed,
and — for an image-to-video workflow — the specific start-frame *file*. A re-roll
regenerates that frame, so the raw filename is per-instance; but the
*configuration* that produced the frame is not, so it is folded back into the
settings key. Two i2v videos built from re-rolls of one image stay together,
while two built from differently configured images split apart. The enhance
tail's params are excluded too, so an enhanced render and its unenhanced twin
land in one folder — enhancement is a finish on an image, not another image).

Each level below the workflow is a *projection* of that settings key onto one
facet, splitting a folder into sub-folders that differ in that facet alone: model
(always), LoRA (always — collapsed to a single "(no LoRA)" folder when the
workflow declares no LoRA keys, so every branch nests the same depth), and — in
the Videos tree only — the source image a video animates, i.e. which picture its
start frame is (:func:`_input_image_config`). The source-image level is a
property of *videos*, so it grows only under Videos; a still an image-conditioned
workflow happened to output (an imported PNG under a video prefix) lands under
Images and is grouped like any other image. The settings group is the full key,
so it nests beneath every projection. This module owns the grouping logic with no
Qt dependency so it can be unit-tested directly.
"""

import json

from origenerator.gallery.enhance import BASE_RENDER_SOURCE, ENHANCE_WORKFLOW
from origenerator.gallery.groups import (
    AllGroup,
    LoraGroup,
    MediaGroup,
    ModelGroup,
    SettingsGroup,
    SourceImageGroup,
    WorkflowGroup,
    child_groups,
)
from origenerator.gallery.keys import (
    folder_id,
    lora_key,
    model_key,
    settings_key,
    source_image_key,
)
from origenerator.gallery.labels import (
    _distinguishing_keys,
    _source_image_label,
    lora_label,
    model_label,
    settings_label,
    workflow_label,
)
from origenerator.gallery.output import is_in_progress, media_type_of_row, produced_output
from origenerator.gallery.signatures import (
    _grouping_version,
    _input_image_config,
    is_image_conditioned,
    canonical_settings,
    enhance_settings,
    lora_signature,
    model_signature,
    parse_params,
    settings_only,
    settings_signature,
)
from origenerator.gallery.source_image import build_image_config_index

MEDIA_LABELS = {"image": "Images", "video": "Videos"}


def _group_ordered(rows, key):
    """Group rows by ``key(row)``, preserving first-appearance order of keys."""
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return list(grouped.items())


def settings_folder_key(row: dict, image_index: dict | None = None) -> str:
    """The key of the settings-folder leaf a row belongs to in the gallery tree.

    Mirrors how :func:`build_gallery_tree` keys that leaf — media type, workflow
    name, settings signature — so an in-flight row (which has no output yet and so
    never appears in the tree itself) can still be matched to the folder it joins.
    ``image_index`` must be the same one the tree was built with (see
    :func:`build_image_config_index`) so an image-conditioned row keys to the same
    leaf its start frame's configuration places it in.
    """
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    return settings_key(
        media_type, workflow_name,
        settings_signature(workflow_name, row.get("params_json"), image_index,
                           workflow_version=row.get("workflow_version")),
    )


def folder_key_at_level(row: dict, level: str, image_index: dict | None = None) -> str:
    """The key of the ``level``-tier folder ``row`` belongs to, recomputed from the
    row under the *current* key formulas.

    A bookmark stores its tier and a representative member row; recomputing here
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
        return lora_key(media_type, workflow_name, lora_signature(workflow_name, params_json))
    if level == "source_image":
        # The tier exists only in the Videos tree, so it always asks which picture.
        config = _input_image_config(
            parse_params(params_json).get("input_image"), image_index, identify=True,
        )
        return source_image_key(media_type, workflow_name, config)
    if level == "settings":
        return settings_folder_key(row, image_index)
    raise ValueError(f"unknown folder level: {level!r}")


def legacy_settings_folder_key(row: dict) -> str:
    """The settings-folder key ``row`` had under the pre-normalization formula:
    ``settings_only`` hashed with sort_keys, before :func:`canonical_settings`.

    One historical key formula shift that orphaned bookmarks made before it. The
    reconcile recomputes this to re-point such a stale star or name onto the row's
    current settings folder."""
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(settings_only(parse_params(row.get("params_json"))), sort_keys=True)
    return settings_key(media_type, workflow_name, signature)


def _preenhance_settings(workflow_name: str, params: dict) -> dict:
    """A row's settings the way every formula predating the enhancement split
    computed them: the recipe with the enhance tail's params still folded in.

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


def legacy_preenhance_settings_folder_keys(members, image_index: dict | None = None) -> set[str]:
    """The settings-folder keys a folder's ``members`` were split across before
    the enhancement layer left the signature: today's key with the enhance tail's
    params folded back in.

    The fourth historical formula shift, and the only one that *merged* folders —
    an enhanced render and its unenhanced twin used to be two. So this takes the
    whole member list and returns a key per distinct enhance setting found among
    them, rather than one key from a single member: a star sitting on either old
    folder must find its way to the merged one. The reconcile recomputes these to
    re-point a star or name made under that formula — one made since the last
    reconcile, so its stored identity was never backfilled."""
    keys = set()
    for row in members:
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
    """Apply a folder's saved custom name and star, returning (label, starred)."""
    meta = folder_meta.get(key, {})
    return (meta.get("custom_name") or label, bool(meta.get("starred")))


def starred_folders(tree: list[MediaGroup]) -> list:
    """Every starred folder in ``tree``, at any depth, in top-down tree order.

    Powers the gallery's Starred shelf: a folder is bookmarked in place (its
    position in the tree never changes) and collected here so all bookmarks —
    however deeply nested — are reachable from one spot.
    """
    found: list = []

    def walk(groups):
        for group in groups:
            if group.starred:
                found.append(group)
            walk(child_groups(group))

    walk(tree)
    return found


def recent_generations(
    rows: list[dict], media_types: set[str] | None = None
) -> list[dict]:
    """Every generated row, newest first — the whole of the Recents shelf's list.

    "Generated" means this app produced the row, from a Generate tab or a gallery
    re-roll; an imported file discovered on disk (``source`` ``"imported"``) is not
    a recent *generation* and is left out. As in the tree, only rows that produced
    an output file appear — the shelf is a gallery of results, so a failed or
    in-flight run with nothing to show doesn't surface. ``rows`` arrive newest-first
    (the caller lists them by descending id), so the result is too.

    Nothing is capped here: the shelf keeps going as far back as the user has ever
    generated, and the pane draws a page of tiles at a time as it's scrolled into
    (:meth:`~origenerator.gui.browser_pane.BrowserPane.grow_recents`).

    ``media_types`` is the shelf's image/video filter (its checkboxes): a set of
    the ``media_type_of_row`` values to keep. ``None`` (the default) keeps every
    type; an empty set keeps none.
    """
    return [
        row for row in rows
        if (row.get("source") or "generated") == "generated" and produced_output(row)
        and (media_types is None or media_type_of_row(row) in media_types)
    ]


def starred_generations(rows: list[dict]) -> list[dict]:
    """Every starred image or video that produced an output, newest first — the
    individual bookmarks the Starred shelf collects alongside starred folders.

    Any produced row the user starred qualifies, imported files included (unlike
    the Recents shelf, which is app-made results only). ``rows`` arrive newest-first
    (the caller lists them by descending id), so the result is too.
    """
    return [row for row in rows if row.get("starred") and produced_output(row)]


def requested_generations(records: list[dict], rows: list[dict]) -> list[dict]:
    """Each spoken request paired with what it made, newest first — the Requests
    shelf's list.

    ``records`` are the rows :meth:`Database.list_requests` returns; each gains
    a ``"row"`` (the generation the request queued) and a ``"source_row"`` (the
    item it was made about, or ``None`` when that has since gone). An in-flight
    generation is kept, unlike the other shelves' listings — a request you have
    just spoken should appear at once, and the whole of what this shelf shows
    about it (what was heard, what changed in the prompt) is readable before
    there is a picture to look at.

    A record whose generation is gone is skipped rather than dropped from the
    table: a delete here is undoable, so the request has to be waiting if the
    item comes back.
    """
    by_id = {row["prompt_id"]: row for row in rows}
    listed = []
    for record in records:
        row = by_id.get(record["prompt_id"])
        if row is not None:
            listed.append({**record, "row": row,
                           "source_row": by_id.get(record["source_prompt_id"])})
    return listed


def unreviewed_experiments(rows: list[dict]) -> list[dict]:
    """The finished experiments awaiting the user's verdict, newest first — the
    Experiments shelf's review queue. Only completed results qualify: a failed
    experiment has nothing to judge, and an in-flight one shows as a live card."""
    return [
        row for row in rows
        if row.get("source") == "experiment"
        and row.get("experiment_verdict") is None
        and produced_output(row)
    ]


def _build_settings_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list[SettingsGroup]:
    """The settings-group leaves under one model, LoRA, or source-image folder.

    Rows collapse by settings signature (all non-instance params, plus an i2v's
    start-frame configuration). A leaf is *named* by its key (see
    :func:`~origenerator.gallery.keys.folder_id`) — the prompt it ran is a
    paragraph, and a folder name is a line — and what the prompt said rides its
    ``detail`` instead, for the tooltip. That detail is disambiguated only
    against its siblings under the same parent, so a value the folder above
    already pins (the model, the LoRA, and for an i2v the source image) is
    constant here and never re-appears in it.
    """
    grouped = _group_ordered(
        rows, lambda r: settings_signature(wf_name, r.get("params_json"), image_index,
                                           workflow_version=r.get("workflow_version"))
    )
    settings_dicts = [
        canonical_settings(wf_name, parse_params(sig_rows[0].get("params_json")))
        for _sig, sig_rows in grouped
    ]
    distinguishing = _distinguishing_keys(settings_dicts)
    groups = []
    for i, (sig, sig_rows) in enumerate(grouped):
        key = settings_key(media_type, wf_name, sig)
        label, starred = _overlay(folder_id(key), key, folder_meta)
        groups.append(SettingsGroup(
            key, label, sig_rows, starred,
            settings_label(settings_dicts[i], distinguishing),
        ))
    return groups


def _grouped_folders(rows, folder_meta, *, signature, key_for, label_for, children_for, cls):
    """Build one folder level: order rows by ``signature``, then key + label +
    overlay each folder and recurse for its children.

    The model, LoRA, and source-image levels are the same folder-building contract
    over different projections of the settings key, so all three go through here —
    differing only in the callables.
    """
    groups = []
    for sig, sub_rows in _group_ordered(rows, signature):
        key = key_for(sig)
        params = parse_params(sub_rows[0].get("params_json"))
        label, starred = _overlay(label_for(params), key, folder_meta)
        groups.append(cls(key, label, children_for(sub_rows), starred))
    return groups


def _build_model_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list[ModelGroup]:
    """The model folders under one workflow, each holding its LoRA folders."""
    return _grouped_folders(
        rows, folder_meta, cls=ModelGroup,
        signature=lambda r: model_signature(wf_name, r.get("params_json")),
        key_for=lambda sig: model_key(media_type, wf_name, sig),
        label_for=lambda params: model_label(wf_name, params),
        children_for=lambda sub: _build_lora_groups(media_type, wf_name, sub, folder_meta, image_index),
    )


def _build_lora_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list[LoraGroup]:
    """The LoRA folders under one model, each holding its leaves.

    A workflow with no LoRA keys collapses to a single ``(no LoRA)`` folder — every
    row shares one empty LoRA signature — so a model folder nests the same way
    whether or not the pipeline uses a LoRA."""
    return _grouped_folders(
        rows, folder_meta, cls=LoraGroup,
        signature=lambda r: lora_signature(wf_name, r.get("params_json")),
        key_for=lambda sig: lora_key(media_type, wf_name, sig),
        label_for=lambda params: lora_label(wf_name, params),
        children_for=lambda sub: _build_leaves(media_type, wf_name, sub, folder_meta, image_index),
    )


def _build_leaves(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list:
    """A model or LoRA folder's leaves: source-image folders when the folder holds
    videos an image conditions (each holding its settings leaves), else settings
    leaves directly.

    The split is by *media type*, not just the workflow: a source image is what a
    video animates, so only the Videos tree grows the level. An image-conditioned
    workflow can still output a still — an imported PNG under a video prefix — which
    lands under Images and animates nothing, so it is grouped like any other image.
    """
    if media_type == "video" and is_image_conditioned(wf_name):
        return _build_source_image_groups(media_type, wf_name, rows, folder_meta, image_index)
    return _build_settings_groups(media_type, wf_name, rows, folder_meta, image_index)


def _build_source_image_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list[SourceImageGroup]:
    """The source-image folders under one model/LoRA folder: videos split by the
    picture they animate, each holding its settings leaves.

    Keyed by which picture that is (:func:`_input_image_config`), the same
    projection of the settings signature that the model and LoRA levels use for
    theirs — so every settings folder in here explores one frame, and opening any
    of them shows videos of that one image."""
    return _grouped_folders(
        rows, folder_meta, cls=SourceImageGroup,
        signature=lambda r: _input_image_config(
            parse_params(r.get("params_json")).get("input_image"), image_index,
            identify=True,
        ),
        key_for=lambda sig: source_image_key(media_type, wf_name, sig),
        label_for=lambda params: _source_image_label(params, image_index),
        children_for=lambda sub: _build_settings_groups(media_type, wf_name, sub, folder_meta, image_index),
    )


def build_gallery_tree(
    rows: list[dict], folder_meta: dict[str, dict] | None = None
) -> list[MediaGroup]:
    """Nest rows into media -> workflow -> model -> LoRA -> [source image] ->
    settings folders.

    Every model folder holds a LoRA level; a workflow with no LoRA keys collapses
    it to a single "(no LoRA)" folder. The source-image level appears only in the
    Videos tree (a still an image-conditioned workflow output is grouped like any
    other image). A row is included once it has something to place: it either
    :func:`produced_output` (a finished result) or :func:`is_in_progress` (a
    running/pending generation whose folder must appear at once, its live tile
    standing in until its output lands). A terminal file-less row — a failed
    generation, or a rejected experiment whose files went to the trash — is
    dropped. Folders appear in the order their first member appears in ``rows``
    (the caller orders rows newest-first); a star never moves a folder —
    bookmarks are gathered by :func:`starred_folders` instead. ``folder_meta``
    (keyed by each folder's stable ``key``) overrides the default label and
    supplies the star state.

    A background experiment is nested like anything else, from the moment it
    starts running: it is a generation, so it gets the folder its settings put it
    in, and the Experiments shelf is a review queue over those rows rather than a
    holding pen outside the tree.
    """
    folder_meta = folder_meta or {}
    # A running standalone enhance is machinery, not a generation: its result
    # folds into the image it upgrades, so its transient row must not grow an
    # "Image Enhance" folder while it cooks (its progress shows as an in-flight
    # card on Recents). A completed one still in the DB — its source image
    # deleted before it could fold — stays visible, so it can be found and
    # deleted rather than haunting the disk invisibly.
    rows = [
        row for row in rows
        if (produced_output(row) or is_in_progress(row))
        and not (row.get("workflow_name") == ENHANCE_WORKFLOW and is_in_progress(row))
        # A re-derived base render is a repair of an existing image, not an
        # image of its own: it folds into its target and vanishes, so it never
        # earns a tile — least of all a duplicate one beside what it repairs.
        and row.get("source") != BASE_RENDER_SOURCE
    ]
    # Only finished images have a file to condition an i2v's frame on, so the
    # index that keys image-conditioned folders is built from those alone.
    image_index = build_image_config_index(
        [row for row in rows
         if media_type_of_row(row) == "image" and produced_output(row)]
    )
    tree = []
    for media_type, media_rows in _group_ordered(rows, media_type_of_row):
        workflow_groups = []
        for wf_name, wf_rows in _group_ordered(
            media_rows, lambda r: r.get("workflow_name") or "unknown"
        ):
            wf_key = f"{media_type}/{wf_name}"
            wf_label, wf_starred = _overlay(workflow_label(wf_name), wf_key, folder_meta)
            workflow_groups.append(WorkflowGroup(
                wf_key, wf_name, wf_label,
                _build_model_groups(media_type, wf_name, wf_rows, folder_meta, image_index),
                wf_starred,
            ))

        media_label, media_starred = _overlay(
            MEDIA_LABELS.get(media_type, media_type.title()), media_type, folder_meta
        )
        tree.append(MediaGroup(
            media_type, media_type, media_label,
            workflow_groups, media_starred,
        ))
    return tree


# The row above Images and Videos, standing for the library entire. Not part of
# the grouping — build_gallery_tree still returns the media roots, and everything
# reading that (starred folders, custom folders, the browser's tiles) is unchanged
# — this is a folder wrapped *around* the result, for somewhere to stand that
# means everything.
ALL_KEY = "__all__"
ALL_LABEL = "All"


def all_group(tree_model, folder_meta: dict[str, dict] | None = None) -> AllGroup:
    """The media roots gathered under one folder, renamable like any other."""
    label, starred = _overlay(ALL_LABEL, ALL_KEY, folder_meta or {})
    return AllGroup(ALL_KEY, label, list(tree_model), starred)
