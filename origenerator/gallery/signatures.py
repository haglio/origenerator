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

from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.model_files import is_no_lora

# Params that identify a specific instance of a recipe rather than the recipe
# itself — dropped from a row's settings so reruns that differ only in these land
# in one folder. Seeds vary the sampling noise; ``input_image`` names the exact
# start-frame file an i2v ran on, and a re-roll regenerates that file. Dropping
# the raw filename keeps a video with its own re-rolls; the *configuration* that
# produced the frame is added back by :func:`settings_signature` so videos built
# from differently configured frames still split. See :func:`_input_image_config`.
INSTANCE_KEYS = frozenset({"seed", "noise_seed", "input_image"})

# ComfyUI's LoadImage annotates a non-input source as "name [output|input|temp]".
_TYPE_ANNOTATION = frozenset({"[output]", "[input]", "[temp]"})


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


def _is_image_conditioned(workflow_name: str | None) -> bool:
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


def _basename(path: str) -> str:
    """Final path segment, tolerant of either OS separator."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _unannotated(image_ref: str) -> str:
    """A LoadImage value stripped of any trailing "[output]"-style type tag, so a
    re-roll's annotated output reference compares by plain filename."""
    stem, _, tag = image_ref.rpartition(" ")
    return stem if stem and tag in _TYPE_ANNOTATION else image_ref


def _frame_name(image_ref: str | None) -> str:
    """The comparison key for an i2v start frame: its basename, lowercased, with
    any ``[output]``-style annotation stripped — so a LoadImage reference, an
    annotated re-roll output, and a stored output filename all match by the plain
    file they name."""
    return _basename(_unannotated(image_ref or "")).lower()


def _input_image_config(input_image: str | None, image_index: dict | None) -> str:
    """The grouping key for an i2v's start frame: the settings signature of the
    image generation that produced it, so a video groups with its own re-rolls
    (same config, a freshly regenerated frame) yet splits from videos built off a
    differently configured frame.

    Falls back to the frame's own filename when it isn't a known generation
    (hand-picked, external, or since deleted), so distinct frames still separate,
    and to ``""`` when there's no input image at all.
    """
    name = _frame_name(input_image)
    if not name:
        return ""
    entry = (image_index or {}).get(name)
    return entry.signature if entry is not None else name


def settings_signature(
    workflow_name: str | None,
    params_json: str | None,
    image_index: dict | None = None,
) -> str:
    """Canonical grouping key: a row's normalized settings (see
    :func:`canonical_settings`), order-independent.

    For an image-conditioned workflow the start frame's own configuration is
    folded in — resolved through ``image_index`` (see
    :func:`build_image_config_index`) — so videos built from differently
    configured frames get distinct keys while a video and its re-rolls (same
    frame config, a freshly regenerated file) share one. ``image_index`` may be
    omitted for rows that aren't image-conditioned.
    """
    params = parse_params(params_json)
    settings = canonical_settings(workflow_name, params)
    if _is_image_conditioned(workflow_name):
        settings = {
            **settings,
            "input_image_config": _input_image_config(params.get("input_image"), image_index),
        }
    return json.dumps(settings, sort_keys=True, default=str)
