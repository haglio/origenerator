"""Pure gallery model: classify and group generations into a folder tree.

The gallery view organizes generations as nested folders:
media type (Images/Videos) -> workflow -> model -> [LoRA] -> settings group
(rows sharing every setting except the seed). A workflow's runs split by which
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

# Params that vary the output without changing its "settings" — collapsed so
# reruns that differ only by seed land in the same folder.
SEED_KEYS = frozenset({"seed", "noise_seed"})

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
    """The params that define a settings group — everything except seeds."""
    return {k: v for k, v in params.items() if k not in SEED_KEYS}


def settings_signature(params_json: str | None) -> str:
    """Canonical key for grouping: the params minus seeds, order-independent."""
    return json.dumps(settings_only(parse_params(params_json)), sort_keys=True)


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


def find_source_image_id(row: dict, image_rows: list[dict]) -> str | None:
    """Return the prompt_id of the image used as this row's ``input_image``.

    Image-to-video rows reference their start frame by filename; match it to an
    image generation by basename. Returns ``None`` when the row has no input
    image or none of ``image_rows`` produced a file with that name.
    """
    input_image = parse_params(row.get("params_json")).get("input_image")
    if not input_image:
        return None
    target = _basename(input_image).lower()
    for image in image_rows:
        for f in row_output_files(image):
            if _basename(f.get("filename", "")).lower() == target:
                return image["prompt_id"]
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


def _model_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "m")


def _lora_key(media_type: str, workflow_name: str, signature: str) -> str:
    return _sig_key(media_type, workflow_name, signature, "l")


def _overlay(label: str, key: str, folder_meta: dict) -> tuple[str, bool]:
    """Apply a folder's saved custom name and star, returning (label, starred)."""
    meta = folder_meta.get(key, {})
    return (meta.get("custom_name") or label, bool(meta.get("starred")))


def _starred_first(groups: list) -> list:
    """Stable-sort starred folders to the top, leaving order otherwise intact."""
    return sorted(groups, key=lambda g: not g.starred)


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
        rows, lambda r: settings_signature(r.get("params_json"))
    )
    settings_dicts = [
        settings_only(parse_params(sig_rows[0].get("params_json")))
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
    return _starred_first(groups)


def _grouped_folders(rows, folder_meta, *, signature, key_for, label_for, children_for, cls):
    """Build one folder level: order rows by ``signature``, key + label + overlay
    each folder, recurse for its children, and float starred folders first.

    The model and LoRA levels are the same folder-building contract over
    different params, so both go through here — differing only in the callables.
    """
    groups = []
    for sig, sub_rows in _group_ordered(rows, signature):
        key = key_for(sig)
        params = parse_params(sub_rows[0].get("params_json"))
        label, starred = _overlay(label_for(params), key, folder_meta)
        groups.append(cls(key, label, children_for(sub_rows), starred))
    return _starred_first(groups)


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
    newest-first), except that starred folders float to the top of their level.
    ``folder_meta`` (keyed by each folder's stable ``key``) overrides the
    default label and supplies the star state.
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
            _starred_first(workflow_groups), media_starred,
        ))
    return _starred_first(tree)
