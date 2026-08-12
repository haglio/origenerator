"""Which rows are enhanced, which await enhancement, and how to enhance one.

The thumbnail badge, the folder's Enhance All button, and the selection's
Enhance action all decide off these helpers, so "enhanced" means one thing
everywhere: the row went through the upscale + low-denoise re-sample tail —
either inline (its workflow's ``enhance`` toggle) or as a standalone
``image_enhance`` run over an existing image.
"""

from origenerator.gallery.output import (
    media_type_of_row,
    output_file_reference,
    produced_output,
    row_output_files,
)
from origenerator.gallery.signatures import _frame_name, parse_params
from origenerator.workflows import WORKFLOW_REGISTRY

ENHANCE_WORKFLOW = "image_enhance"

# The workflows that ran the enhance tail unconditionally, before it became a
# toggle: their rows carry the tail's params but no ``enhance`` flag.
_ALWAYS_ENHANCED = ("sdxl_t2i", "sdxl_pose_transfer")


def is_enhanced_row(row: dict) -> bool:
    """Whether this generation went through the enhance tail — what the green
    thumbnail badge marks. An explicit ``enhance`` param is authoritative;
    a standalone enhancer run always counts; and an SDXL row from the era the
    tail ran unconditionally (enhance params stored, no flag yet) counts too."""
    workflow = row.get("workflow_name") or ""
    if workflow == ENHANCE_WORKFLOW:
        return True
    params = parse_params(row.get("params_json"))
    if "enhance" in params:
        return bool(params["enhance"])
    return workflow in _ALWAYS_ENHANCED and "enhance_denoise" in params


def is_enhanceable_row(row: dict) -> bool:
    """Whether the standalone enhancer can take this row: a finished image.

    An already-enhanced image still qualifies — selecting one and choosing
    Enhance is a deliberate re-enhance; only the folder-wide button filters to
    the not-yet-enhanced (:func:`rows_awaiting_enhancement`)."""
    return media_type_of_row(row) == "image" and produced_output(row)


def enhanced_source_names(rows) -> set[str]:
    """The source-image names (comparison-keyed, like an i2v frame lookup) that
    already have a standalone enhance run among ``rows``."""
    names = set()
    for row in rows:
        if (row.get("workflow_name") or "") == ENHANCE_WORKFLOW:
            name = _frame_name(parse_params(row.get("params_json")).get("input_image"))
            if name:
                names.add(name)
    return names


def rows_awaiting_enhancement(folder_rows, all_rows) -> list[dict]:
    """The members of a folder its Enhance All button targets: finished images
    that neither ran the tail themselves nor already have a standalone enhance
    of their output (checked against ``all_rows``, since the enhanced copies
    live in the enhancer's own folder)."""
    done = enhanced_source_names(all_rows)
    awaiting = []
    for row in folder_rows:
        if not is_enhanceable_row(row) or is_enhanced_row(row):
            continue
        files = row_output_files(row)
        name = _frame_name(files[0].get("filename")) if files else ""
        if name and name in done:
            continue
        awaiting.append(row)
    return awaiting


def enhance_params_for(row: dict) -> dict | None:
    """The ``image_enhance`` params that enhance ``row``'s output: its file as
    the input, its own prompts steering the added texture, and — when the
    source recorded a checkpoint (the SDXL workflows) — that same checkpoint
    doing the refining, so an enhanced copy stays in its source's style.
    ``None`` when the row has no output file to enhance. The seed is left at
    the default; the launcher re-rolls it like any variation."""
    input_ref = output_file_reference(row_output_files(row))
    if input_ref is None:
        return None
    params = dict(WORKFLOW_REGISTRY[ENHANCE_WORKFLOW].default_params())
    src = parse_params(row.get("params_json"))
    params["input_image"] = input_ref
    params["positive_prompt"] = src.get("positive_prompt") or row.get("positive_prompt") or ""
    params["negative_prompt"] = src.get("negative_prompt") or row.get("negative_prompt") or ""
    checkpoint = src.get("checkpoint")
    if isinstance(checkpoint, str) and checkpoint:
        params["checkpoint"] = checkpoint
    return params
