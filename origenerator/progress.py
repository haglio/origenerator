"""Turn ComfyUI's per-node sampler progress into one smooth 0-100 for a job.

A multi-stage video workflow denoises in several sampler passes — WAN 2.2 runs a
high-noise ``KSamplerAdvanced`` and then a low-noise one, and the audio pass that
scores the result is a third. ComfyUI reports progress per node, so each pass
counts from 0 to its own step total: a naive bar fills to 100%, snaps back to 0,
and fills again. This module measures a job's whole cost up front and accumulates
the passes against it, so the bar advances once from 0 to 100 across every stage.

**A step is not the unit a job's cost is measured in.** Counting the steps and
calling each one an equal share of the work is what made a WAN 2.2 I2V bar read
backwards: its 20 video steps against the audio pass's 50 put three quarters of
the bar on the audio, and that three quarters went by in fifteen seconds after
the first quarter had taken eleven minutes. The two are not comparable units — a
WAN step denoises every frame of the clip through a 14B model, and a foley step
denoises a few seconds of audio through a small one — so the bar is budgeted in
*seconds of sampling* instead, and each pass is sized by what a step of it
actually costs (:data:`_VIDEO_STEP_SECONDS_PER_FRAME` and the constants beside
it). Steps are still what the passes report, and still what the band along the
bar's foot counts; they are simply not what the bar is measured in.

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
these same numbers, and a run whose budget is all spent leaves it nothing to pace
off. So every sampler that reports progress is budgeted here, and a pass that
turns up unbudgeted anyway widens the total rather than being clamped away.
"""

# --- what a step of each kind of sampler costs -------------------------------
#
# Seconds, measured off this app's own completed runs, and only ever read against
# each other: what a bar needs is the ratio between the passes of one job, and a
# faster or slower card moves every one of these together. Two fits from those
# durations:
#
#   WAN 2.2 I2V at 8 steps, the same settings but for the clip's length: 81
#   frames took ~355s and 161 frames ~730s. The difference is all sampling, and
#   it divides out at about half a second per frame per step — which is also what
#   a 161-frame run showed directly, at 35s a step.
#
#   The audio pass under it ran its 50 steps in about fifteen seconds on ten
#   seconds of audio. Its cost follows the clip's length the same way the video's
#   does, being a diffusion over an audio latent of that length.
#
# A still has no frame count to scale by, so it is sized flat; a detail fix's crop
# is enlarged to at most 1024px against a full render several times that, so a
# step of one is worth a fraction of a step of the other.
_VIDEO_STEP_SECONDS_PER_FRAME = 0.5
_AUDIO_STEP_SECONDS_PER_SECOND = 0.03
_IMAGE_STEP_SECONDS = 0.5
_DETAIL_STEP_SECONDS = 0.15

# The inputs every latent builder that measures a clip carries together —
# WanImageToVideo, WanFirstLastFrameToVideo, WanTrackToVideo,
# EmptyHunyuanLatentVideo. Matched on that shape rather than on a list of class
# names, so a video workflow written next year is sized as one without anyone
# remembering to add it here; a name list that goes stale sizes a clip's samplers
# as stills, which is the exact mistake this module exists to undo.
# ``ImageFromBatch`` carries a ``length`` too and is not one of these, which is
# why the match needs all four.
_LATENT_SIZE_INPUTS = ("length", "width", "height", "batch_size")


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


# ComfyUI sampler node types that emit step progress, and how many steps each
# reports. What one of those steps costs is a separate question, answered by
# :func:`_step_seconds` — the two were one number until the workflow whose
# cheapest pass reports the most steps turned up.
_SAMPLER_STEPS = {
    "KSampler": _ksampler_steps,
    "KSamplerAdvanced": _ksampler_advanced_steps,
    "HunyuanFoleySampler": _ksampler_steps,
    "DetailerForEach": _detailer_steps,
}


def _literal(value, fallback: float) -> float:
    """A node input's number, or ``fallback`` where it is a link to another node.

    A size derived in-graph (a video's width and height are, here) arrives as
    ``[node_id, slot]`` and cannot be read without running the graph.
    """
    return float(value) if isinstance(value, (int, float)) else fallback


def _video_latent_frames(payload: dict) -> int:
    """Frames in the video latent this payload samples — 0 when it samples a still.

    Read off the latent builder (see :data:`_LATENT_SIZE_INPUTS`), because that
    is the one place a clip's length is a plain number: the samplers downstream
    of it only ever see a latent. 0 for a payload with no such node, and for one
    whose length is itself derived in-graph — both of which fall back to sizing
    the samplers as stills.
    """
    frames = 0
    for node in payload.values():
        inputs = node.get("inputs", {})
        if all(key in inputs for key in _LATENT_SIZE_INPUTS):
            frames = max(frames, int(_literal(inputs["length"], 0)))
    return frames


def _step_seconds(class_type: str, inputs: dict, frames: int) -> float:
    """What one reported step of this sampler is expected to cost, in seconds.

    The one place the video/audio/still distinction is drawn. Its blind spot is a
    still sampled at two sizes in one job — a base render and the enhance tail
    that re-samples it at twice the width are both ``KSampler`` and are sized the
    same here. That is a couple of seconds misplaced on a job that runs for tens
    of them, against the minutes the video case misplaces, so it stays a known
    flat spot rather than a walk back through the graph for a scale factor.
    """
    if class_type == "HunyuanFoleySampler":
        return _AUDIO_STEP_SECONDS_PER_SECOND * max(1.0, _literal(inputs.get("duration"), 1.0))
    if class_type == "DetailerForEach":
        return _DETAIL_STEP_SECONDS
    if frames:
        return _VIDEO_STEP_SECONDS_PER_FRAME * frames
    return _IMAGE_STEP_SECONDS


def sampler_costs(payload: dict) -> dict[str, tuple[int, float]]:
    """Every progress-reporting sampler in ``payload``, by node id.

    ``{node_id: (steps it reports, seconds one of those steps costs)}`` — the
    whole of what a bar needs to size itself, keyed by node because that is what
    a ComfyUI progress event names. Empty for a payload with no recognized
    sampler, which callers treat as "unknown" and fall back to raw per-node
    numbers.
    """
    frames = _video_latent_frames(payload)
    costs = {}
    for node_id, node in payload.items():
        sizer = _SAMPLER_STEPS.get(node.get("class_type"))
        if sizer is None:
            continue
        inputs = node.get("inputs", {})
        costs[str(node_id)] = (
            sizer(inputs), _step_seconds(node["class_type"], inputs, frames),
        )
    return costs


def expected_sampling_seconds(payload: dict) -> int:
    """Seconds of sampling a workflow payload is budgeted for — the bar's total.

    An estimate, and one only ever read against itself: what a bar needs is each
    pass's share of the job, not a prediction of the clock. 0 when no sampler is
    recognized.
    """
    return round(sum(steps * cost for steps, cost in sampler_costs(payload).values()))


def expected_pass_count(payload: dict) -> int:
    """How many sampler passes a payload is budgeted for.

    What decides whether a bar has a second band to show at all: a lone-sampler
    image job is one pass end to end, and a band counting the same steps as the
    reading above it says nothing twice. A detailer counts once here however many
    regions it turns out to sample — the rest are found, not budgeted.
    """
    return len(sampler_costs(payload))


class ProgressTracker:
    """Accumulate a job's per-node sampler progress into one 0-to-total ramp.

    Fed each ComfyUI ``progress`` event as ``(value, max)`` for whichever sampler
    is running — with that sampler's node id, where the caller has one — it
    returns ``(done, total)`` in the budgeted seconds of
    :func:`expected_sampling_seconds`. Each new pass restarts its own ``value``
    from the low end; the tracker banks the finished pass's cost so the next
    continues where it left off instead of snapping back to zero. That restarting
    count is worth showing on its own, and :meth:`current_pass` is where it is
    kept — in steps, which is the honest unit for one pass of one sampler.

    Built without costs — the plain constructor, which is how a test states a
    ramp it means to check — every step is worth one unit and the totals are step
    counts, as they were before passes were weighed against each other.
    """

    @classmethod
    def for_payload(cls, payload: dict) -> "ProgressTracker":
        """Build a tracker sized to a workflow payload's sampler passes."""
        return cls(
            expected_sampling_seconds(payload),
            expected_pass_count(payload),
            {node_id: cost for node_id, (_, cost) in sampler_costs(payload).items()},
        )

    def __init__(self, total_seconds: float, passes: int = 1,
                 step_seconds: dict[str, float] | None = None):
        self._total = float(total_seconds)
        self._passes = max(1, passes)   # sampler passes the payload budgets for
        self._step_seconds = dict(step_seconds or {})  # node id -> a step's cost
        # What a pass nobody budgeted is charged per step: the cheapest thing this
        # job does. Such a pass is a node this app has never sized, and the two
        # ways of being wrong about one are not equal — charging it too little
        # leaves the bar creeping through its tail, where charging it too much (a
        # video step's worth, say, for a frame interpolation reporting one tick a
        # frame) buries every real pass under it. Be wrong where less is at stake.
        self._unbudgeted = min(self._step_seconds.values(), default=1.0)
        self._banked = 0.0        # seconds spent in passes that have finished
        self._stage_max = 0       # this pass's step count (its reported max)
        self._stage_seconds = self._unbudgeted  # what a step of this pass costs
        self._last_value = None   # last value seen in this pass, to spot a restart
        self._node = None         # the node this pass runs on, where ComfyUI said
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
            "stage_seconds": self._stage_seconds,
            "last_value": self._last_value,
            "node": self._node,
            "passes": self._passes,
            "pass_index": self._pass_index,
        }

    def restore(self, snapshot: dict) -> None:
        """Reload a :meth:`snapshot` so the ramp resumes where it left off.

        A snapshot with no ``stage_seconds`` was written while the bar counted
        steps, and its banked figure is a step count that means nothing against a
        total of seconds. Rather than resume such a run at a position that stays
        wrong for the rest of it, it comes back with no position at all and takes
        one from ComfyUI's next push — which is what a job with nothing persisted
        has always done.
        """
        if "stage_seconds" not in snapshot:
            return
        self._total = float(snapshot.get("total", self._total))
        self._banked = float(snapshot.get("banked", 0.0))
        self._stage_max = int(snapshot.get("stage_max", 0))
        self._stage_seconds = float(snapshot.get("stage_seconds", self._unbudgeted))
        last_value = snapshot.get("last_value")
        self._last_value = None if last_value is None else int(last_value)
        self._node = snapshot.get("node")
        self._passes = max(1, int(snapshot.get("passes", self._passes)))
        # A snapshot taken before the band existed says nothing about which pass
        # it was in, but the rest of it does: banked seconds mean a pass finished
        # and another began. Reading that back beats leaving a reconnected job's
        # bar whole until its next tick and then splitting it.
        began = 2 if self._banked else (1 if self._last_value is not None else 0)
        self._pass_index = int(snapshot.get("pass_index", began))

    def current(self) -> tuple[int, int]:
        """The last ``(done, total)`` this tracker would report right now.

        Used to seed a reconnected job's displayed progress from a restored snapshot,
        so the bar shows its last position immediately instead of a blank ramp.
        ``(0, 0)`` when the total is unknown (no recognized sampler).
        """
        if self._total <= 0:
            return 0, 0
        return self._reading(self._last_value or 0)

    def current_pass(self) -> tuple[int, int] | None:
        """The pass running right now, as its own ``(done, total)`` steps — or ``None``.

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

    def update(self, value: int, max_val: int,
               node: str | None = None) -> tuple[int, int]:
        if self._total <= 0:
            return value, max_val  # unknown total: fall back to raw per-node numbers
        if self._last_value is None:
            self._pass_index = 1
            self._begin_pass(node)
        elif self._is_new_pass(value, node):
            # Bank the finished pass at its own rate before taking up the next's.
            self._banked += self._stage_max * self._stage_seconds
            self._stage_max = 0
            self._pass_index += 1
            self._begin_pass(node)
        self._last_value = value
        self._stage_max = max(self._stage_max, max_val)
        # A pass costlier than what was budgeted for it — a detailer that found
        # more regions than the one it was budgeted, or a tiled upscale sized off
        # the image — can't be counted up front. Widen the total to admit it
        # rather than clamp it away: a bar that rescales says there is more to do,
        # where a bar pinned at 100% says the opposite of the truth and says it
        # for as long as the pass runs.
        self._total = max(self._total,
                          self._banked + self._stage_max * self._stage_seconds)
        return self._reading(value)

    def _is_new_pass(self, value: int, node: str | None) -> bool:
        """Whether this event belongs to a pass other than the one in hand.

        The node id settles it outright where ComfyUI gave one, which is what lets
        two passes of unequal cost be told apart even when they report the same
        step counts. A value dropping below the last is the older reading, and
        still the only one that catches a *second run of the same node*: an Impact
        detailer sampling its second region names the node it named for the first.
        """
        if node is not None and self._node is not None and node != self._node:
            return True
        return value < self._last_value

    def _begin_pass(self, node: str | None) -> None:
        self._node = node
        self._stage_seconds = self._step_seconds.get(node, self._unbudgeted)

    def _reading(self, value: int) -> tuple[int, int]:
        """This position and the whole, rounded to the second the bar shows.

        The total floors at 1 rather than at 0: a job budgeted for less than a
        second still has a position within itself, and a reported total of zero
        is how a caller is told there is no reading at all — which would put a
        sweeping indeterminate bar on a job that is measuring fine.
        """
        done = min(self._banked + value * self._stage_seconds, self._total)
        return round(done), max(1, round(self._total))
