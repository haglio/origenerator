"""Pure gallery model: classify and group generations into a folder tree.

The gallery view organizes generations as nested folders:
media type (Images/Videos) -> workflow -> model -> [LoRA] -> settings group
(rows sharing every setting except per-instance ones: the seed and, for i2v, the
input image, since a re-roll regenerates it). A workflow's runs split by which
model produced them, since the same workflow can yield dramatically different
output per model; a workflow that declares LoRA keys splits once more, by LoRA,
beneath each model — so variants that share a base model but differ in LoRA land
in sibling folders. Workflows with no LoRA skip that level. This module owns the
grouping logic with no Qt dependency so it can be unit-tested directly.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from origenerator.media import media_type_from_filename, sibling_of_type
from origenerator.workflows import WORKFLOW_REGISTRY

# Params that identify a specific instance of a recipe rather than the recipe
# itself — collapsed so reruns that differ only in these land in one folder.
# Seeds vary the sampling noise; ``input_image`` names an i2v's start frame, and
# a re-roll regenerates that image, so two videos differing only by their
# (freshly generated) input image are still the same recipe and belong together.
INSTANCE_KEYS = frozenset({"seed", "noise_seed", "input_image"})

MEDIA_LABELS = {"image": "Images", "video": "Videos"}

# File extensions stripped from a model filename to make a tidy folder label.
MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".sft")


def parse_params(params_json: str | None) -> dict:
    """Parse a row's ``params_json`` into a dict, tolerating bad data."""
    if not params_json:
        return {}
    try:
        params = json.loads(params_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return params if isinstance(params, dict) else {}


def settings_only(params: dict) -> dict:
    """The params that define a settings group — everything except the keys that
    only pick a specific instance of it (seeds and the i2v input image)."""
    return {k: v for k, v in params.items() if k not in INSTANCE_KEYS}


def canonical_settings(workflow_name: str | None, params: dict) -> dict:
    """The settings that place a row in a folder, normalized so a row's provenance
    can't split it from its own re-roll.

    For a registered workflow this is exactly its non-instance ``default_params``
    keys, valued from the row where present and the workflow default otherwise —
    so a sparse import (which recorded only a few keys) and a full re-roll of it
    (``prepared_params`` fills every default) hash the same, and stored keys the
    workflow doesn't define (an i2v import's in-graph-derived ``width``/``height``,
    raw sampler-node fields) never split a folder. Falls back to dropping only the
    per-instance keys when the workflow is unknown — there are then no defaults to
    normalize against.
    """
    wf = _registered(workflow_name)
    if wf is None:
        return settings_only(params)
    return {
        key: params.get(key, default)
        for key, default in wf.default_params().items()
        if key not in INSTANCE_KEYS
    }


def settings_signature(workflow_name: str | None, params_json: str | None) -> str:
    """Canonical grouping key: a row's normalized settings (see
    :func:`canonical_settings`), order-independent."""
    return json.dumps(
        canonical_settings(workflow_name, parse_params(params_json)),
        sort_keys=True, default=str,
    )


def _registered(workflow_name: str | None):
    """The registered WorkflowTemplate for ``workflow_name``, or ``None``."""
    return WORKFLOW_REGISTRY.get(workflow_name or "")


def workflow_output_type(workflow_name: str | None) -> str | None:
    """Return the registered workflow's ``output_type``, or ``None`` if unknown."""
    wf = _registered(workflow_name)
    return wf.output_type if wf else None


def workflow_model_keys(workflow_name: str | None) -> tuple[str, ...]:
    """The param keys whose values name the model a workflow's row ran with."""
    wf = _registered(workflow_name)
    return tuple(wf.model_keys) if wf else ()


def workflow_lora_keys(workflow_name: str | None) -> tuple[str, ...]:
    """The param keys whose values name the LoRA(s) a workflow's row ran with.

    Empty for a workflow with no LoRA, which the gallery reads as "draw no LoRA
    level" (every row then shares one empty signature).
    """
    wf = _registered(workflow_name)
    return tuple(wf.lora_keys) if wf else ()


def _values_signature(keys: tuple[str, ...], params_json: str | None) -> str:
    """Canonical, order-stable key from the values a row recorded for ``keys``."""
    params = parse_params(params_json)
    return json.dumps([params.get(key) for key in keys], default=str)


def model_signature(workflow_name: str | None, params_json: str | None) -> str:
    """Canonical key for grouping a workflow's rows by the model they used."""
    return _values_signature(workflow_model_keys(workflow_name), params_json)


def lora_signature(workflow_name: str | None, params_json: str | None) -> str:
    """Canonical key for grouping a workflow's rows by the LoRA(s) they used."""
    return _values_signature(workflow_lora_keys(workflow_name), params_json)


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


def _basename(path: str) -> str:
    """Final path segment, tolerant of either OS separator."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


# ComfyUI's LoadImage annotates a non-input source as "name [output|input|temp]".
_TYPE_ANNOTATION = frozenset({"[output]", "[input]", "[temp]"})


def _unannotated(image_ref: str) -> str:
    """A LoadImage value stripped of any trailing "[output]"-style type tag, so a
    re-roll's annotated output reference compares by plain filename."""
    stem, _, tag = image_ref.rpartition(" ")
    return stem if stem and tag in _TYPE_ANNOTATION else image_ref


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
    target = _basename(_unannotated(input_image)).lower()
    for image in image_rows:
        for f in row_output_files(image):
            if _basename(f.get("filename", "")).lower() == target:
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


@dataclass
class SettingsGroup:
    key: str
    label: str
    rows: list[dict]
    starred: bool = False


@dataclass
class LoraGroup:
    key: str
    label: str
    children: list[SettingsGroup]
    starred: bool = False


@dataclass
class ModelGroup:
    key: str
    label: str
    # Either LoraGroups (when the workflow declares LoRA keys) or, when it does
    # not, SettingsGroups directly — a model folder skips the LoRA level then.
    children: list
    starred: bool = False


@dataclass
class WorkflowGroup:
    key: str
    workflow_name: str
    label: str
    model_groups: list[ModelGroup]
    starred: bool = False


@dataclass
class MediaGroup:
    key: str
    media_type: str
    label: str
    workflow_groups: list[WorkflowGroup]
    starred: bool = False


def folder_level(group) -> str | None:
    """Which recipe-hierarchy level a folder sits at: ``"workflow"``, ``"model"``,
    or ``"lora"`` — or ``None`` for the media roots and settings leaves.

    Powers the per-level badge the gallery draws on tree rows and browser tiles:
    a media folder is self-evidently Images/Videos and a settings leaf is where
    the generations themselves live, so neither needs one.
    """
    for cls, level in (
        (WorkflowGroup, "workflow"), (ModelGroup, "model"), (LoraGroup, "lora")
    ):
        if isinstance(group, cls):
            return level
    return None


def child_groups(group) -> list:
    """The sub-folders directly under a folder (empty for a settings leaf)."""
    if isinstance(group, MediaGroup):
        return group.workflow_groups
    if isinstance(group, WorkflowGroup):
        return group.model_groups
    if isinstance(group, (ModelGroup, LoraGroup)):
        return group.children
    return []


def rows_under(group) -> list[dict]:
    """Every generation beneath a folder, at any depth."""
    if isinstance(group, SettingsGroup):
        return list(group.rows)
    return [row for child in child_groups(group) for row in rows_under(child)]


def group_level(group) -> str:
    """Which tier of the tree ``group`` sits at: media, workflow, model, lora, or
    settings. A bookmark records its tier so its key can be recomputed from a
    member row under whatever key formula is current (see
    :func:`folder_key_at_level`)."""
    if isinstance(group, MediaGroup):
        return "media"
    if isinstance(group, WorkflowGroup):
        return "workflow"
    if isinstance(group, ModelGroup):
        return "model"
    if isinstance(group, LoraGroup):
        return "lora"
    return "settings"


def _group_ordered(rows, key):
    """Group rows by ``key(row)``, preserving first-appearance order of keys."""
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return list(grouped.items())


def _sig_key(media_type: str, workflow_name: str, signature: str, prefix: str = "") -> str:
    """A folder's stable key from its signature, tagged by level.

    The one-letter ``prefix`` (``m`` model, ``l`` LoRA; none for settings) keeps
    each level's key clear of the others' — a settings folder's segment is pure
    hex, so no prefixed key can collide with it in ``folder_meta``.
    """
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    return f"{media_type}/{workflow_name}/{prefix}{digest}"


def _settings_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature)


def settings_folder_key(row: dict) -> str:
    """The key of the settings-folder leaf a row belongs to in the gallery tree.

    Mirrors how :func:`build_gallery_tree` keys that leaf — media type, workflow
    name, settings signature — so an in-flight row (which has no output yet and so
    never appears in the tree itself) can still be matched to the folder it joins.
    """
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    return _settings_key(media_type, workflow_name, settings_signature(workflow_name, row.get("params_json")))


def _model_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "m")


def _lora_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "l")


def folder_key_at_level(row: dict, level: str) -> str:
    """The key of the ``level``-tier folder ``row`` belongs to, recomputed from the
    row under the *current* key formulas.

    A bookmark stores its tier and a representative member row; recomputing here
    re-derives the folder's key so a star or custom name follows the folder even
    after a key formula changes — the silent orphaning the reconcile undoes."""
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
    if level == "settings":
        return settings_folder_key(row)
    raise ValueError(f"unknown folder level: {level!r}")


def legacy_settings_folder_key(row: dict) -> str:
    """The settings-folder key ``row`` had under the pre-normalization formula:
    ``settings_only`` hashed with sort_keys, before :func:`canonical_settings`.

    That change is the one historical key formula shift that orphaned bookmarks
    made before it. The reconcile recomputes this to re-point such a stale star or
    name onto the row's current settings folder."""
    media_type = media_type_of_row(row)
    workflow_name = row.get("workflow_name") or "unknown"
    signature = json.dumps(settings_only(parse_params(row.get("params_json"))), sort_keys=True)
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


def _build_settings_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict
) -> list[SettingsGroup]:
    """The settings-group leaves under one model or LoRA folder.

    Rows collapse by settings signature (all non-seed params), and each leaf's
    label is disambiguated only against its siblings under the same parent — so a
    value the folder above already pins (the model, and the LoRA) is constant
    here and never re-appears in a settings name.
    """
    grouped = _group_ordered(
        rows, lambda r: settings_signature(wf_name, r.get("params_json"))
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


def _grouped_folders(rows, folder_meta, *, signature, key_for, label_for, children_for, cls):
    """Build one folder level: order rows by ``signature``, then key + label +
    overlay each folder and recurse for its children.

    The model and LoRA levels are the same folder-building contract over
    different params, so both go through here — differing only in the callables.
    """
    groups = []
    for sig, sub_rows in _group_ordered(rows, signature):
        key = key_for(sig)
        params = parse_params(sub_rows[0].get("params_json"))
        label, starred = _overlay(label_for(params), key, folder_meta)
        groups.append(cls(key, label, children_for(sub_rows), starred))
    return groups


def _build_model_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict
) -> list[ModelGroup]:
    """The model folders under one workflow, each holding its LoRA folders — or,
    for a LoRA-less workflow, its settings leaves directly."""
    return _grouped_folders(
        rows, folder_meta, cls=ModelGroup,
        signature=lambda r: model_signature(wf_name, r.get("params_json")),
        key_for=lambda sig: _model_key(media_type, wf_name, sig),
        label_for=lambda params: model_label(wf_name, params),
        children_for=lambda sub: _build_under_model(media_type, wf_name, sub, folder_meta),
    )


def _build_under_model(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict
) -> list:
    """A model folder's children: LoRA folders when the workflow declares LoRA
    keys, else settings leaves directly (LoRA-less workflows skip that level)."""
    if workflow_lora_keys(wf_name):
        return _build_lora_groups(media_type, wf_name, rows, folder_meta)
    return _build_settings_groups(media_type, wf_name, rows, folder_meta)


def _build_lora_groups(
    media_type: str, wf_name: str, rows: list[dict], folder_meta: dict
) -> list[LoraGroup]:
    """The LoRA folders under one model, each holding its settings leaves."""
    return _grouped_folders(
        rows, folder_meta, cls=LoraGroup,
        signature=lambda r: lora_signature(wf_name, r.get("params_json")),
        key_for=lambda sig: _lora_key(media_type, wf_name, sig),
        label_for=lambda params: lora_label(wf_name, params),
        children_for=lambda sub: _build_settings_groups(media_type, wf_name, sub, folder_meta),
    )


def build_gallery_tree(
    rows: list[dict], folder_meta: dict[str, dict] | None = None
) -> list[MediaGroup]:
    """Nest rows into media -> workflow -> model -> [LoRA] -> settings folders.

    The LoRA level appears only under workflows that declare LoRA keys. Rows that
    produced no output file (failed or unfinished generations) are
    dropped first, so the tree holds only results worth showing. Folders appear
    in the order their first member appears in ``rows`` (the caller orders rows
    newest-first); a star never moves a folder — bookmarks are gathered by
    :func:`starred_folders` instead. ``folder_meta`` (keyed by each folder's
    stable ``key``) overrides the default label and supplies the star state.
    """
    folder_meta = folder_meta or {}
    rows = [row for row in rows if produced_output(row)]
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
                _build_model_groups(media_type, wf_name, wf_rows, folder_meta),
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
