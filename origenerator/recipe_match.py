"""Pick the recipe for a dropdown act, mined from the gallery, in two tiers.

An act's videos are found by their stored prompt ("assume the prompt was respected",
so it names what's happening) and grouped into recipes — ignoring the free-text
prompt, the input image and the seeds, so the same setup on different frames counts
once. Each recipe's chosen video supplies its full params (prompt included) to re-run
on a dropped image via the gallery's combine launch.

- :func:`smart_recipe` (primary) is situation-aware: the local LLM compares the
  dropped image's scene to the *starting scene* each recipe is used with — where
  "is the subject already in frame, and whose hand is on it" actually lives, since
  start-frame property — and picks the recipe that fits.
- :func:`best_recipe` (fallback, when the model is unreachable or finds no fit) is
  the act's most-used recipe, image-independent.
- :func:`curated_recipe` sits above both tiers: an act the content overlay pins a
  hand-tuned workflow+params for skips mining entirely — its videos may all share
  a weakness (mining can only reproduce the past), and the pin is the way out.
- :func:`available_categories` reports which acts have any video at all (or a
  curated recipe), so the dropdown can grey out the ones no tier could answer.

The LLM boundary is one function, so the grouping and act-membership logic stays
unit-testable without a live model, a database, or a widget.
"""

import json
import logging
import urllib.request
from collections import defaultdict

from origenerator.content import load_content

logger = logging.getLogger(__name__)

_CONTENT = load_content()

# The acts a prompt can depict, and the distinctive substrings that mark each
# one, are library vocabulary rather than logic: they come from the content
# overlay (content.example.json documents the shape).  Conservative by design —
# a loose match would fire on unrelated words, and a prompt that dodges every
# substring simply does not count toward its act.
CATEGORIES: tuple[str, ...] = tuple(_CONTENT["recipe_categories"])
_CATEGORY_KEYWORDS = {
    name: tuple(words) for name, words in _CONTENT["recipe_categories"].items()
}

# Optional hand-tuned recipes, also overlay vocabulary: an act named here runs
# its pinned workflow+params instead of whatever the gallery mining would pick.
# Mining can only ever reproduce past videos, so an act whose past videos all
# share a weakness (the wrong LoRA, a speed-over-quality setup) is stuck with
# it; a curated entry is how the overlay breaks that loop with a known-good
# setup (a purpose-trained LoRA pair at its author's recommended settings).
_CURATED_RECIPES: dict = _CONTENT.get("combine_recipes") or {}


def curated_recipe(category: str) -> dict | None:
    """The overlay's hand-tuned recipe for ``category``, or ``None`` for mining.

    A usable entry is a dict naming a ``workflow`` (its ``params`` dict holds
    the pinned settings; anything unnamed falls to the workflow's defaults).
    Anything else — no entry, or a malformed one — returns ``None`` so the
    caller falls back to mining the gallery rather than failing the act.
    """
    spec = _CURATED_RECIPES.get(category)
    if not isinstance(spec, dict) or not spec.get("workflow"):
        return None
    return spec

# Params that don't define a recipe: the free-text prompt, the start frame, the
# seeds and bookkeeping — plus values that are incidental or derived, not deliberate
# recipe choices: the output size (derived in-graph from the input image), the clip
# length, and the dual-sampler split points (derived from ``steps``). Excluding them
# keeps the signature on the real levers (model, LoRA, sampler regime) so the same
# setup on different frames/lengths groups as one recipe instead of fragmenting.
_RECIPE_EXCLUDE = frozenset((
    "positive_prompt", "negative_prompt", "input_image",
    "seed", "noise_seed", "filename_prefix", "batch_size",
    "width", "height", "length", "frame_count", "frame_rate",
    "start_at_step", "end_at_step",
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


def _created(row) -> str:
    """A row's creation timestamp for recency ordering (missing sorts oldest)."""
    return row.get("created_at") or ""


def _act_recipe_groups(category: str, video_rows, *, require_scene: bool = False) -> dict:
    """The act's videos grouped by recipe signature. ``require_scene`` also drops
    members with no ``start_scene`` — nothing for the LLM to situation-match on."""
    groups = defaultdict(list)
    for row in video_rows:
        if not _matches_category(category, row.get("positive_prompt")):
            continue
        if require_scene and not (row.get("start_scene") or "").strip():
            continue
        groups[_recipe_signature(row)].append(row)
    return groups


def available_categories(video_rows) -> set[str]:
    """The acts a picked dropdown entry can actually answer: those ``video_rows``
    holds at least one video of (a recipe can be mined), plus those the overlay
    curates a recipe for (nothing to mine — the recipe is pinned). The panel greys
    out the rest, so an act that could only ever answer "no recipe yet" is never
    offered."""
    return {c for c in CATEGORIES
            if curated_recipe(c) is not None
            or any(_matches_category(c, row.get("positive_prompt")) for row in video_rows)}


def best_recipe(category: str, video_rows) -> str | None:
    """The prompt_id of the exemplar for ``category``'s best recipe, or ``None``.

    "Best" is the recipe (model + params) behind the most of the user's videos of
    that act; a tie goes to the recipe with the more recent video. The winning recipe
    is represented by its most-recent video, whose full params (prompt included) the
    caller re-runs on the dropped image. ``None`` when the gallery holds no video of
    the act, so the caller can prompt the user to make one first.
    """
    groups = _act_recipe_groups(category, video_rows)
    if not groups:
        return None
    best = max(groups.values(), key=lambda g: (len(g), max(_created(r) for r in g)))
    return max(best, key=_created)["prompt_id"]


# --- situation-aware pick (LLM over recipes' starting scenes) ---------------


def _recipe_representatives(category: str, video_rows) -> list:
    """One representative video per recipe among ``category``'s videos: the most-recent
    member of each recipe group that carries a ``start_scene`` (its input image's
    prompt) to match on. A recipe with no start scene anywhere is left out — there's
    nothing to compare the dropped image against."""
    groups = _act_recipe_groups(category, video_rows, require_scene=True)
    return [max(group, key=_created) for group in groups.values()]


def build_scene_messages(category: str, image_scene: str, representatives: list, system_prompt: str) -> list:
    """The chat messages for one situation match: the rules, then the dropped image's
    scene and each candidate recipe shown by the starting scene it's made for."""
    listing = "\n".join(f"{i}. {r.get('start_scene')}" for i, r in enumerate(representatives))
    user = (
        f"Desired act: {category}\n\n"
        f"The input image's scene:\n{image_scene}\n\n"
        f"Candidate {category} recipes, each shown by the starting scene it is made for:\n{listing}\n\n"
        "Pick the number whose starting scene best matches the input image's "
        "situation — whether the subject is already in frame, and if so whose hand(s) are "
        "on it (hers, his, or neither). "
        'Reply with only JSON: {"choice": <the number, or -1 if none fit>}'
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def _extract_json(content: str) -> dict:
    """Parse a JSON object out of an LLM reply, tolerating fences/preamble."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def parse_choice(completion: dict, options: list) -> str | None:
    """The chosen recipe's prompt_id from a chat completion, or ``None`` for none.

    ``{"choice": n}`` indexes ``options``; ``-1`` or out of range → ``None`` (a
    legitimate "none of these fit"). Raises on a reply with no usable choice, which
    the caller treats like any other model failure."""
    obj = _extract_json(completion["choices"][0]["message"]["content"])
    index = int(obj["choice"])
    if 0 <= index < len(options):
        return options[index]["prompt_id"]
    return None


def _post_chat(base_url: str, model: str, messages: list, timeout: float) -> dict:
    """POST one chat request to the local OpenAI-compatible endpoint; return its JSON.

    The single I/O boundary — isolated so the matching above stays testable — over the
    same stdlib ``urllib`` the ComfyUI client and voice rewrite use. Low temperature:
    a lookup, not brainstorming."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def smart_recipe(category: str, image_scene: str, video_rows, *, base_url: str,
                 model: str, system_prompt: str, timeout: float = 20.0) -> str | None:
    """The prompt_id of the recipe whose starting scene best fits the dropped image,
    or ``None`` when there's nothing to pick or the model can't decide.

    Offers the LLM one representative per recipe among ``category``'s videos (each
    shown by the starting scene it's made for) and returns its choice. ``None`` when
    the act has no scored recipe, the model deliberately reports no fit, or the call
    fails — the caller then falls back to :func:`best_recipe`.
    """
    representatives = _recipe_representatives(category, video_rows)
    if not representatives:
        return None
    try:
        completion = _post_chat(
            base_url, model,
            build_scene_messages(category, image_scene, representatives, system_prompt),
            timeout,
        )
        chosen = parse_choice(completion, representatives)
        logger.info("recipe_match: category=%s scene-match chosen=%s of %d recipes",
                    category, chosen, len(representatives))
        return chosen
    except Exception as exc:  # model down / unparseable: caller falls back to best_recipe
        logger.warning("recipe_match: category=%s scene-match failed (%s)", category, exc)
        return None
