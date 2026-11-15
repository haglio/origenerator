from __future__ import annotations

import json
import random
from dataclasses import dataclass
from functools import lru_cache

from app_support.gallery_rows import source_of

from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.output_files import READINGS_KEPT, produced_output

_DENORMALIZED_COLUMNS = ("positive_prompt", "negative_prompt", "seed")

_SEED_MAX = (1 << 63) - 1


@dataclass
class ConfigSnapshot:
    workflow_name: str
    params: dict
    seed_is_random: bool

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "params": self.params,
            "seed_is_random": self.seed_is_random,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConfigSnapshot:
        params = data.get("params")
        if not isinstance(params, dict):
            params = {}
        return cls(
            workflow_name=str(data.get("workflow_name", "")),
            params=params,
            seed_is_random=bool(data.get("seed_is_random", False)),
        )


_FLOAT_TOL = 1e-9


def _values_equal(a, b) -> bool:
    a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
    if a_num and b_num:
        return abs(a - b) < _FLOAT_TOL
    return a == b


def merge_denormalized(row: dict) -> dict:
    return _with_what_only_its_columns_hold(row, _recorded)


def _recorded(raw: str | None) -> dict:
    try:
        params = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        params = {}
    return params if isinstance(params, dict) else {}


_recorded_as_read_before = lru_cache(maxsize=READINGS_KEPT)(_recorded)


def _with_what_only_its_columns_hold(row: dict, recorded) -> dict:
    params = recorded(row.get("params_json"))
    only_in_columns = {key: row[key] for key in _DENORMALIZED_COLUMNS
                       if row.get(key) is not None and key not in params}
    return {**params, **only_in_columns} if only_in_columns else params


def _params_identical(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(_values_equal(a[k], b[k]) for k in a)


def configs_match(a: ConfigSnapshot, b: ConfigSnapshot) -> bool:
    return (a.workflow_name == b.workflow_name
            and a.seed_is_random == b.seed_is_random
            and _params_identical(a.params, b.params))


def find_duplicate_generation(rows, snapshot: ConfigSnapshot) -> dict | None:
    if snapshot.seed_is_random:
        return None
    for row in rows:
        if not reproducible(row):
            continue
        if row.get("workflow_name", "") != snapshot.workflow_name:
            continue
        if _params_identical(snapshot.params, _with_what_only_its_columns_hold(
                row, _recorded_as_read_before)):
            return row
    return None


def reproducible(row: dict) -> bool:
    return (row.get("status") == GenerationStatus.COMPLETED
            and produced_output(row)
            and source_of(row) == GenerationSource.GENERATED)


def would_reproduce_a_completed_run(rows, workflow, params: dict, *,
                                   seed_is_random: bool = False) -> bool:
    snapshot = ConfigSnapshot(workflow.name,
                              {**workflow.default_params(), **params},
                              seed_is_random)
    return find_duplicate_generation(rows, snapshot) is not None


def what_a_request_makes(rows, workflow, params: dict, asked_of: dict | None) -> dict | None:
    made = {**workflow.default_params(), **params, **seeds_of(asked_of, workflow)}
    return None if would_reproduce_a_completed_run(rows, workflow, made) else made


def seeds_of(row: dict | None, workflow) -> dict:
    params = merge_denormalized(row or {})
    return {key: params[key] for key in workflow.seed_keys() if params.get(key) not in (None, "")}


def randomize_seeds(params: dict, seed_keys) -> dict:
    out = dict(params)
    for key in seed_keys:
        out[key] = random.randint(0, _SEED_MAX)
    return out


def filled_params(row: dict, workflow) -> dict:
    defaults = workflow.default_params()
    params = merge_denormalized(row)
    never_recorded = [key for key in workflow.seed_keys() if key not in params]
    for key, value in defaults.items():
        params.setdefault(key, value)
    for key in workflow.enhance_keys():
        if key in defaults:
            params[key] = defaults[key]
    return randomize_seeds(params, never_recorded)


def prepared_params(row: dict, workflow) -> dict:
    return randomize_seeds(filled_params(row, workflow), workflow.seed_keys())
