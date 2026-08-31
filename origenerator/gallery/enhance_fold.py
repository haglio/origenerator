"""Folding a finished enhancement back into the image it upgraded.

An enhancement is not a generation of its own: its result is an upgraded layer
on an existing image. The standalone ``image_enhance`` workflow is machinery —
its job runs under a transient row (so in-flight cards and restart reconnection
work), and the moment it completes :func:`fold_enhancement` moves its output
onto the source row: the source keeps its folder, star and identity, its
thumbnail and preview become the enhanced pixels, its pre-enhance file stays
listed (and on disk) as the original, and the transient row is deleted.
:func:`fold_completed_enhancements` runs the same fold at startup, healing
completions that landed while the app was closed — and retroactively converting
older rows recorded as ``image_enhance`` generations.

**This module is the whole of the gallery package's persistence.** Everything
else under :mod:`origenerator.gallery` takes rows and answers questions about
them; only these two functions take a database and change what is in it, and
``tests/test_gallery_facade.py`` holds that at one file. So a reader asking what
the gallery can alter has one file to read, and a caller wanting the pure half
can have it without a database at all.

Its own home is beside the other top-level modules that touch the database
rather than inside this package, which would leave the gallery free of
persistence outright — that move is the second half of the audit's
`E_workflows_gallery_voice/design/002` and belongs with the root package's own
item, since :func:`fold_completed_enhancements` is called from the boot
sequence.
"""

import json
import logging

from origenerator.gallery.enhance import (
    enhance_level_params,
    is_enhance_product_row,
)
from origenerator.gallery.enhance_settings import ENHANCE_WORKFLOW, level_knobs
from origenerator.gallery.output import (
    media_type_of_row,
    parse_file_list,
    row_output_files,
)
from origenerator.gallery.signatures import parse_params
from origenerator.gallery.source_image import source_image_id_for

logger = logging.getLogger(__name__)


def _history_entries(files: list[dict], params: dict,
                     run_id: int | None) -> list[dict]:
    """One ``enhance_history`` entry per file this enhance produced: the file's
    name, the knobs that made it — so a level can name its own settings even
    after the transient job row is gone — and ``run_id``, the id that row had.

    The id is kept for the same reason: the row about to be deleted is what said
    where this enhancement falls in the library's order, and the image it
    upgraded sorts on the shelf by the newest one it has received
    (:func:`enhancement_recency`)."""
    settings = level_knobs(params)
    return [
        {"filename": f.get("filename"), "params": settings, "run_id": run_id}
        for f in files if f.get("filename")
    ]


def fold_enhancement(db, enhance_row: dict,
                     image_rows: list[dict] | None = None) -> str | None:
    """Fold a finished standalone enhance into the image it enhanced.

    The source row becomes the enhanced image in place: the enhanced file
    leads its ``output_files`` (so previews, thumbnails, and anything built
    from the row use the upgraded pixels), every earlier file stays listed —
    the pre-enhance original remains on disk, reachable from the metadata
    block, and no later import scan finds an orphan — and ``original_files``
    records what the row held before its first enhance, which is also what
    marks it enhanced. The settings this run used are appended to
    ``enhance_history``, so the level it just added can be told apart from the
    ones already there (:func:`enhance_levels`). Folder membership, star,
    params and identity are untouched: enhancing never moves or duplicates a
    node. The transient enhance row is deleted (row only — its file now
    belongs to the source).

    Returns the upgraded source's prompt_id, or ``None`` (and folds nothing)
    when the enhance produced no file or its source image is no longer in the
    database — such a row is left alone rather than half-migrated.

    ``image_rows`` is the pool the start frame is matched against, for a caller
    that already holds one: the startup sweep folds a whole backlog at once, and
    re-reading every generation (graphs included) per fold is the difference
    between a launch and a wait.
    """
    enhanced_files = row_output_files(enhance_row)
    if not enhanced_files:
        return None
    input_image = parse_params(enhance_row.get("params_json")).get("input_image")
    if image_rows is None:
        image_rows = db.list_generations()
    candidates = [
        r for r in image_rows
        if r.get("prompt_id") != enhance_row.get("prompt_id")
        and media_type_of_row(r) == "image"
    ]
    source_id = source_image_id_for(input_image, candidates)
    if source_id is None:
        return None
    source = db.get_generation(source_id)
    updates = {
        "output_files": json.dumps(enhanced_files + row_output_files(source)),
        "enhance_history": json.dumps(
            _history_entries(enhanced_files, enhance_level_params(enhance_row),
                             enhance_row.get("id"))
            + parse_file_list(source.get("enhance_history"))
        ),
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
    """Fold every finished enhancement standing as a row of its own into the
    image it upgraded.

    The startup half of the fold: completions that landed while the app was
    closed (reconciled from /history), rows from before enhancement folded at
    all — the retroactive fix that turns old "Image Enhance generations" into
    upgrades of the images they enhanced — and the ones the import scan
    reconstructed from bare files, which is how a branch session's enhance
    arrives (:func:`is_enhance_product_row`). In-flight rows are left for their
    live completion; sourceless rows (the enhanced image was deleted) are left
    as they are. Returns how many rows were folded.

    Oldest first, so a stack of enhancements lands in the order it was made and
    an enhance *of* an enhance finds its input already folded onto the image it
    belongs to. The pool each fold matches against is read once and kept current
    as folds land, because reading it per row would mean pulling every stored
    graph in the library through memory for each one.
    """
    rows = sorted(db.list_generations(), key=lambda r: r.get("id") or 0)
    pool = [r for r in rows if media_type_of_row(r) == "image"]
    folded = 0
    for row in rows:
        if row.get("status") != "completed":
            continue
        if (row.get("workflow_name") or "") != ENHANCE_WORKFLOW                 and not is_enhance_product_row(row):
            continue
        source_id = fold_enhancement(db, row, image_rows=pool)
        if source_id is None:
            continue
        folded += 1
        # The pool's own copies go stale the moment a fold rewrites the source:
        # refresh the one that changed (so the file it just gained can be found
        # by an enhance made from it) and drop the row that no longer exists.
        upgraded = db.get_generation(source_id)
        pool = [r for r in pool if r.get("prompt_id") != row.get("prompt_id")]
        for candidate in pool:
            if candidate.get("prompt_id") == source_id and upgraded is not None:
                candidate.update(upgraded)
    if folded:
        logger.info("Folded %d enhancements into their source images", folded)
    return folded
