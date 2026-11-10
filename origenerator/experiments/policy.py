from __future__ import annotations

from dataclasses import dataclass

from origenerator.gallery import parse_params, produced_output
from origenerator.generation_config import filled_params, randomize_seeds
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.media import MediaType
from origenerator.workflows.base import ParamType
from origenerator.workflows.derived_size import without_an_explicit_size
from origenerator.workflows.lora_rows import (
    a_lora_filed_apart_from_its_model,
    strength_without_its_lora,
)

_UP_BONUS = 1.0
_FAVORITE_BONUS = 2 * _UP_BONUS
_RECENT_BONUS = _UP_BONUS / 2
_RECENT_ROWS = 25

_VIDEO_SHARE = 0.8
_LORA_DIM_WEIGHT = 4.0

_SECOND_DIM_CHANCE = 0.3
_EXPLORE_CHANCE = 0.25
_VETO_MIN_VOTES = 3
_VETO_MAX_WEIGHT = 0.25
_JITTER_SHARE_OF_THE_RANGE = 1 / 8
_NUMERIC_CANDIDATES = 5
_NUMERIC_BUCKETS = 8


def _rule_of_succession(ups: int, downs: int) -> float:
    return (1.0 + ups) / (2.0 + ups + downs)


@dataclass
class Proposal:
    workflow: object
    params: dict
    base_prompt_id: str
    mutated_keys: tuple


class ExperimentPolicy:
    def __init__(self, registry, rng):
        self._registry = registry
        self._rng = rng

    def propose(self, rows: list[dict]) -> Proposal | None:
        bases = self._prefer_videos(self._base_candidates(rows))
        if not bases:
            return None
        weights = [self._base_weight(row, i) for i, (row, _) in enumerate(bases)]
        row, workflow = self._weighted_choice(bases, weights)
        params = without_an_explicit_size(filled_params(row, workflow), workflow)
        mutated = self._mutate(params, workflow, rows)
        params = randomize_seeds(params, workflow.seed_keys())
        return Proposal(workflow, params, row["prompt_id"], tuple(mutated))

    def _base_candidates(self, rows):
        out = []
        for row in rows:
            workflow = self._registry.get(row.get("workflow_name") or "")
            if workflow is None:
                continue
            if not workflow.selectable:
                continue
            if row.get("status") != GenerationStatus.COMPLETED or not produced_output(row):
                continue
            if row.get("source") == GenerationSource.EXPERIMENT and row.get("experiment_verdict") != "up":
                continue
            if workflow.missing_inputs(parse_params(row.get("params_json"))):
                continue
            out.append((row, workflow))
        return out

    def _prefer_videos(self, bases):
        videos = [b for b in bases if b[1].output_type == MediaType.VIDEO]
        stills = [b for b in bases if b[1].output_type != MediaType.VIDEO]
        if not videos or not stills:
            return bases
        return videos if self._rng.random() < _VIDEO_SHARE else stills

    @staticmethod
    def _base_weight(row, rows_newer):
        weight = 1.0
        if row.get("starred"):
            weight += _FAVORITE_BONUS
        if row.get("experiment_verdict") == "up":
            weight += _UP_BONUS
        if rows_newer < _RECENT_ROWS:
            weight += _RECENT_BONUS
        return weight

    def _mutate(self, params, workflow, rows):
        definitions = workflow.param_definitions()
        dims = self._mutable_dims(definitions)
        if not dims:
            return []
        count = 2 if len(dims) > 1 and self._rng.random() < _SECOND_DIM_CHANCE else 1
        mutated = []
        for dim in self._weighted_dim_order(dims):
            if len(mutated) == count:
                break
            if self._apply_mutation(params, dim, definitions, workflow, rows):
                mutated.append(dim.key)
        return mutated

    def _weighted_dim_order(self, dims):
        remaining = list(dims)
        order = []
        while remaining:
            weights = [_LORA_DIM_WEIGHT if "lora" in d.key.lower() else 1.0
                       for d in remaining]
            index = self._rng.choices(range(len(remaining)), weights=weights, k=1)[0]
            order.append(remaining.pop(index))
        return order

    @staticmethod
    def _mutable_dims(definitions):
        dims = []
        for pd in definitions:
            if pd.key == "batch_size":
                continue
            if pd.key == "positive_prompt" or (pd.type in (ParamType.INT, ParamType.FLOAT) and pd.min_val is not None \
                    and pd.max_val is not None and pd.max_val > pd.min_val) or (pd.type == ParamType.DROPDOWN and pd.options and len(pd.options) > 1):
                dims.append(pd)
        return dims

    def _apply_mutation(self, params, pd, definitions, workflow, rows) -> bool:
        if pd.key == "positive_prompt":
            return self._crossover_prompts(params, workflow, rows)
        if strength_without_its_lora(pd.key, params):
            return False
        if pd.type == ParamType.DROPDOWN:
            return self._swap_dropdown(params, pd, definitions, workflow, rows)
        return self._jitter_numeric(params, pd, workflow, rows)

    def _crossover_prompts(self, params, workflow, rows):
        current = params.get("positive_prompt", "")
        donors = []
        weights = []
        for row in rows:
            if (row.get("workflow_name") or "") != workflow.name:
                continue
            if row.get("status") != GenerationStatus.COMPLETED or not produced_output(row):
                continue
            if row.get("source") == GenerationSource.EXPERIMENT and row.get("experiment_verdict") != "up":
                continue
            donor_params = parse_params(row.get("params_json"))
            positive = donor_params.get("positive_prompt") or row.get("positive_prompt") or ""
            if not positive or positive == current:
                continue
            donors.append((positive, donor_params.get("negative_prompt",
                                                      row.get("negative_prompt") or "")))
            weights.append(1.0 + (_FAVORITE_BONUS if row.get("starred") else 0.0))
        choice = self._pick_value(
            donors, self._verdict_tallies(workflow, "positive_prompt", rows, None),
            value_of=lambda donor: donor[0], appeal=weights,
        )
        if choice is None:
            return False
        params["positive_prompt"], params["negative_prompt"] = choice
        return True

    def _swap_dropdown(self, params, pd, definitions, workflow, rows):
        candidates = [o for o in pd.options if o != params.get(pd.key)
                      and not a_lora_filed_apart_from_its_model({**params, pd.key: o},
                                                                definitions)]
        choice = self._pick_value(
            candidates, self._verdict_tallies(workflow, pd.key, rows, None))
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
        sigma = (pd.max_val - pd.min_val) * _JITTER_SHARE_OF_THE_RANGE
        candidates = []
        for _ in range(_NUMERIC_CANDIDATES):
            value = self._snap(base + self._rng.gauss(0.0, sigma), pd)
            if value != params.get(pd.key) and value not in candidates:
                candidates.append(value)
        choice = self._pick_value(
            candidates, self._verdict_tallies(workflow, pd.key, rows, pd), pd=pd)
        if choice is None:
            return False
        params[pd.key] = choice
        return True

    @staticmethod
    def _snap(value, pd):
        value = max(pd.min_val, min(pd.max_val, value))
        if pd.step:
            value = pd.min_val + round((value - pd.min_val) / pd.step) * pd.step
            value = max(pd.min_val, min(pd.max_val, value))
        return round(value) if pd.type == ParamType.INT else round(value, 4)

    def _pick_value(self, candidates, tallies, *, pd=None, value_of=lambda c: c, appeal=None):
        pool = []
        weights = []
        for i, candidate in enumerate(candidates):
            ups, downs = tallies.get(self._bucket(value_of(candidate), pd), (0, 0))
            weight = _rule_of_succession(ups, downs)
            if ups + downs >= _VETO_MIN_VOTES and weight <= _VETO_MAX_WEIGHT:
                continue
            pool.append(candidate)
            weights.append(weight * (appeal[i] if appeal else 1.0))
        if not pool:
            return None
        return self._explore_or_exploit(pool, weights)

    def _verdict_tallies(self, workflow, key, rows, pd) -> dict:
        tallies: dict = {}
        for row in rows:
            if row.get("source") != GenerationSource.EXPERIMENT:
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
        if pd is not None and pd.type in (ParamType.INT, ParamType.FLOAT):
            try:
                span = pd.max_val - pd.min_val
                return round((float(value) - pd.min_val) / span * _NUMERIC_BUCKETS)
            except (TypeError, ValueError, ZeroDivisionError):
                return value
        return value

    def _explore_or_exploit(self, candidates, weights):
        if self._rng.random() < _EXPLORE_CHANCE:
            return self._rng.choice(candidates)
        return self._weighted_choice(candidates, weights)

    def _weighted_choice(self, candidates, weights):
        return self._rng.choices(candidates, weights=weights, k=1)[0]
