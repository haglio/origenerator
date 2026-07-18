"""The ambient scheduler: run one background experiment at a time, only when
nobody else wants the GPU.

Each tick it checks, in order: the feature is on; no failure cooldown is
pending; the last experiment's outcome is settled (a failed one backs off
exponentially, so a broken recipe or a downed ComfyUI is probed, not hammered);
nothing of *anyone's* is queued or running in the database (a user's Generate,
an auto-generate loop, or our own last experiment — user work always wins the
queue); and the GPU itself reads idle (Evolver's upscaler or any other load —
see :mod:`.gpu`). Only then does it ask the policy for a proposal and hand it to
the injected ``launch``. It owns no generation machinery and no widgets: the
launch callable (the gallery view's adapter) does the actual submitting, so the
runner stays a pure scheduler, unit-testable with fakes.
"""

import logging

from PyQt6.QtCore import QObject, QTimer

from origenerator.experiments.gpu import gpu_busy as _default_gpu_busy

logger = logging.getLogger(__name__)

_TICK_INTERVAL_MS = 20_000
# After a failure, wait 2**failures ticks (capped) before trying again.
_MAX_BACKOFF_TICKS = 30
# After the user cancels an experiment (its row vanishes), sit out this many
# further ticks beyond the one that noticed (~a minute all told): the cancel said
# "not now", so don't spawn the next one in their face — but it's no failure, so
# no exponential streak builds either.
_CANCEL_BREATHER_TICKS = 2


class ExperimentRunner(QObject):
    def __init__(self, db, policy, launch, *, gpu_busy=_default_gpu_busy,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._policy = policy
        self._launch = launch
        self._gpu_busy = gpu_busy
        self._enabled = False
        self._pending_prompt_id: str | None = None  # our launched, unresolved row
        self._failures = 0        # consecutive failed experiments
        self._cooldown_ticks = 0  # ticks left to sit out after a failure
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_INTERVAL_MS)
        self._timer.timeout.connect(self.tick)

    # --- the on/off switch --------------------------------------------------

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Turn the ambient loop on or off. Turning it on ticks at once — the
        user just asked for experiments, so the first shouldn't wait a tick.
        Turning it off never touches a job already submitted; it only stops new
        launches."""
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self._timer.start()
            self.tick()
        else:
            self._timer.stop()

    # --- one scheduling beat ------------------------------------------------

    def tick(self) -> None:
        if not self._enabled:
            return
        if self._cooldown_ticks > 0:
            self._cooldown_ticks -= 1
            return
        self._resolve_last_outcome()
        if self._cooldown_ticks > 0:
            return  # the resolve just noticed a failure — start sitting it out
        if self._anything_in_flight():
            return
        if self._gpu_busy():
            return
        proposal = self._policy.propose(self._db.list_generations())
        if proposal is None:
            return
        prompt_id = self._launch(proposal)
        if prompt_id is None:
            self._note_failure()
        else:
            self._pending_prompt_id = prompt_id
            logger.info(
                "Experiment launched (%s): %s mutated from %s",
                prompt_id, ", ".join(proposal.mutated_keys) or "seeds only",
                proposal.base_prompt_id,
            )

    def _anything_in_flight(self) -> bool:
        """True while any generation is queued or running — the user's or ours.
        The database is the one source of truth for that (jobs survive app
        restarts there), and one at a time is the whole point: an idle-time
        experimenter must never stack the queue against the user."""
        return any(
            row.get("status") in ("running", "pending")
            for row in self._db.list_generations()
        )

    def _resolve_last_outcome(self) -> None:
        """Settle the row our last launch created: a completed experiment clears
        the failure streak, a failed one lengthens the next cooldown, and one the
        user cancelled (its row deleted) earns a short breather. A row still in
        flight leaves things as they are."""
        if self._pending_prompt_id is None:
            return
        row = self._db.get_generation(self._pending_prompt_id)
        if row is None:
            self._pending_prompt_id = None
            self._cooldown_ticks = max(self._cooldown_ticks, _CANCEL_BREATHER_TICKS)
        elif row.get("status") == "completed":
            self._pending_prompt_id = None
            self._failures = 0
        elif row.get("status") == "error":
            self._pending_prompt_id = None
            self._note_failure()

    def _note_failure(self) -> None:
        self._failures += 1
        self._cooldown_ticks = min(2 ** self._failures, _MAX_BACKOFF_TICKS)
        logger.warning(
            "Experiment failed (%d in a row); backing off %d ticks",
            self._failures, self._cooldown_ticks,
        )
