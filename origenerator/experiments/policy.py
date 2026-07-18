"""Derive the next background experiment from the gallery's own history.

The policy hill-climbs the user's actual work: it picks a past generation as a
base (favoring starred items and up-voted experiments), mutates one or two of
its workflow's declared dimensions — a numeric nudged within its form range, a
combo swapped for another installed option, or the prompt pair crossed over from
a sibling generation — and re-rolls every seed. Review verdicts feed back in:
values that appeared in up-voted experiments are sampled more, values from
down-voted ones less, so the search concentrates where the user's taste points
while an exploration floor keeps it from tunneling.

Deliberately deterministic machinery (no LLM): everything is derived from
gallery rows and ``param_definitions``, so it works offline and is unit-testable
with an injected RNG.
"""

from dataclasses import dataclass

from origenerator.gallery import parse_params, produced_output
from origenerator.generation_config import filled_params, randomize_seeds

# A base is worth more when the user has explicitly liked it: a star is the
# strongest signal, an up-voted experiment close behind, newness a mild boost.
_STAR_BONUS = 2.0
_UP_BONUS = 1.0
_RECENT_BONUS = 0.5
_RECENT_WINDOW = 25  # rows arrive newest-first; this many count as "recent"

# How often a proposal mutates two dimensions instead of one.
_SECOND_DIM_CHANCE = 0.3
# Exploration floor: this often, a mutated value is drawn uniformly instead of
# by verdict weight, so a promising-but-unseen value still gets its chance.
_EXPLORE_CHANCE = 0.25
# A value the reviews have clearly damned is dropped from the pool outright —
# explore draws included — once it has this many votes at or under this weight.
# "Down" has to actually mean the value stops coming back.
_VETO_MIN_VOTES = 3
_VETO_MAX_WEIGHT = 0.25
# Numeric jitter: candidate values are drawn around the base value with a sigma
# of range/_JITTER_SPREAD, so mutations search locally rather than teleport.
_JITTER_SPREAD = 8.0
_NUMERIC_CANDIDATES = 5
_NUMERIC_BUCKETS = 8  # verdict-weight resolution across a numeric's range


@dataclass
class Proposal:
    """One experiment to run: a workflow, its full params (seeds already
    re-rolled), and the provenance the runner records/logs."""

    workflow: object
    params: dict
    base_prompt_id: str
    mutated_keys: tuple


class ExperimentPolicy:
    def __init__(self, registry, rng):
        self._registry = registry
        self._rng = rng

    # --- the one entry point ------------------------------------------------

    def propose(self, rows: list[dict]) -> Proposal | None:
        """The next experiment to run, derived from ``rows`` (newest first), or
        ``None`` when the gallery holds nothing to build on."""
        bases = self._base_candidates(rows)
        if not bases:
            return None
        weights = [self._base_weight(row, i) for i, (row, _) in enumerate(bases)]
        row, workflow = self._weighted_choice(bases, weights)
        params = filled_params(row, workflow)
        mutated = self._mutate(params, workflow, rows)
        params = randomize_seeds(params, workflow.seed_keys())
        return Proposal(workflow, params, row["prompt_id"], tuple(mutated))

    # --- base selection -----------------------------------------------------

    def _base_candidates(self, rows):
        """Rows an experiment may build on, paired with their workflow: finished
        results of a registered workflow. A down-voted experiment is out — the
        user has said not to go there — while an unreviewed one waits for its
        verdict rather than compounding unvetted mutations."""
        out = []
        for row in rows:
            workflow = self._registry.get(row.get("workflow_name") or "")
            if workflow is None:
                continue
            if row.get("status") != "completed" or not produced_output(row):
                continue
            if row.get("source") == "experiment" and row.get("experiment_verdict") != "up":
                continue
            if "input_image" in workflow.default_params() and \
                    not parse_params(row.get("params_json")).get("input_image"):
                continue  # an i2v with no start frame recorded can't be re-run
            out.append((row, workflow))
        return out

    @staticmethod
    def _base_weight(row, index):
        weight = 1.0
        if row.get("starred"):
            weight += _STAR_BONUS
        if row.get("experiment_verdict") == "up":
            weight += _UP_BONUS
        if index < _RECENT_WINDOW:
            weight += _RECENT_BONUS
        return weight

    # --- mutation -----------------------------------------------------------

    def _mutate(self, params, workflow, rows):
        """Mutate ``params`` in place along one or two of the workflow's
        dimensions, returning the mutated keys."""
        dims = self._mutable_dims(workflow)
        if not dims:
            return []
        count = 2 if len(dims) > 1 and self._rng.random() < _SECOND_DIM_CHANCE else 1
        # Walk the dims in random order until enough mutations actually applied —
        # a dim can be a no-op (a prompt with no donor to cross from, say), and a
        # proposal that changes nothing but its seed teaches nothing.
        self._rng.shuffle(dims)
        mutated = []
        for dim in dims:
            if len(mutated) == count:
                break
            if self._apply_mutation(params, dim, workflow, rows):
                mutated.append(dim.key)
        return mutated

    @staticmethod
    def _mutable_dims(workflow):
        """The dimensions an experiment may vary: the prompt pair, any bounded
        numeric, and any multi-option combo — per the workflow's own form."""
        dims = []
        for pd in workflow.param_definitions():
            if pd.key == "positive_prompt":
                dims.append(pd)
            elif pd.type in ("int", "float") and pd.min_val is not None \
                    and pd.max_val is not None and pd.max_val > pd.min_val:
                dims.append(pd)
            elif pd.type == "combo" and pd.options and len(pd.options) > 1:
                dims.append(pd)
        return dims

    def _apply_mutation(self, params, pd, workflow, rows) -> bool:
        """Write one mutated value for ``pd`` into ``params``. Returns whether a
        change was made (a dimension with nothing to change to is a no-op)."""
        if pd.key == "positive_prompt":
            return self._crossover_prompts(params, workflow, rows)
        if pd.type == "combo":
            return self._swap_combo(params, pd, workflow, rows)
        return self._jitter_numeric(params, pd, workflow, rows)

    def _crossover_prompts(self, params, workflow, rows):
        """Replace the prompt pair with another finished generation's — the same
        recipe pointed at a sibling subject. Donors are weighted by their own
        appeal (stars/up-votes) and the verdict record of their prompt."""
        current = params.get("positive_prompt", "")
        donors = []
        weights = []
        for row in rows:
            if (row.get("workflow_name") or "") != workflow.name:
                continue
            if row.get("status") != "completed" or not produced_output(row):
                continue
            if row.get("source") == "experiment" and row.get("experiment_verdict") != "up":
                continue
            donor_params = parse_params(row.get("params_json"))
            positive = donor_params.get("positive_prompt") or row.get("positive_prompt") or ""
            if not positive or positive == current:
                continue
            donors.append((positive, donor_params.get("negative_prompt",
                                                      row.get("negative_prompt") or "")))
            weights.append(1.0 + (_STAR_BONUS if row.get("starred") else 0.0))
        choice = self._pick_value(
            donors, workflow, "positive_prompt", rows,
            value_of=lambda donor: donor[0], appeal=weights,
        )
        if choice is None:
            return False
        params["positive_prompt"], params["negative_prompt"] = choice
        return True

    def _swap_combo(self, params, pd, workflow, rows):
        candidates = [o for o in pd.options if o != params.get(pd.key)]
        choice = self._pick_value(candidates, workflow, pd.key, rows)
        if choice is None:
            return False
        params[pd.key] = choice
        return True

    def _jitter_numeric(self, params, pd, workflow, rows):
        base = params.get(pd.key, pd.default)
        try:
            base = float(base)
        except (TypeError, ValueError):
            base = float(pd.default)
        sigma = (pd.max_val - pd.min_val) / _JITTER_SPREAD
        candidates = []
        for _ in range(_NUMERIC_CANDIDATES):
            value = self._snap(base + self._rng.gauss(0.0, sigma), pd)
            if value != params.get(pd.key) and value not in candidates:
                candidates.append(value)
        choice = self._pick_value(candidates, workflow, pd.key, rows, pd=pd)
        if choice is None:
            return False
        params[pd.key] = choice
        return True

    @staticmethod
    def _snap(value, pd):
        """Clamp a jittered value to the dimension's range and step, and to int
        for an int dimension."""
        value = max(pd.min_val, min(pd.max_val, value))
        if pd.step:
            value = pd.min_val + round((value - pd.min_val) / pd.step) * pd.step
            value = max(pd.min_val, min(pd.max_val, value))
        return int(round(value)) if pd.type == "int" else round(value, 4)

    # --- verdict-driven value weights --------------------------------------

    def _pick_value(self, candidates, workflow, key, rows, *, pd=None,
                    value_of=lambda c: c, appeal=None):
        """Draw one of ``candidates`` for ``key``, steered by review verdicts.

        Each candidate's weight is the mean of a Beta(1+ups, 1+downs) posterior
        over its verdict record — 0.5 with no evidence, rising under up-votes,
        falling under down-votes — times any caller-supplied ``appeal`` (a prompt
        donor's stars). A candidate the reviews have clearly damned is vetoed
        from the pool outright; an exploration floor keeps the rest reachable.
        Returns ``None`` when nothing survives to choose (no candidates, or all
        vetoed with nothing to fall back on).
        """
        tallies = self._verdict_tallies(workflow, key, rows, pd)
        pool = []
        weights = []
        for i, candidate in enumerate(candidates):
            ups, downs = tallies.get(self._bucket(value_of(candidate), pd), (0, 0))
            weight = (1.0 + ups) / (2.0 + ups + downs)
            if ups + downs >= _VETO_MIN_VOTES and weight <= _VETO_MAX_WEIGHT:
                continue  # the reviews have damned this value — drop it outright
            pool.append(candidate)
            weights.append(weight * (appeal[i] if appeal else 1.0))
        if not pool:
            return None
        return self._explore_or_exploit(pool, weights)

    def _verdict_tallies(self, workflow, key, rows, pd) -> dict:
        """Per value bucket, the ``(ups, downs)`` this workflow's reviewed
        experiments have recorded for ``key``."""
        tallies: dict = {}
        for row in rows:
            if row.get("source") != "experiment":
                continue
            verdict = row.get("experiment_verdict")
            if verdict not in ("up", "down"):
                continue
            if (row.get("workflow_name") or "") != workflow.name:
                continue
            value = parse_params(row.get("params_json")).get(key)
            if value is None:
                continue
            bucket = self._bucket(value, pd)
            ups, downs = tallies.get(bucket, (0, 0))
            tallies[bucket] = (ups + 1, downs) if verdict == "up" else (ups, downs + 1)
        return tallies

    @staticmethod
    def _bucket(value, pd):
        """The verdict-tally key for a value: numerics pool into coarse bins
        across their range (individual floats would never repeat), everything
        else tallies exactly."""
        if pd is not None and pd.type in ("int", "float"):
            try:
                span = pd.max_val - pd.min_val
                return round((float(value) - pd.min_val) / span * _NUMERIC_BUCKETS)
            except (TypeError, ValueError, ZeroDivisionError):
                return value
        return value

    # --- weighted sampling --------------------------------------------------

    def _explore_or_exploit(self, candidates, weights):
        """Draw by weight, except an exploration floor's worth of uniform draws."""
        if self._rng.random() < _EXPLORE_CHANCE:
            return self._rng.choice(candidates)
        return self._weighted_choice(candidates, weights)

    def _weighted_choice(self, candidates, weights):
        return self._rng.choices(candidates, weights=weights, k=1)[0]
