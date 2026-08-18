"""Re-deriving the base render an inline enhance threw away, while the app is shut.

Before enhancement became a layer, a workflow with ``enhance`` on saved only the
finished picture: the base render was made on the way through and discarded, so
those rows carry one file and no "before" to compare it against.

They are recoverable, because they are reproducible. Diffusion is deterministic
given the same seed, model, sampler, scheduler, steps and cfg, and the enhance
tail hangs off the base pass without altering it — so re-running the recorded
recipe with the tail switched off produces exactly the pixels that pass produced
the first time.

It is GPU nobody asked for, though — one full render per row, and the library
here has well over a hundred — so doing it while the app is open would put every
one of them in front of the user's own work. It rides the same absence the
background experimenter does: queued as the app closes, cleared when it opens.
ComfyUI outlives the app and works through the batch alone; the next launch
folds whatever finished into the images it belongs to and drops whatever hadn't
started. How much goes is a time budget rather than a row count
(:data:`BATCH_MINUTES`), because a repair costs exactly one render and that is
seconds for an image and minutes for a video.

The rows it makes are repairs, not generations: tagged ``source="base_render"``,
kept out of the tree so a half-finished one never shows as a duplicate image,
and folded into their target the way a standalone enhance folds into the image
it upgraded.
"""

from __future__ import annotations

import json
import logging
import statistics

from origenerator import gallery
from origenerator.gallery.enhance import BASE_RENDER_SOURCE as SOURCE
from origenerator.gallery.output import is_in_progress
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# What an absence is allowed to spend on repairs, in minutes of GPU. Sized in
# time rather than rows because the cost of one repair is the cost of one
# render, and that is not a fixed thing: the first version of this handed out
# six per absence on the reasoning that a render is a night's work, when the
# rows needing repair are images this library finishes in a median of eight
# seconds — which would have drained a 147-row backlog over twenty-five
# evenings. The budget is read against what each workflow has actually taken
# here (:func:`typical_seconds`), so a backlog of slow renders still queues few.
BATCH_MINUTES = 45.0

# What one repair is assumed to cost where the library has never timed that
# workflow. Deliberately pessimistic: guessing high queues too few, which costs
# another absence, where guessing low queues a batch ComfyUI cannot finish and
# the next launch throws the remainder away.
UNTIMED_SECONDS = 60.0

# The params key carrying which row a re-render is repairing. Nothing in the
# graph reads it, and the gallery's grouping only ever asks a workflow for the
# keys it declares — so an extra key here can't split a folder or reach a node.
TARGET_KEY = "_base_render_of"


def rows_missing_their_base(rows: list[dict]) -> list[dict]:
    """Enhanced images that kept no original and whose recipe can be rebuilt.

    The badge says an enhancement happened; the absence of an original says the
    tail baked it in. Those two together are exactly the rows this can help. A
    row whose workflow isn't registered (an import) is passed over: there is no
    recipe to re-run, and guessing one would produce a "base" that is not this
    image's base at all.
    """
    out = []
    for row in rows:
        if row.get("source") == SOURCE:
            continue  # a repair in flight is not itself something to repair
        if gallery.media_type_of_row(row) != "image":
            continue
        if not gallery.is_enhanced_row(row) or gallery.original_files_of(row):
            continue
        if not gallery.produced_output(row):
            continue
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or "enhance" not in workflow.default_params():
            continue
        out.append(row)
    return out


def base_params_for(row: dict, workflow) -> dict:
    """The row's own recipe with the enhance tail switched off.

    Every other param — the seed above all — is reproduced exactly, because that
    is the whole basis for expecting the same pixels back. The target's id rides
    along under :data:`TARGET_KEY` so the finished render knows what it repairs.
    """
    params = dict(workflow.default_params())
    params.update(gallery.parse_params(row.get("params_json")))
    params["enhance"] = False
    params[TARGET_KEY] = row["prompt_id"]
    return params


def already_queued(rows: list[dict]) -> set[str]:
    """The ids of rows a re-render is already in flight for, so a second absence
    doesn't queue the same repair twice."""
    return {
        gallery.parse_params(r.get("params_json")).get(TARGET_KEY)
        for r in rows if r.get("source") == SOURCE and is_in_progress(r)
    } - {None}


def typical_seconds(rows: list[dict], workflow_name: str) -> float:
    """How long one run of ``workflow_name`` has actually taken in this library.

    The median of what it has recorded, so a handful of very slow runs (a model
    loaded from cold, a machine busy with something else) doesn't decide the
    budget for the rest. :data:`UNTIMED_SECONDS` where it has never been timed.
    """
    timed = [
        row["duration_seconds"] for row in rows
        if row.get("workflow_name") == workflow_name
        and row.get("status") == "completed"
        and row.get("duration_seconds")
    ]
    return statistics.median(timed) if timed else UNTIMED_SECONDS


def queue_base_renders(rows: list[dict], launch, limit: int | None = None,
                       budget_minutes: float = BATCH_MINUTES) -> int:
    """Hand ComfyUI a batch of base re-renders to run while the app is closed.

    ``launch(workflow, params)`` submits one and returns its prompt_id, or
    ``None`` when the launch didn't take. Returns how many were queued.

    The batch is as much as fits in ``budget_minutes`` of estimated GPU, priced
    per row from what its workflow has actually taken here — so a backlog of
    quick images goes in one absence and a backlog of slow ones does not get
    queued only for the next launch to discard it. ``limit`` caps the count on
    top of that, for a caller that wants a fixed number.
    """
    pending = already_queued(rows)
    cost: dict[str, float] = {}
    budget = budget_minutes * 60
    spent = 0.0
    queued = 0
    for row in rows_missing_their_base(rows):
        if limit is not None and queued >= limit:
            break
        if row["prompt_id"] in pending:
            continue
        name = row["workflow_name"]
        if name not in cost:
            cost[name] = typical_seconds(rows, name)
        if queued and spent + cost[name] > budget:
            break  # always at least one, however slow: the backlog has to move
        workflow = WORKFLOW_REGISTRY[name]
        if launch(workflow, base_params_for(row, workflow)) is not None:
            queued += 1
            spent += cost[name]
    if queued:
        logger.info("Queued %d base re-render(s) (~%d min) to run while the app "
                    "is closed", queued, round(spent / 60))
    return queued


def attach_base(db, target_id: str, files: list[dict]) -> bool:
    """Record ``files`` as the pre-enhance version of the image ``target_id``.

    The enhanced file keeps its place at the head of the target's
    ``output_files`` — it is still what the row shows — and the base joins behind
    it as the version the info pane offers as ``Original``. ``False`` when there
    is nothing to attach it to: the target was deleted meanwhile, or something
    else repaired it first.
    """
    target = db.get_generation(target_id) if target_id else None
    if not files or target is None or gallery.original_files_of(target):
        return False
    base = [dict(f, role="original") for f in files]
    db.update_generation(
        target_id,
        output_files=json.dumps(gallery.row_output_files(target) + base),
        original_files=json.dumps(base),
    )
    logger.info("Folded a re-derived base render into %s", target_id)
    return True


def fold_base_render(db, render_row: dict) -> str | None:
    """Attach a finished re-render to the image it repairs, and drop its own row.

    Returns the target's prompt_id, or ``None`` when there was nothing to fold
    onto — the row is then left alone rather than half-migrated, so it can be
    found and cleared by hand.
    """
    target_id = gallery.parse_params(render_row.get("params_json")).get(TARGET_KEY)
    if not attach_base(db, target_id, gallery.row_output_files(render_row)):
        return None
    db.delete_generation(render_row["prompt_id"])
    return target_id


def fold_completed_base_renders(db) -> int:
    """Fold every re-render that finished while the app was closed.

    The startup sweep, run before the tree is built so a repaired image is
    already showing both its versions by the time it is drawn. Returns how many
    were folded.
    """
    folded = 0
    for row in db.list_generations():
        if row.get("source") != SOURCE or row.get("status") != "completed":
            continue
        if fold_base_render(db, row) is not None:
            folded += 1
    if folded:
        logger.info("Folded %d base render(s) from the last absence", folded)
    return folded


def cancel_base_renders(db, client) -> int:
    """Clear ComfyUI of the re-renders the last absence queued but didn't reach.

    The app is open now, so the GPU is the user's. Mirrors the experimenter's
    own cancel: every one still queued is dropped and its abandoned row deleted,
    and one caught mid-render is interrupted as well. Returns how many were
    dropped; a finished one is untouched, since it is a repair waiting to fold.
    """
    rows = [
        r for r in db.list_generations()
        if r.get("source") == SOURCE and is_in_progress(r)
    ]
    if not rows:
        return 0
    executing = _safe_running(client)
    dropped, interrupt = 0, False
    for row in rows:
        prompt_id = row["prompt_id"]
        try:
            client.cancel_prompt(prompt_id)
        except Exception as e:
            logger.warning("Could not dequeue base re-render %s: %s", prompt_id, e)
            continue
        db.delete_generation(prompt_id)
        dropped += 1
        interrupt = interrupt or prompt_id in executing
    if interrupt:
        try:
            client.interrupt()
        except Exception as e:
            logger.warning("Could not interrupt the running base re-render: %s", e)
    if dropped:
        logger.info("Dropped %d queued base re-render(s) — the app is open", dropped)
    return dropped


def _safe_running(client) -> set:
    try:
        return client.fetch_running()
    except Exception as e:
        logger.warning("Could not read ComfyUI's running prompts: %s", e)
        return set()
