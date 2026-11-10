from __future__ import annotations

import itertools
import json
import logging
import subprocess
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.threading_utils import start_daemon_thread

from origenerator import evolver_agreement

logger = logging.getLogger(__name__)

DELETE_FROM_TRASH = "delete_from_trash_command"
VIDEOS_PER_ASK = 50
_GIVEN_SECONDS = 5 * 60
_UNANSWERED = (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError)


def delete_for_good(videos, *, checkout: Path | None = None, runner=subprocess.run) -> int:
    videos = list(videos)
    checkout = evolver_agreement.evolver_checkout() if checkout is None else checkout
    command = evolver_agreement.published_command(checkout, DELETE_FROM_TRASH)
    if command is None:
        logger.warning("Evolver names no way to delete what waits in Trash, so %d video(s) "
                       "stay in Kino's and Genau's Trash folders", len(videos))
        return 0
    interpreter, *arguments = command
    deleted = 0
    for batch in itertools.batched(videos, VIDEOS_PER_ASK):
        try:
            answered = runner([str(checkout / interpreter), *arguments, *map(str, batch)],
                              cwd=str(checkout), capture_output=True, text=True,
                              timeout=_GIVEN_SECONDS, **hidden_subprocess_kwargs())
            deleted += int(json.loads(answered.stdout.strip().splitlines()[-1])["deleted"])
        except _UNANSWERED as e:
            logger.warning("Evolver could not be asked to delete %d video(s) for good: %s",
                           len(batch), e)
    logger.info("Evolver deleted %d of %d video(s) for good", deleted, len(videos))
    return deleted


def in_the_background(videos, *, start=start_daemon_thread) -> None:
    start(target=delete_for_good, args=(list(videos),), name="evolver-delete-from-trash")
