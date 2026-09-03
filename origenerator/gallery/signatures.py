"""Row identity: parse a generation's stored params and reduce them to the
canonical keys that place it in the gallery tree.

Everything here answers "what recipe produced this row", independent of Qt and of
the folder structure itself: parsing ``params_json``, normalizing it against a
workflow's declared defaults, and hashing the facets the tree groups by (the full
settings, the model, the LoRA). The frame-identity helpers live here too because
:func:`settings_signature` folds an image-conditioned row's start-frame
configuration into the settings key.
"""

import json
from functools import lru_cache

from origenerator.file_refs import frame_name, reference_basename, unannotated
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.model_files import is_no_lora

# Params that identify a specific instance of a recipe rather than the recipe
# itself — dropped from a row's settings so reruns that differ only in these land
# in one folder. Seeds vary the sampling noise; ``input_image`` names the exact
# start-frame file an i2v ran on, and a re-roll regenerates that file. Dropping
# the raw filename keeps a video with its own re-rolls; the *configuration* that
# produced the frame is added back by :func:`settings_signature` so videos built
# from differently configured frames still split. See :func:`_input_image_config`.
# This static set serves only rows with no registered workflow (imports), where
# there's no template to ask; a registered row's instance keys are derived from
# its declared seed params instead (:func:`_workflow_instance_keys`), so a
# workflow growing a seed can't silently start splitting folders by it.
INSTANCE_KEYS = frozenset({"seed", "noise_seed", "audio_seed", "input_image"})

# Params that configure a row's *enhancement* rather than its recipe — also
# dropped from its settings, so an enhanced image and its unenhanced twin share
# one folder. An enhancement is a finish applied to an image, not a different
# image: the standalone enhancer already folds its result onto the row it
# upgrades without moving it, and the workflows' inline ``enhance`` toggle means
# the same thing. This static set serves rows with no registered workflow
# (imports); a registered row's keys come from its template instead
# (:meth:`WorkflowTemplate.enhance_keys`), so a workflow growing another enhance
# knob can't silently start splitting folders by it.
ENHANCE_KEYS = frozenset({"enhance", "enhance_scale", "enhance_steps", "enhance_denoise"})

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


def _registered(workflow_name: str | None):
    """The registered WorkflowTemplate for ``workflow_name``, or ``None``."""
    return WORKFLOW_REGISTRY.get(workflow_name or "")


def _grouping_version(workflow_name: str | None, workflow_version: str | None) -> str:
    """The workflow generation a row groups under: its stored version when that
    names a concrete one, else the workflow's current registered version.

    Folding this into the settings key is what puts different generations of a
    workflow in different folders. When a workflow's recipe changes (a v002 SDXL
    render vs a v003 one with the enhance tail), its outputs look different, but
    default-normalization would merge them: an old row lacking the new params is
    filled with their defaults (:func:`canonical_settings`) and so hashes like a
    new run. A row with no concrete version — a live form's prospective settings
    (``None``), or an import's best-effort metadata (``"imported"``/
    ``"unknown"``) — takes the current version, preserving the property that a
    sparse import and a full re-roll of it group together.
    """
    if workflow_version and workflow_version not in ("imported", "unknown"):
        return workflow_version
    wf = _registered(workflow_name)
    return wf.version if wf else ""


@lru_cache(maxsize=None)
def _workflow_instance_keys(workflow_name: str) -> frozenset:
    """A registered workflow's per-instance keys: every seed param it declares
    (sampler and foley alike — a variation re-rolls them all) plus the start
    frame. Cached because ``seed_keys()`` walks ``param_definitions()``, which
    scans the model directories."""
    return frozenset(_registered(workflow_name).seed_keys()) | {"input_image"}


@lru_cache(maxsize=None)
def _workflow_enhance_keys(workflow_name: str) -> frozenset:
    """A registered workflow's enhancement-layer keys (see :data:`ENHANCE_KEYS`).
    Cached for the same reason as :func:`_workflow_instance_keys` — it too walks
    ``param_definitions()``."""
    return frozenset(_registered(workflow_name).enhance_keys())


def workflow_enhance_keys(workflow_name: str | None) -> frozenset:
    """The param keys that configure ``workflow_name``'s enhancement rather than
    its recipe, falling back to the static :data:`ENHANCE_KEYS` for a workflow
    with no registered template."""
    wf = _registered(workflow_name)
    return _workflow_enhance_keys(workflow_name) if wf is not None else ENHANCE_KEYS


def is_image_conditioned(workflow_name: str | None) -> bool:
    """True when a workflow drives its output from an ``input_image`` — an i2v
    whose start frame is itself (usually) a generation with its own settings."""
    wf = _registered(workflow_name)
    return wf is not None and "input_image" in wf.default_params()


def canonical_settings(workflow_name: str | None, params: dict) -> dict:
    """The settings that place a row in a folder, normalized so a row's provenance
    can't split it from its own re-roll.

    For a registered workflow this is exactly its non-instance ``default_params``
    keys, valued from the row where present and the workflow default otherwise —
    so a sparse import (which recorded only a few keys) and a full re-roll of it
    (``prepared_params`` fills every default) hash the same, and stored keys the
    workflow doesn't define (an i2v import's in-graph-derived ``width``/``height``,
    raw sampler-node fields) never split a folder. Falls back to dropping only the
    per-instance and enhancement keys when the workflow is unknown — there are then
    no defaults to normalize against.

    The enhancement layer (:data:`ENHANCE_KEYS`) is dropped alongside the
    per-instance keys: whether a render ran the enhance tail, and how, doesn't
    make it a different image.
    """
    wf = _registered(workflow_name)
    if wf is None:
        return {k: v for k, v in settings_only(params).items() if k not in ENHANCE_KEYS}
    ungrouped = _workflow_instance_keys(workflow_name) | _workflow_enhance_keys(workflow_name)
    return {
        key: params.get(key, default)
        for key, default in wf.default_params().items()
        if key not in ungrouped
    }


def enhance_settings(workflow_name: str | None, params: dict) -> dict:
    """A row's enhancement-layer params, normalized against the workflow's
    defaults exactly as :func:`canonical_settings` normalizes its recipe.

    Deliberately absent from every current key. The one caller is the reconcile's
    pre-layer legacy formula
    (:func:`~origenerator.gallery.tree.legacy_preenhance_settings_folder_keys`),
    which must reproduce the signature these params used to be part of.
    """
    keys = workflow_enhance_keys(workflow_name)
    wf = _registered(workflow_name)
    if wf is None:
        return {k: v for k, v in params.items() if k in keys}
    return {
        key: params.get(key, default)
        for key, default in wf.default_params().items()
        if key in keys
    }


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

    Empty for a workflow with no LoRA; every row then shares one empty signature,
    collapsing the model folder's LoRA level to a single "(no LoRA)" folder.
    """
    wf = _registered(workflow_name)
    return tuple(wf.lora_keys) if wf else ()


@lru_cache(maxsize=None)
def workflow_param_order(workflow_name: str | None) -> tuple[str, ...]:
    """The param keys a workflow lays out in its form, in that order.

    This is the single order both surfaces present settings in: the Generate form
    builds its rows straight from ``param_definitions()``, and the gallery info
    pane sorts a row's stored params by this so every generation groups the same
    way regardless of the order its JSON was serialized in. Empty for an unknown
    workflow (an import with no registered template), leaving the caller to fall
    back to the stored order. Cached because the order is static per workflow —
    so this pays ``param_definitions()``'s model-directory scan at most once each.
    """
    wf = _registered(workflow_name)
    return tuple(pd.key for pd in wf.param_definitions()) if wf else ()


def _keyed_signature(keys: tuple[str, ...], params: dict) -> str:
    """Canonical, order-stable key from the values ``params`` holds for ``keys``."""
    return json.dumps([params.get(key) for key in keys], default=str)


def _values_signature(keys: tuple[str, ...], params_json: str | None) -> str:
    """Canonical, order-stable key from the values a row recorded for ``keys``."""
    return _keyed_signature(keys, parse_params(params_json))


def _named_loras(keys: tuple[str, ...], params: dict) -> dict:
    """``params`` narrowed to the LoRA ``keys`` that actually name a LoRA — the
    "None" sentinel and empty values dropped. A bypassed LoRA then groups and
    labels as no LoRA at all, the same as an import whose graph had no LoRA node.
    """
    return {k: params.get(k) for k in keys if not is_no_lora(params.get(k))}


def model_signature(workflow_name: str | None, params_json: str | None) -> str:
    """Canonical key for grouping a workflow's rows by the model they used."""
    return _values_signature(workflow_model_keys(workflow_name), params_json)


def lora_signature(workflow_name: str | None, params_json: str | None) -> str:
    """Canonical key for grouping a workflow's rows by the LoRA(s) they used.

    A "None"/empty LoRA reads as no LoRA (see :func:`_named_loras`), so a run
    that bypassed a LoRA shares one signature with a no-LoRA import.
    """
    keys = workflow_lora_keys(workflow_name)
    return _keyed_signature(keys, _named_loras(keys, parse_params(params_json)))


# The reference-reading trio, under the names this module's callers grew up
# with. One reading of a file reference serves the whole app now
# (:mod:`origenerator.file_refs`); these stay so nothing here has to be re-said.
_basename = reference_basename
_unannotated = unannotated
_frame_name = frame_name


def _outputs_video(workflow_name: str | None) -> bool:
    """True when a workflow's results are videos — the one kind whose folders grow
    a source-image tier under their LoRA folders."""
    wf = _registered(workflow_name)
    return wf is not None and wf.output_type == "video"


def _input_image_config(input_image: str | None, image_index: dict | None,
                        *, identify: bool = False) -> str:
    """The grouping key for a row's start frame.

    ``identify`` picks which question is being asked of the frame. *Which picture
    is it* (``True``) is what a video's folders need: their source-image tier means
    one picture, and every settings folder under that tier explores the same
    frame — a different prompt, a different CFG — so opening any of them must
    show videos of the one image. *What configuration produced it* (``False``,
    the default) is what everything else needs, where there is no such tier and a
    batch of enhances of a dozen different pictures is one folder of work.

    Identity is the generation that produced the frame, so a picture answers as
    itself however it is named: an enhanced image keeps its original file listed
    beside the enhanced one, and a video that ran on either is a video of that
    picture. Both modes fall back to the frame's own filename when it isn't a
    known generation (hand-picked, external, or since deleted) — distinct frames
    still separate — and to ``""`` when there is no input image at all.

    Videos grouped by configuration here until 2026-08-18, so that a video stayed
    with its own image-seed re-rolls: a fresh draw of the same settings is the
    same recipe, so it read as the same folder. But two draws of one prompt are
    two different pictures, and collecting them made a source-image folder that
    held several — precisely what that tier promises it never does. A re-drawn
    frame now opens its own folder, which is what a new picture is.
    """
    name = _frame_name(input_image)
    if not name:
        return ""
    entry = (image_index or {}).get(name)
    if entry is None:
        return name
    if identify:
        return entry.prompt_id or name
    return entry.signature


def rows_in_settings(rows, key, image_index=None):
    """The rows (in the given order) whose settings match ``key`` — a
    ``(workflow_name, signature)`` pair, as produced by pairing a workflow with
    :func:`settings_signature`. ``image_index`` positions image rows for the
    signature (see :func:`build_image_config_index`). Empty for a ``None`` key.

    The shared predicate behind "everything in this settings folder" — the config
    tabs' seeded history and a tab's most-recent-matching preview both read it.
    """
    if key is None:
        return []
    workflow_name, signature = key
    return [
        row for row in rows
        if (row.get("workflow_name") or "") == workflow_name
        and settings_signature(workflow_name, row.get("params_json"), image_index,
                               workflow_version=row.get("workflow_version")) == signature
    ]


def settings_signature(
    workflow_name: str | None,
    params_json: str | None,
    image_index: dict | None = None,
    workflow_version: str | None = None,
) -> str:
    """Canonical grouping key: a row's normalized settings (see
    :func:`canonical_settings`), order-independent — the enhancement layer
    excluded, so an enhanced render keys the same as its unenhanced twin.

    For an image-conditioned workflow the start frame is folded in — resolved
    through ``image_index`` (see :func:`build_image_config_index`) — so rows built
    from different frames get distinct keys. A video folds in *which picture* the
    frame is, because a video is filed under that picture's own folder;
    anything else folds in the frame's configuration, so a batch of enhances of
    many pictures stays one folder of work (see :func:`_input_image_config`).
    ``image_index`` may be omitted for rows that aren't image-conditioned.

    The workflow generation is folded in too (see :func:`_grouping_version`), so
    rows made before and after a workflow's recipe changed never share a key. A
    stored row passes its ``workflow_version`` column; ``None`` (a live form's
    prospective settings) means the current version.
    """
    params = parse_params(params_json)
    settings = {
        **canonical_settings(workflow_name, params),
        "workflow_version": _grouping_version(workflow_name, workflow_version),
    }
    if is_image_conditioned(workflow_name):
        settings = {
            **settings,
            "input_image_config": _input_image_config(
                params.get("input_image"), image_index,
                identify=_outputs_video(workflow_name),
            ),
        }
    return json.dumps(settings, sort_keys=True, default=str)
