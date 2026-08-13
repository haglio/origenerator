"""Background experiments: queued as the app closes, cleared when it opens.

Experiments belong to the stretch when Origenerator isn't running. ComfyUI is a
server that outlives the app, so closing hands it a batch of policy-proposed
variations and it works through them alone; the next launch finds the finished
ones on the Experiments shelf (the startup reconcile finalizes their rows) and
drops whatever hadn't run yet, so an open app never has an experiment competing
with the user for the GPU.
"""

import logging

from origenerator.gallery.output import is_in_progress

logger = logging.getLogger(__name__)

# How many experiments one absence gets. ComfyUI runs them back to back with
# nobody watching, so this is the whole night's output — and every one comes back
# as a card to review, so a bigger batch buys more results at the price of a
# longer shelf. Enough to fill an evening, few enough to review in a sitting.
BATCH_SIZE = 8
# Consecutive launches that didn't take before the batch is abandoned. A refused
# launch is usually a proposal landing in a folder an earlier one claimed — worth
# re-proposing past. A run of them means ComfyUI is refusing everything (it's
# down, or the submit is timing out), and this runs while the user waits for the
# app to close, so a few tries is the whole budget.
_MAX_CONSECUTIVE_MISSES = 3


def queue_experiments(rows, policy, launch) -> int:
    """Hand ComfyUI a batch of experiments to run while the app is closed.

    Asks ``policy`` for one proposal at a time and submits it through ``launch``
    (the gallery's adapter, which returns the launched row's prompt_id, or
    ``None`` when the launch didn't take). Returns how many were queued.
    """
    launched = misses = 0
    while launched < BATCH_SIZE and misses < _MAX_CONSECUTIVE_MISSES:
        proposal = policy.propose(rows)
        if proposal is None:
            break  # the gallery holds nothing to build on
        if launch(proposal) is None:
            misses += 1
        else:
            launched, misses = launched + 1, 0
    logger.info("Queued %d experiment(s) to run while the app is closed", launched)
    return launched


def cancel_experiments(db, client) -> int:
    """Clear ComfyUI of the experiments the last absence queued.

    The app is open now, so the GPU is the user's: every experiment still queued
    is dropped and its abandoned row deleted, and one caught mid-render is
    interrupted as well — dequeuing alone would leave it holding the card.
    Returns how many were dropped. Finished ones are untouched: they're the
    results waiting on the shelf.
    """
    rows = [
        r for r in db.list_generations()
        if r.get("source") == "experiment" and is_in_progress(r)
    ]
    if not rows:
        return 0
    executing = _safe_running(client)
    dropped = 0
    interrupt = False
    for row in rows:
        prompt_id = row["prompt_id"]
        try:
            client.cancel_prompt(prompt_id)
        except Exception as e:
            # Leave the row alone: the prompt may still run, and the app adopts
            # an in-flight row as a live job it can preempt when the user works.
            logger.warning("Could not dequeue experiment %s: %s", prompt_id, e)
            continue
        db.delete_generation(prompt_id)
        dropped += 1
        interrupt = interrupt or prompt_id in executing
    if interrupt:
        # Only ever for a prompt of ours: ComfyUI serves other clients, and
        # /interrupt stops whatever it happens to be executing.
        try:
            client.interrupt()
        except Exception as e:
            logger.warning("Could not interrupt the running experiment: %s", e)
    if dropped:
        logger.info("Dropped %d queued experiment(s) — the app is open", dropped)
    return dropped


def _safe_running(client) -> set:
    """The prompt ids ComfyUI is executing, or an empty set if it can't say."""
    try:
        return client.fetch_running()
    except Exception as e:
        logger.warning("Could not read ComfyUI's running prompts: %s", e)
        return set()
