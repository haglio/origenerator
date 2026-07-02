"""Pure gallery model: classify and group generations into a folder tree.

The gallery view organizes generations as nested folders:
media type (Images/Videos) -> workflow -> model -> LoRA -> [source image] ->
settings group (rows sharing every setting except per-instance ones: the seed,
and — for an image-to-video workflow — the specific start-frame *file*. A re-roll
regenerates that frame, so the raw filename is per-instance; but the
*configuration* that produced the frame is not, so it is folded back into the
settings key. Two i2v videos built from re-rolls of one image stay together,
while two built from differently configured images split apart).

Each level below the workflow is a *projection* of that settings key onto one
facet, splitting a folder into sub-folders that differ in that facet alone: model
(always), LoRA (always — collapsed to a single "(no LoRA)" folder when the
workflow declares no LoRA keys, so every branch nests the same depth), and — in
the Videos tree only — the source image a video animates, i.e. the configuration
of its start frame (:func:`_input_image_config`). The source-image level is a
property of *videos*, so it grows only under Videos; a still an image-conditioned
workflow happened to output (an imported PNG under a video prefix) lands under
Images and is grouped like any other image. The settings group is the full key,
so it nests beneath every projection. This module owns the grouping logic with no
Qt dependency so it can be unit-tested directly.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from origenerator.media import media_type_from_filename, sibling_of_type
from origenerator.gallery.signatures import (
    _basename,
    _frame_name,
    _input_image_config,
    _is_image_conditioned,
    _registered,
    _unannotated,
    canonical_settings,
    lora_signature,
    model_signature,
    parse_params,
    settings_only,
    settings_signature,
    workflow_lora_keys,
    workflow_model_keys,
    workflow_output_type,
)
from origenerator.gallery.groups import (
    LoraGroup,
    MediaGroup,
    ModelGroup,
    SettingsGroup,
    SourceImageGroup,
    WorkflowGroup,
    child_groups,
    folder_level,
    group_level,
    rows_under,
)

MEDIA_LABELS = {"image": "Images", "video": "Videos"}

# File extensions stripped from a model filename to make a tidy folder label.
MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft")


def row_output_files(row: dict) -> list[dict]:
    """Parse a row's ``output_files`` JSON into a list, tolerating bad data."""
    raw = row.get("output_files")
    if not raw:
        return []
    try:
        files = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return files if isinstance(files, list) else []


def produced_output(row: dict) -> bool:
    """True when a row recorded at least one output file.

    The gallery is a gallery of results: a generation that failed (or hasn't
    finished) wrote no file, so it has nothing to show and is left out of the
    tree entirely rather than surfacing as an empty, file-less entry.
    """
    return bool(row_output_files(row))


def media_type_of_row(row: dict) -> str:
    """Classify a row as ``"image"`` or ``"video"``.

    The actual output file is authoritative — a still saved under a video
    workflow's prefix is an image and must not surface in the Videos folder.
    Rows with no file yet (pending) fall back to the workflow's declared type,
    then to ``"image"``.
    """
    for f in row_output_files(row):
        inferred = media_type_from_filename(f.get("filename", ""))
        if inferred:
            return inferred
    return workflow_output_type(row.get("workflow_name")) or "image"


def resolve_preview(row: dict, output_dir: Path) -> tuple[Path, str] | None:
    """Locate the file to preview for ``row`` and how to render it.

    Prefers the full-resolution output under ``output_dir`` (so videos play and
    images show at full quality), classifying it by extension. Falls back to the
    stored thumbnail — always a still image — when the output is missing. Returns
    ``None`` when nothing displayable can be found.
    """
    for f in row_output_files(row):
        filename = f.get("filename")
        if not filename:
            continue
        full = output_dir / f.get("subfolder", "") / filename
        rendered_as = media_type_from_filename(filename)
        if rendered_as is not None and full.exists():
            return full, rendered_as
        break

    thumb = row.get("thumbnail_path")
    if thumb and Path(thumb).exists():
        return Path(thumb), "image"

    return None


def output_disk_files(row: dict, output_dir: Path) -> list[Path]:
    """Every on-disk output file a row owns, for deletion.

    The referenced output file plus any same-stem sidecar of the other media
    type — a video's VHS_VideoCombine metadata PNG, say. Removing the sidecar
    too is what stops a later import from resurrecting the orphan as its own
    entry. Files already absent are skipped.
    """
    paths: list[Path] = []
    for f in row_output_files(row):
        filename = f.get("filename")
        if not filename:
            continue
        full = output_dir / f.get("subfolder", "") / filename
        if not full.exists():
            continue
        paths.append(full)
        other = "video" if media_type_from_filename(filename) == "image" else "image"
        sidecar = sibling_of_type(full, other)
        if sidecar is not None:
            paths.append(sidecar)
    return paths


def source_image_id_for(input_image: str | None, image_rows: list[dict]) -> str | None:
    """The prompt_id of the image generation an ``input_image`` value names.

    Image-to-video rows reference their start frame by filename; match it to an
    image generation by basename (through any ``[output]`` annotation). ``None``
    when the value is empty or none of ``image_rows`` produced a file with that
    name. Takes the bare value so the Generate tab — which has the field, not a
    stored row — can resolve it the same way :func:`find_source_image_id` does.
    """
    if not input_image:
        return None
    target = _frame_name(input_image)
    for image in image_rows:
        for f in row_output_files(image):
            if _frame_name(f.get("filename")) == target:
                return image["prompt_id"]
    return None


def find_source_image_id(row: dict, image_rows: list[dict]) -> str | None:
    """Return the prompt_id of the image used as this row's ``input_image``.

    Image-to-video rows reference their start frame by filename; match it to an
    image generation by basename. Returns ``None`` when the row has no input
    image or none of ``image_rows`` produced a file with that name.
    """
    return source_image_id_for(
        parse_params(row.get("params_json")).get("input_image"), image_rows
    )


@dataclass
class _ImageConfig:
    """How the gallery keys and names an image used as an i2v's start frame."""

    signature: str  # the image's settings signature — groups a video with re-rolls of its frame
    label: str      # the image's folder label — names the video's source-image folder


def build_image_config_index(image_rows: list[dict]) -> dict[str, _ImageConfig]:
    """Map each image's output filename to the configuration that produced it.

    Keyed by output basename (lowercased, matching how an ``input_image`` value
    resolves), so an i2v row can look up its start frame's settings signature and
    folder label in O(1). Built once per tree. Images that produced no file
    contribute nothing.
    """
    index: dict[str, _ImageConfig] = {}
    for image in image_rows:
        workflow_name = image.get("workflow_name")
        params = parse_params(image.get("params_json"))
        config = _ImageConfig(
            signature=settings_signature(workflow_name, image.get("params_json")),
            label=settings_label(canonical_settings(workflow_name, params)),
        )
        for f in row_output_files(image):
            name = _frame_name(f.get("filename"))
            if name:
                index.setdefault(name, config)
    return index


def videos_from_source_image(image_row: dict, video_rows: list[dict]) -> list[dict]:
    """The video rows that used this image as their input — the videos it was
    animated into. The inverse of :func:`find_source_image_id`, for showing an
    image the animations made from it."""
    image_id = image_row.get("prompt_id")
    if image_id is None:
        return []
    return [v for v in video_rows if find_source_image_id(v, [image_row]) == image_id]


def output_file_reference(files: list[dict]) -> str | None:
    """A ``LoadImage``-resolvable reference to a generation's first output file.

    A saved file lives in ComfyUI's output dir, so the reference carries its
    subfolder and an ``[output]`` tag (LoadImage validates by file existence via
    that annotation, not by input-folder membership). Feeds a re-rolled i2v its
    freshly generated start frame. ``None`` when no file has a name to reference.
    """
    for f in files:
        filename = f.get("filename")
        if not filename:
            continue
        subfolder = f.get("subfolder") or ""
        path = f"{subfolder}/{filename}" if subfolder else filename
        return f"{path} [{f.get('type') or 'output'}]"
    return None


def workflow_label(workflow_name: str | None) -> str:
    """Human-facing folder name for a workflow: its display name, else the key."""
    wf = _registered(workflow_name)
    return wf.display_name if wf else (workflow_name or "unknown")


def _model_name(value) -> str:
    """A model file's display form: final path segment, model extension stripped."""
    base = _basename(str(value))
    for ext in MODEL_EXTS:
        if base.lower().endswith(ext):
            return base[: -len(ext)]
    return base


def _joined_file_label(keys: tuple[str, ...], params: dict, fallback: str) -> str:
    """Join the cleaned filenames a row recorded for ``keys``, else ``fallback``.

    Shared by the model and LoRA folder labels: both name a folder after one or
    more model-file params, differing only in which keys and the empty fallback.
    """
    parts = [_model_name(params[key]) for key in keys if params.get(key)]
    return " / ".join(parts) or fallback


def model_label(workflow_name: str | None, params: dict) -> str:
    """Human-facing folder name for the model a row used.

    Joins each model param's cleaned filename. Falls back to ``"(unknown
    model)"`` when the workflow declares no model keys or the row recorded none
    of their values (e.g. an imported file whose graph didn't carry the model).
    """
    return _joined_file_label(workflow_model_keys(workflow_name), params, "(unknown model)")


def lora_label(workflow_name: str | None, params: dict) -> str:
    """Human-facing folder name for the LoRA(s) a row used.

    Joins each LoRA param's cleaned filename. Falls back to ``"(no LoRA)"`` when
    the row recorded none of their values (e.g. an older import that didn't carry
    the LoRA).
    """
    return _joined_file_label(workflow_lora_keys(workflow_name), params, "(no LoRA)")


def _prompt_headline(params: dict) -> str:
    """The positive prompt as a single trimmed line, or ``""`` if empty."""
    prompt = " ".join((params.get("positive_prompt") or "").split())
    return prompt[:60] + ("…" if len(prompt) > 60 else "")


def config_tab_title(workflow_name: str | None, params: dict) -> str:
    """A Generate tab's default name: the model (workflow) it runs, followed by
    the gallery folder (the prompt) its output would land in when there is one.

    Leads with the model so tabs stay grouped by pipeline; the prompt distinguishes
    same-model tabs. A blank config is named by its model alone.
    """
    headline = _prompt_headline(settings_only(params))
    model = workflow_label(workflow_name)
    return f"{model} › {headline}" if headline else model


def _short_value(value) -> str:
    text = str(value)
    return text[:24] + ("…" if len(text) > 24 else "")


def _settings_fallback(params: dict) -> str:
    """A name for a prompt-less, otherwise-undistinguished settings group."""
    bits = []
    if "width" in params and "height" in params:
        bits.append(f"{params['width']}×{params['height']}")
    for key in ("steps", "cfg"):
        if key in params:
            bits.append(f"{key} {params[key]}")
    return ", ".join(bits) or "(default settings)"


def _distinguishing_keys(settings_list: list[dict]) -> set[str]:
    """Setting keys whose value is not identical across every group."""
    if len(settings_list) <= 1:
        return set()
    keys = set().union(*settings_list)
    return {
        key for key in keys
        if len({
            json.dumps(s[key], sort_keys=True, default=str) if key in s else "\x00"
            for s in settings_list
        }) > 1
    }


def settings_label(params: dict, distinguishing_keys=()) -> str:
    """A short, human-readable name for a settings group.

    Leads with the positive prompt, then appends the settings that set this
    group apart from its siblings so same-prompt folders stay tellable apart.
    """
    headline = _prompt_headline(params)
    detail_keys = [k for k in sorted(distinguishing_keys) if k != "positive_prompt"]
    if detail_keys:
        detail = ", ".join(f"{k} {_short_value(params.get(k))}" for k in detail_keys)
        return f"{headline} · {detail}" if headline else detail
    return headline or _settings_fallback(params)


def _group_ordered(rows, key):
    """Group rows by ``key(row)``, preserving first-appearance order of keys."""
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return list(grouped.items())


def _sig_key(media_type: str, workflow_name: str, signature: str, prefix: str = "") -> str:
    """A folder's stable key from its signature, tagged by level.

    The one-letter ``prefix`` (``m`` model, ``l`` LoRA, ``i`` source image; none
    for settings) keeps each level's key clear of the others' — a settings
    folder's segment is pure hex, so no prefixed key can collide with it in
    ``folder_meta``.
    """
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return f"{media_type}/{workflow_name}/{prefix}{digest}"


def _settings_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature)


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
    return _settings_key(
        media_type, workflow_name,
        settings_signature(workflow_name, row.get("params_json"), image_index),
    )


def _model_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "m")


def _lora_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "l")


def _source_image_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "i")


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
        return _model_key(media_type, workflow_name, model_signature(workflow_name, params_json))
    if level == "lora":
        return _lora_key(media_type, workflow_name, lora_signature(workflow_name, params_json))
    if level == "source_image":
        config = _input_image_config(parse_params(params_json).get("input_image"), image_index)
        return _source_image_key(media_type, workflow_name, config)
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
    return _settings_key(media_type, workflow_name, signature)


def legacy_preframe_settings_folder_key(row: dict) -> str:
    """The settings-folder key an image-conditioned row had before its start
    frame's configuration was folded into the key — :func:`canonical_settings`
    hashed with the input image dropped entirely (the pre-frame-config formula).

    The reconcile recomputes this to re-point a star or name made before that
    change onto the row's current settings folder. Equal to the current key for
    workflows that aren't image-conditioned, which never folded a frame in."""
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(
        canonical_settings(workflow_name, parse_params(row.get("params_json"))),
        sort_keys=True, default=str,
    )
    return _settings_key(media_type, workflow_name, signature)


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


def recent_generations(rows: list[dict], limit: int) -> list[dict]:
    """The most recently generated rows, newest first — the Recents shelf's list.

    "Generated" means this app produced the row, from a Generate tab or a gallery
    re-roll; an imported file discovered on disk (``source`` ``"imported"``) is not
    a recent *generation* and is left out. As in the tree, only rows that produced
    an output file appear — the shelf is a gallery of results, so a failed or
    in-flight run with nothing to show doesn't surface. ``rows`` arrive newest-first
    (the caller lists them by descending id), so the first ``limit`` survivors are
    the most recent.
    """
    generated = [
        row for row in rows
        if (row.get("source") or "generated") == "generated" and produced_output(row)
    ]
    return generated[:limit]


def _build_settings_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list[SettingsGroup]:
    """The settings-group leaves under one model, LoRA, or source-image folder.

    Rows collapse by settings signature (all non-instance params, plus an i2v's
    start-frame configuration), and each leaf's label is disambiguated only
    against its siblings under the same parent — so a value the folder above
    already pins (the model, the LoRA, and for an i2v the source image) is
    constant here and never re-appears in a settings name.
    """
    grouped = _group_ordered(
        rows, lambda r: settings_signature(wf_name, r.get("params_json"), image_index)
    )
    settings_dicts = [
        canonical_settings(wf_name, parse_params(sig_rows[0].get("params_json")))
        for _sig, sig_rows in grouped
    ]
    distinguishing = _distinguishing_keys(settings_dicts)
    groups = []
    for i, (sig, sig_rows) in enumerate(grouped):
        key = _settings_key(media_type, wf_name, sig)
        label, starred = _overlay(
            settings_label(settings_dicts[i], distinguishing), key, folder_meta
        )
        groups.append(SettingsGroup(key, label, sig_rows, starred))
    return groups


def _source_image_label(params: dict, image_index: dict) -> str:
    """The name of the source-image folder a video's start frame belongs to.

    The image generation's own folder label when the frame is a known generation
    (so a video's source folder reads the same as the image it animates), else the
    frame's bare filename, and ``"(no input image)"`` when there is none.
    """
    input_image = params.get("input_image")
    name = _frame_name(input_image)
    if not name:
        return "(no input image)"
    entry = (image_index or {}).get(name)
    return entry.label if entry is not None else _basename(_unannotated(input_image))


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
        key_for=lambda sig: _model_key(media_type, wf_name, sig),
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
        key_for=lambda sig: _lora_key(media_type, wf_name, sig),
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
    if media_type == "video" and _is_image_conditioned(wf_name):
        return _build_source_image_groups(media_type, wf_name, rows, folder_meta, image_index)
    return _build_settings_groups(media_type, wf_name, rows, folder_meta, image_index)


def _build_source_image_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict, image_index: dict
) -> list[SourceImageGroup]:
    """The source-image folders under one model/LoRA folder: videos split by the
    configuration of the start frame they animate, each holding its settings leaves.

    Keyed by that configuration (:func:`_input_image_config`), the same projection
    of the settings signature that the model and LoRA levels use for theirs — so
    re-rolls of one image stay together while differently configured frames split."""
    return _grouped_folders(
        rows, folder_meta, cls=SourceImageGroup,
        signature=lambda r: _input_image_config(
            parse_params(r.get("params_json")).get("input_image"), image_index
        ),
        key_for=lambda sig: _source_image_key(media_type, wf_name, sig),
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
    other image). Rows that produced no output file (failed or unfinished
    generations) are dropped first, so the tree holds only results
    worth showing. Folders appear
    in the order their first member appears in ``rows`` (the caller orders rows
    newest-first); a star never moves a folder — bookmarks are gathered by
    :func:`starred_folders` instead. ``folder_meta`` (keyed by each folder's
    stable ``key``) overrides the default label and supplies the star state.
    """
    folder_meta = folder_meta or {}
    rows = [row for row in rows if produced_output(row)]
    image_index = build_image_config_index(
        [row for row in rows if media_type_of_row(row) == "image"]
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
