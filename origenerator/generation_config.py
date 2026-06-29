"""Pure helpers for reasoning about a generation's configuration.

Qt-free so the logic stays unit-testable without a widget toolkit. Shared by
the gallery (reuse) and the generate view (subtab prefill + session persistence).
"""

import json
from dataclasses import dataclass

_DENORMALIZED_COLUMNS = ("positive_prompt", "negative_prompt", "seed")


@dataclass
class ConfigSnapshot:
    """A generate panel's live settings, captured to persist and restore a tab.

    ``params`` is read without randomizing the seed; ``seed_is_random`` records
    whether the seed's "Random" box is checked, so a restored tab comes back
    random rather than pinned to the stale seed in the field at save time.
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
