"""Which rows are enhanced, which await enhancement, how to enhance one — and
folding a finished enhance back into the image it upgraded.

An enhancement is not a generation of its own: its result is an upgraded layer
on an existing image. The standalone ``image_enhance`` workflow is machinery —
its job runs under a transient row (so in-flight cards and restart reconnection
work), and the moment it completes, :func:`fold_enhancement` moves its output
onto the source row: the source keeps its folder, star and identity, its
thumbnail and preview become the enhanced pixels, its pre-enhance file stays
listed (and on disk) as the original, and the transient row is deleted.
:func:`fold_completed_enhancements` runs the same fold at startup, healing
completions that landed while the app was closed — and retroactively converting
any older rows recorded as ``image_enhance`` generations.

The thumbnail badge, the folder's Enhance All button, and the selection's
Enhance action all decide off the helpers here, so "enhanced" means one thing
everywhere: the row went through the upscale + low-denoise re-sample tail —
inline (its workflow's ``enhance`` toggle) or folded in from a standalone run.
"""

import json
import logging

from origenerator.gallery.output import (
    media_type_of_row,
    output_file_reference,
    parse_file_list,
    produced_output,
    row_output_files,
)
from origenerator.gallery.signatures import _frame_name, parse_params
from origenerator.gallery.source_image import source_image_id_for
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

ENHANCE_WORKFLOW = "image_enhance"

# The workflows that ran the enhance tail unconditionally, before it became a
# toggle: their rows carry the tail's params but no ``enhance`` flag.
_ALWAYS_ENHANCED = ("sdxl_t2i", "sdxl_pose_transfer")


def is_enhanced_row(row: dict) -> bool:
    """Whether this generation carries enhanced pixels — what the green
    thumbnail badge marks. A folded-in standalone enhance (``original_files``
    set) counts; an explicit ``enhance`` param is authoritative for inline
    runs; an SDXL row from the era the tail ran unconditionally (tail params
    stored, no flag yet) counts too."""
    if row.get("original_files"):
        return True
    workflow = row.get("workflow_name") or ""
    if workflow == ENHANCE_WORKFLOW:
        return True  # a transient/unfolded enhance row IS an enhanced image
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
    """The source-image names (comparison-keyed, like an i2v frame lookup) with
    an un-folded standalone enhance among ``rows`` — normally just the jobs
    still in flight, since a completed one folds into its source and vanishes.
    Keeps a second button press from re-queuing an image already cooking."""
    names = set()
    for row in rows:
        if (row.get("workflow_name") or "") == ENHANCE_WORKFLOW:
            name = _frame_name(parse_params(row.get("params_json")).get("input_image"))
            if name:
                names.add(name)
    return names


def rows_awaiting_enhancement(folder_rows, all_rows) -> list[dict]:
    """The members of a folder its Enhance All button targets: finished images
    that aren't enhanced and don't have an enhance already in flight (checked
    against ``all_rows``, where the transient job rows live)."""
    cooking = enhanced_source_names(all_rows)
    awaiting = []
    for row in folder_rows:
        if not is_enhanceable_row(row) or is_enhanced_row(row):
            continue
        names = {_frame_name(f.get("filename")) for f in row_output_files(row)}
        if names & cooking:
            continue
        awaiting.append(row)
    return awaiting


def enhance_params_for(row: dict) -> dict | None:
    """The ``image_enhance`` params that enhance ``row``'s output: its file as
    the input, its own prompts steering the added texture, and — when the
    source recorded a checkpoint (the SDXL workflows) — that same checkpoint
    doing the refining, so an enhanced image stays in its own style.

    An already-enhanced row re-enhances from its ORIGINAL file, not the
    enhanced one, so a deliberate re-enhance re-derives at a fresh seed rather
    than compounding upscale upon upscale. ``None`` when the row has no output
    file to enhance. The seed is left at the default; the launcher re-rolls it
    like any variation."""
    files = parse_file_list(row.get("original_files")) or row_output_files(row)
    input_ref = output_file_reference(files)
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


def fold_enhancement(db, enhance_row: dict) -> str | None:
    """Fold a finished standalone enhance into the image it enhanced.

    The source row becomes the enhanced image in place: the enhanced file
    leads its ``output_files`` (so previews, thumbnails, and anything built
    from the row use the upgraded pixels), every earlier file stays listed —
    the pre-enhance original remains on disk, reachable from the metadata
    block, and no later import scan finds an orphan — and ``original_files``
    records what the row held before its first enhance, which is also what
    marks it enhanced. Folder membership, star, params and identity are
    untouched: enhancing never moves or duplicates a node. The transient
    enhance row is deleted (row only — its file now belongs to the source).

    Returns the upgraded source's prompt_id, or ``None`` (and folds nothing)
    when the enhance produced no file or its source image is no longer in the
    database — such a row is left alone rather than half-migrated.
    """
    enhanced_files = row_output_files(enhance_row)
    if not enhanced_files:
        return None
    input_image = parse_params(enhance_row.get("params_json")).get("input_image")
    image_rows = [
        r for r in db.list_generations()
        if r.get("prompt_id") != enhance_row.get("prompt_id")
        and media_type_of_row(r) == "image"
    ]
    source_id = source_image_id_for(input_image, image_rows)
    if source_id is None:
        return None
    source = db.get_generation(source_id)
    updates = {
        "output_files": json.dumps(enhanced_files + row_output_files(source)),
    }
    if not source.get("original_files"):
        # First enhance: what the row holds now is the true original. A
        # re-enhance keeps this — the original is the pre-ANY-enhance file.
        updates["original_files"] = source.get("output_files")
    if enhance_row.get("thumbnail_path"):
        updates["thumbnail_path"] = enhance_row["thumbnail_path"]
    db.update_generation(source_id, **updates)
    db.delete_generation(enhance_row["prompt_id"])
    return source_id


def fold_completed_enhancements(db) -> int:
    """Fold every completed ``image_enhance`` row into its source image.

    The startup half of the fold: completions that landed while the app was
    closed (reconciled from /history), and rows from before enhancement folded
    at all — the retroactive fix that turns old "Image Enhance generations"
    into upgrades of the images they enhanced. In-flight rows are left for
    their live completion; sourceless rows (the enhanced image was deleted)
    are left as they are. Returns how many rows were folded.
    """
    folded = 0
    for row in db.list_generations():
        if (row.get("workflow_name") or "") != ENHANCE_WORKFLOW:
            continue
        if row.get("status") != "completed":
            continue
        if fold_enhancement(db, row) is not None:
            folded += 1
    if folded:
        logger.info("Folded %d enhancements into their source images", folded)
    return folded
