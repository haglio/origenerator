"""Turn ComfyUI's per-node sampler progress into one smooth 0-100 for a job.

A multi-stage video workflow denoises in several sampler passes — WAN 2.2 runs a
high-noise ``KSamplerAdvanced`` and then a low-noise one, and the audio pass that
scores the result is a third. ComfyUI reports progress per node, so each pass
counts from 0 to its own step total: a naive bar fills to 100%, snaps back to 0,
and fills again. This module measures a job's total sampler steps up front and
accumulates the passes against it, so the bar advances once from 0 to 100 across
every stage.

The measuring is what has to be right. A pass left out of the up-front total
doesn't make the bar finish early — it makes the bar finish and then sit at 100%
for the whole length of that pass, which reads as a job that has stalled. It
takes the countdown beside it down too: ``timing.remaining_seconds`` paces off
these same numbers, and a run whose steps are all spent leaves it nothing to pace
off. So every sampler that reports progress is budgeted here, and a pass that
turns up unbudgeted anyway widens the total rather than being clamped away.
"""


def _ksampler_steps(inputs: dict) -> int:
    return int(inputs.get("steps", 0))


def _ksampler_advanced_steps(inputs: dict) -> int:
    """Steps a KSamplerAdvanced actually runs: its slice of the schedule.

    ``start_at_step``/``end_at_step`` carve a window out of the full ``steps``
    schedule (``end_at_step`` is often a sentinel like 10000 meaning "to the
    end"), and ComfyUI's progress ``max`` for the node is that window's length.
    """
    steps = int(inputs.get("steps", 0))
    start = int(inputs.get("start_at_step", 0))
    end = int(inputs.get("end_at_step", steps))
    return max(0, min(end, steps) - start)


# ComfyUI sampler node types that emit step progress, and how to size each.
# HunyuanFoleySampler is the audio pass every video workflow appends, and it is
# the larger half of the run by step count — 50 against the 4 to 20 the video
# samplers split between them. Leaving it out is what pinned the bar at 100% for
# minutes at a time while the audio was still being made.
_SAMPLER_STEPS = {
    "KSampler": _ksampler_steps,
    "KSamplerAdvanced": _ksampler_advanced_steps,
    "HunyuanFoleySampler": _ksampler_steps,
}


def expected_progress_steps(payload: dict) -> int:
    """Total sampler steps ComfyUI will report for a workflow payload.

    Sums the denoising steps of every sampler node — the units ComfyUI's
    ``progress`` events count in — so a run's several passes read as one total.
    Returns 0 when no sampler is recognized, which callers treat as "unknown"
    and fall back to raw per-node numbers.
    """
    total = 0
    for node in payload.values():
        sizer = _SAMPLER_STEPS.get(node.get("class_type"))
        if sizer is not None:
            total += sizer(node.get("inputs", {}))
    return total


class ProgressTracker:
    """Accumulate a job's per-node sampler progress into one 0-to-total ramp.

    Fed each ComfyUI ``progress`` event as ``(value, max)`` for whichever
    sampler is running, it returns ``(cumulative, total)`` measured against the
    job's whole-run step count. Each new pass restarts its own ``value`` from the
    low end; the tracker banks the finished pass's steps so the next continues
    where it left off instead of snapping back to zero.
    """

    @classmethod
    def for_payload(cls, payload: dict) -> "ProgressTracker":
        """Build a tracker sized to a workflow payload's total sampler steps."""
        return cls(expected_progress_steps(payload))

    def __init__(self, total_steps: int):
        self._total = total_steps
        self._banked = 0          # steps completed in passes that have finished
        self._stage_max = 0       # this pass's step count (its reported max)
        self._last_value = None   # last value seen in this pass, to spot a restart

    def snapshot(self) -> dict:
        """The tracker's resumable state, small enough to persist each progress tick.

        Paired with :meth:`restore`, this lets a job's ramp survive an app restart:
        the banked passes and the current pass's position come back intact, so a
        reconnected multi-stage job continues its 0-to-total ramp from where it was
        rather than restarting the count from the pass it reconnects into.
        """
        return {
            "total": self._total,
            "banked": self._banked,
            "stage_max": self._stage_max,
            "last_value": self._last_value,
        }

    def restore(self, snapshot: dict) -> None:
        """Reload a :meth:`snapshot` so the ramp resumes where it left off."""
        self._total = int(snapshot.get("total", self._total))
        self._banked = int(snapshot.get("banked", 0))
        self._stage_max = int(snapshot.get("stage_max", 0))
        last_value = snapshot.get("last_value")
        self._last_value = None if last_value is None else int(last_value)

    def current(self) -> tuple[int, int]:
        """The last ``(cumulative, total)`` this tracker would report right now.

        Used to seed a reconnected job's displayed progress from a restored snapshot,
        so the bar shows its last position immediately instead of a blank ramp.
        ``(0, 0)`` when the total is unknown (no recognized sampler).
        """
        if self._total <= 0:
            return 0, 0
        return min(self._banked + (self._last_value or 0), self._total), self._total

    def update(self, value: int, max_val: int) -> tuple[int, int]:
        if self._total <= 0:
            return value, max_val  # unknown total: fall back to raw per-node numbers
        # A value that drops below the current pass's last marks a new pass: bank
        # the finished pass's steps and start accumulating from the fresh count.
        if self._last_value is not None and value < self._last_value:
            self._banked += self._stage_max
            self._stage_max = 0
        self._last_value = value
        self._stage_max = max(self._stage_max, max_val)
        # A pass wider than what was budgeted for it — an Impact detailer, which
        # samples once per region it detects, or a tiled upscale sized off the
        # image — can't be counted up front. Widen the total to admit it rather
        # than clamp it away: a bar that rescales says there is more to do, where
        # a bar pinned at 100% says the opposite of the truth and says it for as
        # long as the pass runs.
        self._total = max(self._total, self._banked + self._stage_max)
        cumulative = min(self._banked + value, self._total)
        return cumulative, self._total
