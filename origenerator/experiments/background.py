from __future__ import annotations

import logging

from origenerator.generation_state import GenerationSource
from origenerator.inflight import drop_in_flight

logger = logging.getLogger(__name__)

EXPERIMENTS_QUEUED_PER_ABSENCE = 8
_MISSES_MEANING_COMFYUI_REFUSES = 3


def queue_experiments(rows, policy, launch) -> int:
    launched = misses = 0
    while launched < EXPERIMENTS_QUEUED_PER_ABSENCE and misses < _MISSES_MEANING_COMFYUI_REFUSES:
        proposal = policy.propose(rows)
        if proposal is None:
            break
        if launch(proposal) is None:
            misses += 1
        else:
            launched, misses = launched + 1, 0
            logger.info(
                "Experiment %d: bred from %s, varying %s", launched,
                proposal.base_prompt_id,
                ", ".join(proposal.mutated_keys) or "nothing",
            )
    logger.info("Queued %d experiment(s) to run while the app is closed", launched)
    return launched


def cancel_experiments(db, client) -> int:
    return drop_in_flight(db, client, GenerationSource.EXPERIMENT, "experiment")
