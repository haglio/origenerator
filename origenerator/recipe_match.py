"""Pick the one best recipe for a dropdown act, mined from the gallery.

Each act ("gamma", "redacted", …) maps to a single recipe — the model + params the
user has made the most videos with for that act — rather than a per-image search.
An act's videos are found by their stored prompt ("assume the prompt was respected",
so it names what's happening); grouped by recipe, ignoring the free-text prompt, the
input image and the seeds so the same setup on different frames counts once; and the
most-used group's most-recent video supplies the recipe (its full params, prompt
included) to re-run on a dropped image via the gallery's combine launch.

Qt-free and dependency-free, so the grouping and act-membership logic stays
unit-testable without a database or a widget.
"""

import json
from collections import defaultdict

CATEGORIES = ("gamma", "epsilon", "zeta", "redacted", "alpha", "dancing")

# Distinctive substrings that mark a video's prompt as depicting each act — the only
# thing authored per act. Conservative (a loose match like a bare "bj" would fire on
# unrelated words); a prompt that dodges all of them just won't count toward its act.
_CATEGORY_KEYWORDS = {
    "gamma": ("gamma", "gamma", "oral", "alpha", "redacted", "alpha form",
                "anchor in mouth", "anchor in her mouth", "anchor in mouth"),
    "epsilon": ("epsilon", "epsilon", "stroking", "jerking", "jerk off", "stroke"),
    "zeta": ("zeta", "redacted job", "zeta", "zeta", "zeta", "titty redacted",
                "zeta", "between her redacteds", "between her zeta"),
    "redacted": ("redacted", "redacted", "penetrat", "intercourse", "riding", "doggy",
                "cowsubject", "delta"),
    "alpha": ("alpha", "alpha", "redacted", "ejaculat", "redacted", "redacted on",
                "epsilon form"),
    "dancing": ("dancing", "dance", "twerk", "striptease", "strip tease", "stripping"),
}

# Params that vary run-to-run within one recipe: the free-text prompt, the start
# frame, the seeds, and bookkeeping. Excluded from the recipe signature so the same
# model+settings used on different images/prompts groups as a single recipe.
_RECIPE_EXCLUDE = frozenset((
    "positive_prompt", "negative_prompt", "input_image",
    "seed", "noise_seed", "filename_prefix", "batch_size",
))


def _matches_category(category: str, prompt: str) -> bool:
    """Whether ``prompt`` reads as depicting ``category`` by its keyword substrings."""
    low = (prompt or "").lower()
    return any(kw in low for kw in _CATEGORY_KEYWORDS.get(category, ()))


def _hashable(value):
    """A stable, hashable stand-in for a param value (lists/dicts → sorted JSON)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, sort_keys=True)


def _recipe_signature(row: dict):
    """A hashable key for a row's model+params recipe, ignoring the free-text prompt,
    the input image and the seeds — so the same setup on different frames counts as
    one recipe."""
    try:
        params = json.loads(row.get("params_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        params = {}
    if not isinstance(params, dict):
        params = {}
    settings = tuple(sorted(
        (k, _hashable(v)) for k, v in params.items() if k not in _RECIPE_EXCLUDE
    ))
    return (row.get("workflow_name") or "", settings)


def best_recipe(category: str, video_rows) -> str | None:
    """The prompt_id of the exemplar for ``category``'s best recipe, or ``None``.

    "Best" is the recipe (model + params) behind the most of the user's videos of
    that act; a tie goes to the recipe with the more recent video. The winning recipe
    is represented by its most-recent video, whose full params (prompt included) the
    caller re-runs on the dropped image. ``None`` when the gallery holds no video of
    the act, so the caller can prompt the user to make one first.
    """
    def created(row) -> str:
        return row.get("created_at") or ""

    groups = defaultdict(list)
    for row in video_rows:
        if _matches_category(category, row.get("positive_prompt")):
            groups[_recipe_signature(row)].append(row)
    if not groups:
        return None
    best = max(groups.values(), key=lambda g: (len(g), max(created(r) for r in g)))
    return max(best, key=created)["prompt_id"]
