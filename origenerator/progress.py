"""Turn ComfyUI's per-node sampler progress into one smooth 0-100 for a job.

A multi-stage video workflow denoises in several sampler passes — WAN 2.2 runs a
high-noise ``KSamplerAdvanced`` and then a low-noise one, and the audio pass that
scores the result is a third. ComfyUI reports progress per node, so each pass
counts from 0 to its own step total: a naive bar fills to 100%, snaps back to 0,
and fills again. This module measures a job's total sampler steps up front and
accumulates the passes against it, so the bar advances once from 0 to 100 across
every stage.

Two readings come out of that, and a bar shows both. :meth:`ProgressTracker.
update` gives the whole run's ramp; :meth:`ProgressTracker.current_pass` gives
the pass running right now, counting on its own from zero. The second is what a
single bar used to be mistaken for. An enhancement that upscales an image and
then fixes its faces and its hands is three passes — more, wherever a detector
finds several regions — and one bar showing only the pass in hand empties and
refills once per fix, which reads as a queue of separate jobs rather than one
job's work. Kept apart, the restarting belongs to the lower band, where it is
the truth about the step being taken, and the reading above it only advances.

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


def _detailer_steps(inputs: dict) -> int:
    """One region's worth of an Impact detailer — the floor of what it will run.

    The node samples once per region its detector finds, ``cycle`` times each,
    and how many regions that is cannot be known until the detector has looked:
    one face, or four. So the budget is one region, which is what any pass that
    fixes something at all costs; a second region widens the total from
    :meth:`ProgressTracker.update`, the way an unbudgeted pass does.

    Budgeting that floor rather than nothing is the difference between a bar
    that dips once near the end and a bar that empties and refills once per fix.
    The detailer's sampler runs exactly ``steps`` steps whatever the denoise
    (Impact widens the schedule to ``steps/denoise`` and then slices ``steps``
    back out of its tail), so this needs no denoise of its own.
    """
    return int(inputs.get("steps", 0)) * max(1, int(inputs.get("cycle", 1)))


# ComfyUI sampler node types that emit step progress, and how to size each.
# HunyuanFoleySampler is the audio pass every video workflow appends, and it is
# the larger half of the run by step count — 50 against the 4 to 20 the video
# samplers split between them. Leaving it out is what pinned the bar at 100% for
# minutes at a time while the audio was still being made.
_SAMPLER_STEPS = {
    "KSampler": _ksampler_steps,
    "KSamplerAdvanced": _ksampler_advanced_steps,
    "HunyuanFoleySampler": _ksampler_steps,
    "DetailerForEach": _detailer_steps,
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


def expected_pass_count(payload: dict) -> int:
    """How many sampler passes a payload is budgeted for.

    What decides whether a bar has a second band to show at all: a lone-sampler
    image job is one pass end to end, and a band counting the same steps as the
    reading above it says nothing twice. A detailer counts once here however many
    regions it turns out to sample — the rest are found, not budgeted.
    """
    return sum(1 for node in payload.values()
               if node.get("class_type") in _SAMPLER_STEPS)


class ProgressTracker:
    """Accumulate a job's per-node sampler progress into one 0-to-total ramp.

    Fed each ComfyUI ``progress`` event as ``(value, max)`` for whichever
    sampler is running, it returns ``(cumulative, total)`` measured against the
    job's whole-run step count. Each new pass restarts its own ``value`` from the
    low end; the tracker banks the finished pass's steps so the next continues
    where it left off instead of snapping back to zero. That restarting count is
    worth showing on its own, and :meth:`current_pass` is where it is kept.
    """

    @classmethod
    def for_payload(cls, payload: dict) -> "ProgressTracker":
        """Build a tracker sized to a workflow payload's total sampler steps."""
        return cls(expected_progress_steps(payload), expected_pass_count(payload))

    def __init__(self, total_steps: int, passes: int = 1):
        self._total = total_steps
        self._passes = max(1, passes)  # sampler passes the payload budgets for
        self._banked = 0          # steps completed in passes that have finished
        self._stage_max = 0       # this pass's step count (its reported max)
        self._last_value = None   # last value seen in this pass, to spot a restart
        self._pass_index = 0      # passes begun so far, the running one included

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
            "passes": self._passes,
            "pass_index": self._pass_index,
        }

    def restore(self, snapshot: dict) -> None:
        """Reload a :meth:`snapshot` so the ramp resumes where it left off."""
        self._total = int(snapshot.get("total", self._total))
        self._banked = int(snapshot.get("banked", 0))
        self._stage_max = int(snapshot.get("stage_max", 0))
        last_value = snapshot.get("last_value")
        self._last_value = None if last_value is None else int(last_value)
        self._passes = max(1, int(snapshot.get("passes", self._passes)))
        # A snapshot taken before the band existed says nothing about which pass
        # it was in, but the rest of it does: banked steps mean a pass finished
        # and another began. Reading that back beats leaving a reconnected job's
        # bar whole until its next tick and then splitting it.
        began = 2 if self._banked else (1 if self._last_value is not None else 0)
        self._pass_index = int(snapshot.get("pass_index", began))

    def current(self) -> tuple[int, int]:
        """The last ``(cumulative, total)`` this tracker would report right now.

        Used to seed a reconnected job's displayed progress from a restored snapshot,
        so the bar shows its last position immediately instead of a blank ramp.
        ``(0, 0)`` when the total is unknown (no recognized sampler).
        """
        if self._total <= 0:
            return 0, 0
        return min(self._banked + (self._last_value or 0), self._total), self._total

    def current_pass(self) -> tuple[int, int] | None:
        """The pass running right now, as its own ``(done, total)`` — or ``None``.

        ``None`` wherever a second band would say nothing the reading above it
        doesn't: a run budgeted for one pass and still inside it, a run that has
        not reported a step, and a run with no recognized sampler (whose bar is
        already showing raw per-node numbers, which *are* this reading). A run
        budgeted for several passes has its band from its first step, so the band
        doesn't appear from nowhere partway through; an under-budgeted one grows
        one the moment a second pass proves there was more than the one.
        """
        if self._total <= 0 or self._pass_index == 0:
            return None
        if self._passes <= 1 and self._pass_index <= 1:
            return None
        return min(self._last_value or 0, self._stage_max), self._stage_max

    def update(self, value: int, max_val: int) -> tuple[int, int]:
        if self._total <= 0:
            return value, max_val  # unknown total: fall back to raw per-node numbers
        # A value that drops below the current pass's last marks a new pass: bank
        # the finished pass's steps and start accumulating from the fresh count.
        if self._last_value is None:
            self._pass_index = 1
        elif value < self._last_value:
            self._banked += self._stage_max
            self._stage_max = 0
            self._pass_index += 1
        self._last_value = value
        self._stage_max = max(self._stage_max, max_val)
        # A pass wider than what was budgeted for it — a detailer that found more
        # regions than the one it was budgeted, or a tiled upscale sized off the
        # image — can't be counted up front. Widen the total to admit it rather
        # than clamp it away: a bar that rescales says there is more to do, where
        # a bar pinned at 100% says the opposite of the truth and says it for as
        # long as the pass runs.
        self._total = max(self._total, self._banked + self._stage_max)
        cumulative = min(self._banked + value, self._total)
        return cumulative, self._total
