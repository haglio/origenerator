"""Pure helpers for reasoning about a generation's configuration.

Qt-free so the logic stays unit-testable without a widget toolkit. Shared by
the gallery (reuse) and the generate view (subtab prefill + strip-click compare).
"""

import json

_DENORMALIZED_COLUMNS = ("positive_prompt", "negative_prompt", "seed")


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
