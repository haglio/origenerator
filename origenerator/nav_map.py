"""The map around one generation, as the players' HUD draws it.

A Fun Time satellite maps the clip on screen against its library: the same
configuration under other seeds runs right as the seed row, and the same seed
under other configurations runs down as the column.  A show of this app's
generations reads the same way, in the gallery's own terms — a configuration
is a settings folder (the workflow, its version, the model, the LoRA and every
setting but the seed), and a seed is the sampler's.

Pure and Qt-free: rows in, rows out.  The show keeps the item on screen and
the gallery supplies the library it is mapped against.
"""
from __future__ import annotations

from origenerator import gallery
from origenerator.search import content_stems

# How many near configurations "more seeds" adds to the exact family.  Six
# fills the HUD's seed row; the point of the cap is that widening must never
# dump a whole model's worth of pictures into a row meant to show close kin.
WIDEN_ADDITIONS = 6


def generation_seed(row: dict) -> str | None:
    """The seed *row*'s sampler ran with, or ``None`` for a row that has none.

    Off the params first: a video's sampler seed is ``noise_seed``, which the
    row's ``seed`` column never carries — that column only mirrors a ``seed``
    param — so the column is the fallback rather than the answer.
    """
    params = gallery.parse_params(row.get("params_json"))
    for key in ("seed", "noise_seed"):
        if params.get(key) not in (None, ""):
            return str(params[key])
    return None if row.get("seed") is None else str(row["seed"])


def _others(current: dict, rows) -> list[dict]:
    """The rows of *current*'s workflow other than itself — the only ones that
    can share a settings folder or a model with it, and a filter that costs a
    dict lookup where the keys under it cost a parse each."""
    workflow = current.get("workflow_name")
    return [row for row in rows
            if row["prompt_id"] != current["prompt_id"]
            and row.get("workflow_name") == workflow]


def seed_family(current: dict, rows, *, image_index) -> list[dict]:
    """*current* and every row of its settings folder: the same configuration
    under other seeds, in the order *rows* lists them."""
    key = gallery.settings_folder_key(current, image_index)
    return [current, *(row for row in _others(current, rows)
                       if gallery.settings_folder_key(row, image_index) == key)]


def config_family(current: dict, rows, *, image_index) -> list[dict]:
    """*current* and every row with its seed under another configuration.

    The same workflow and model, because a seed only means the same picture
    where the same sampler draws from the same latent: a seed that collides
    across models is a coincidence, and one across workflows is not even that.
    """
    seed = generation_seed(current)
    if seed is None:
        return [current]
    model = gallery.folder_key_at_level(current, "model", image_index)
    settings = gallery.settings_folder_key(current, image_index)
    return [current, *(
        row for row in _others(current, rows)
        if generation_seed(row) == seed
        and gallery.folder_key_at_level(row, "model", image_index) == model
        and gallery.settings_folder_key(row, image_index) != settings
    )]


def _picture_key(row: dict, image_index) -> str:
    """Which picture an image-conditioned row was made from, or "" for a row
    made from nothing — the tier under the LoRA that only a video has."""
    if not gallery.is_image_conditioned(row.get("workflow_name")):
        return ""
    return gallery.folder_key_at_level(row, "source_image", image_index)


def _likeness(one: frozenset[str], other: frozenset[str]) -> float:
    """How alike two prompts read, 0.0-1.0: shared words over all words between them."""
    if not one or not other:
        return 0.0
    return len(one & other) / len(one | other)


def widened_family(current: dict, rows, *, image_index,
                   additions: int = WIDEN_ADDITIONS) -> list[dict] | None:
    """The seed row widened past the exact configuration — "more seeds": the
    family, then the nearest other configurations of the same model, up to
    *additions* of them.  ``None`` when the model holds nothing else to widen
    to, which is a dead end worth saying rather than a row of strangers.

    Nearest by how little the configuration differs: the same LoRA first, then
    (for a video) the same source picture, then the prompt that reads most like
    this one — so what joins the row is the slightly-different, not the
    merely-same-model.
    """
    own = seed_family(current, rows, image_index=image_index)
    kept = {row["prompt_id"] for row in own}
    model = gallery.folder_key_at_level(current, "model", image_index)
    lora = gallery.folder_key_at_level(current, "lora", image_index)
    picture = _picture_key(current, image_index)
    mine = content_stems(current)
    ranked = sorted(
        (
            (gallery.folder_key_at_level(row, "lora", image_index) != lora,
             _picture_key(row, image_index) != picture,
             -_likeness(mine, content_stems(row)),
             row["prompt_id"],
             row)
            for row in _others(current, rows)
            if row["prompt_id"] not in kept
            and gallery.folder_key_at_level(row, "model", image_index) == model
        ),
        key=lambda scored: scored[:4],
    )
    if not ranked:
        return None
    return [*own, *(scored[-1] for scored in ranked[:max(additions, 0)])]


def one_per_stretch(rows, *, image_index) -> list[dict]:
    """*rows* with every run of neighbors from one settings folder stood for by
    the last of the run — the first of them made, in a list that is newest
    first, so a seed landing in a run already shown changes nothing."""
    kept: list[dict] = []
    folder_of_the_run = object()
    stands_for_the_run = 0
    for row in rows:
        if gallery.is_enhanced_row(row):
            kept.append(row)     # a better version, not another try at the seed
            continue
        folder = gallery.settings_folder_key(row, image_index)
        if folder == folder_of_the_run:
            kept[stands_for_the_run] = row
        else:
            stands_for_the_run = len(kept)
            kept.append(row)
            folder_of_the_run = folder
    return kept
