"""Background experiments: queued as the app closes, cleared when it opens.

Experiments belong to the stretch when Origenerator isn't running. ComfyUI is a
server that outlives the app, so closing hands it a batch of policy-proposed
variations and it works through them alone; the next launch finds the finished
ones on the Experiments shelf (the startup reconcile finalizes their rows) and
drops whatever hadn't run yet, so an open app never has an experiment competing
with the user for the GPU.
"""
from __future__ import annotations

import logging

from origenerator.generation_state import GenerationSource
from origenerator.inflight import drop_in_flight

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
    ``None`` when the launch didn't take). Each one that takes is logged with
    the row it was bred from and the params it varies. Returns how many were
    queued.
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
            # The provenance, once per launch. The app is shut while this batch
            # runs, so a log line is the only place what it explored is written
            # down -- a count alone cannot say which experiment varied what.
            logger.info(
                "Experiment %d: bred from %s, varying %s", launched,
                proposal.base_prompt_id,
                ", ".join(proposal.mutated_keys) or "nothing",
            )
    logger.info("Queued %d experiment(s) to run while the app is closed", launched)
    return launched


def cancel_experiments(db, client) -> int:
    """Clear ComfyUI of the experiments the last absence queued.

    The app is open now, so the GPU is the user's: every experiment still queued
    is dropped and its abandoned row deleted, and one caught mid-render is
    stopped as well (:func:`origenerator.inflight.drop_in_flight`). Returns how
    many were dropped. Finished ones are untouched: they're the results waiting
    on the shelf.
    """
    return drop_in_flight(db, client, GenerationSource.EXPERIMENT, "experiment")
