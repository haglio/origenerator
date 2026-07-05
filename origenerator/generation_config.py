"""Pure helpers for reasoning about a generation's configuration.

Qt-free so the logic stays unit-testable without a widget toolkit. Shared by
the gallery (reuse) and the generate view (subtab prefill + strip-click compare).
"""

import json
import random
from dataclasses import dataclass

_DENORMALIZED_COLUMNS = ("positive_prompt", "negative_prompt", "seed")

_SEED_MAX = (1 << 63) - 1


@dataclass
class ConfigSnapshot:
    """A generate panel's live settings, captured for comparison.

    ``params`` is read without randomizing the seed; ``seed_is_random`` records
    whether the seed's "Random" box is checked (in which case the panel can
    never match a concrete past generation), so a reopened tab comes back the way
    it was left.
    """

    workflow_name: str
    params: dict
    seed_is_random: bool

    def to_dict(self) -> dict:
        """A JSON-serializable view, for persisting an open generate tab."""
        return {
            "workflow_name": self.workflow_name,
            "params": self.params,
            "seed_is_random": self.seed_is_random,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConfigSnapshot":
        """Rebuild from :meth:`to_dict` output, tolerating partial/corrupt data."""
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
    """Return a generation row's full params dict.

    ``params_json`` is authoritative; the denormalized ``positive_prompt``,
    ``negative_prompt`` and ``seed`` columns are folded in only for keys the
    JSON doesn't already carry. Missing or malformed ``params_json`` yields an
    empty base.
    """
    raw = row.get("params_json")
    try:
        params = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        params = {}
    if not isinstance(params, dict):
        params = {}
    for key in _DENORMALIZED_COLUMNS:
        val = row.get(key)
        if val is not None and key not in params:
            params[key] = val
    return params


def _params_identical(a: dict, b: dict) -> bool:
    """True when two param dicts carry the same keys and equal values."""
    return a.keys() == b.keys() and all(_values_equal(a[k], b[k]) for k in a)


def find_duplicate_generation(rows, snapshot: ConfigSnapshot) -> dict | None:
    """Return the first already-completed generation ``snapshot`` would reproduce.

    Re-running a config whose seed isn't randomized re-creates a byte-identical
    output, so this lets the caller warn before wasting a slot. A row counts only
    when it is a reproducible generation of ours whose full parameters match:

    * ``completed`` -- a failed or canceled attempt is a legitimate retry.
    * ``source == "generated"`` -- imports lack our full graph/params and aren't
      reproducible, so re-running never re-creates one.
    * every parameter equal -- matching only the keys a stored row happens to
      carry would wrongly flag a sparsely recorded row (e.g. a reused import)
      when the user changed a field it never stored.

    Returns ``None`` when the seed is random (every run differs) or nothing matches.
    """
    if snapshot.seed_is_random:
        return None
    for row in rows:
        if row.get("status") != "completed":
            continue
        if row.get("source", "generated") != "generated":
            continue
        if row.get("workflow_name", "") != snapshot.workflow_name:
            continue
        if _params_identical(snapshot.params, merge_denormalized(row)):
            return row
    return None


def randomize_seeds(params: dict, seed_keys) -> dict:
    """Return a copy of ``params`` with every key in ``seed_keys`` re-rolled.

    Used to re-run a generation as a fresh variation: same settings, new seed.
    Each named key is set (even if absent) so the rebuilt payload always has a
    seed to use; a workflow with two seeds (e.g. dual-noise video) re-rolls both.
    """
    out = dict(params)
    for key in seed_keys:
        out[key] = random.randint(0, _SEED_MAX)
    return out


def filled_params(row: dict, workflow) -> dict:
    """A stored row's params with any it didn't carry filled from the workflow's
    defaults (imports keep only sparse metadata) — its seeds left exactly as
    stored. The reproducible half of :func:`prepared_params`, used on its own to
    re-run a recipe while pinning one of its two seeds (an i2v re-roll that keeps
    the video seed, say).
    """
    params = merge_denormalized(row)
    for key, value in workflow.default_params().items():
        params.setdefault(key, value)
    return params


def prepared_params(row: dict, workflow) -> dict:
    """A stored row's params readied to generate a fresh variation of it.

    :func:`filled_params` with every seed re-rolled — the common preparation a
    gallery re-roll and a Generate-tab random input both run before rebuilding a
    payload.
    """
    return randomize_seeds(filled_params(row, workflow), workflow.seed_keys())
