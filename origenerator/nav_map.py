"""The map around one generation, as the players' HUD draws it.

A Fun Time satellite maps the clip on screen against its library: the same
act under other seeds runs right as the seed row, and the same subject's
other acts run down as the column.  A show of this app's generations reads
the same way, in the gallery's own terms.  The subject is a picture, and what
was made of it is the videos animated from it: they run down its column, each
named for the act it shows, and the picture heads theirs as their source.  A
seed is the picture's — a video's own sampler seed says nothing about which
picture it is of — so a picture's row is its settings folder (the workflow,
its version, the model, the LoRA and every setting but the seed), and a
video's is its act animated from the pictures in its own picture's folder.

Pure and Qt-free: rows in, rows out.  The show keeps the item on screen and
the gallery supplies the library it is mapped against.
"""
from __future__ import annotations

from dataclasses import dataclass

from origenerator import gallery
from origenerator.media import MediaType
from origenerator.recipe_match import act_of
from origenerator.search import content_stems

# How many near configurations "more seeds" adds to the exact family.  Six
# fills the HUD's seed row; the point of the cap is that widening must never
# dump a whole model's worth of pictures into a row meant to show close kin.
WIDEN_ADDITIONS = 6

# What a picture is called among the acts of the videos animated from it.
SOURCE_IMAGE = "Source image"


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


def _likeness(one: frozenset[str], other: frozenset[str]) -> float:
    """How alike two prompts read, 0.0-1.0: shared words over all words between them."""
    if not one or not other:
        return 0.0
    return len(one & other) / len(one | other)


@dataclass(frozen=True)
class Surroundings:
    """What the library holds around one generation: the act its own row is
    named for, the same act under other seeds along the row, down the column
    one generation for each other act of the same picture with the act it
    shows, and the rest of that picture's whole group — what a loop down the
    column plays, twins of an act included."""

    label: str = ""
    seeds: tuple[dict, ...] = ()
    configs: tuple[dict, ...] = ()
    actions: tuple[tuple[dict, str], ...] = ()
    group: tuple[dict, ...] = ()


def _source_picture_id(row: dict, image_index) -> str | None:
    """Which picture *row* was animated from, or ``None`` for a row that is not
    a video or whose start frame no generation in the library produced."""
    if gallery.media_type_of_row(row) != MediaType.VIDEO:
        return None
    return gallery.source_image_id_in(row, image_index)


class _Animations:
    """Which picture each of the library's videos was animated from, and back
    — read once, because every question the map asks would walk it again."""

    def __init__(self, rows, image_index) -> None:
        pictures = {row["prompt_id"]: row for row in rows
                    if gallery.media_type_of_row(row) != MediaType.VIDEO}
        self._picture_of: dict[str, dict] = {}
        self._videos_of: dict[str, list[dict]] = {}
        for row in rows:
            picture = pictures.get(_source_picture_id(row, image_index))
            if picture is not None:
                self._picture_of[row["prompt_id"]] = picture
                self._videos_of.setdefault(picture["prompt_id"], []).append(row)

    def picture_of(self, row: dict) -> dict | None:
        return self._picture_of.get(row["prompt_id"])

    def videos_of(self, picture: dict) -> list[dict]:
        return self._videos_of.get(picture["prompt_id"], [])

    def label_of(self, row: dict) -> str:
        """The act(s) *row*'s map row is named for: what it shows, and — for a
        picture something was animated from — that it is their source."""
        source = SOURCE_IMAGE if self.videos_of(row) else ""
        return ", ".join(act for act in (source, act_of(row)) if act)

    def group_of(self, row: dict) -> list[dict]:
        """The picture *row* is or was animated from, then every video animated
        from it.  A video made from no picture the library holds stands alone."""
        picture = self.picture_of(row) or row
        return [picture, *self.videos_of(picture)]


def _one_per_act(labeled) -> tuple[tuple[dict, str], ...]:
    """The first generation showing each act, in the order they came: the
    column steps between acts, so twins of one act share its row."""
    first: dict[str, dict] = {}
    for row, label in labeled:
        first.setdefault(label, row)
    return tuple((row, label) for label, row in first.items())


def act_labels(rows, *, image_index) -> dict[str, str]:
    """What each of *rows* is named for on the map, by id — what an act filter
    matches a generation on."""
    animations = _Animations(rows, image_index)
    return {row["prompt_id"]: animations.label_of(row) for row in rows}


def surroundings(current: dict, rows, *, image_index) -> Surroundings:
    animations = _Animations(rows, image_index)
    own = animations.label_of(current)
    picture = animations.picture_of(current)
    if picture is None:
        seeds = seed_family(current, rows, image_index=image_index)[1:]
    else:
        # A video's seed is its picture's: the same act, animated from the
        # same configuration of picture under other seeds.
        seeds = [video
                 for sibling in seed_family(picture, rows, image_index=image_index)
                 for video in animations.videos_of(sibling)
                 if video["prompt_id"] != current["prompt_id"]
                 and animations.label_of(video) == own]
    group = [row for row in animations.group_of(current)
             if row["prompt_id"] != current["prompt_id"]]
    return Surroundings(
        label=own,
        seeds=tuple(seeds),
        # Configurations belong to pictures: a video's seed is the picture's
        # it was animated from, so another configuration of it is a video of
        # that picture, which the acts below already are.
        configs=() if picture is not None else tuple(
            config_family(current, rows, image_index=image_index)[1:]),
        actions=_one_per_act(
            (row, label) for row, label in ((row, animations.label_of(row)) for row in group)
            if label != own),
        group=tuple(group),
    )


def beyond_the_row(current: dict, rows, *, image_index,
                   additions: int = WIDEN_ADDITIONS) -> list[dict]:
    """What "more seeds" adds to *current*'s row, nearest first, up to
    *additions* of them — nothing when nothing lies beyond it, which is a dead
    end worth saying rather than a row of strangers.

    Beyond a video animated from a picture lie other videos of its act — the
    act is a bound, not a preference: another act is what the column is for —
    nearest by the model and LoRA that animated them, then by how alike the
    pictures they were animated from read.  Beyond anything else lie the other
    configurations of its own model: the same LoRA first, then the prompt that
    reads most like this one.
    """
    animations = _Animations(rows, image_index)
    around = surroundings(current, rows, image_index=image_index)
    kept = {current["prompt_id"], *(row["prompt_id"] for row in around.seeds)}
    model = gallery.folder_key_at_level(current, "model", image_index)
    lora = gallery.folder_key_at_level(current, "lora", image_index)
    picture = animations.picture_of(current)
    if picture is None:
        candidates = [row for row in _others(current, rows)
                      if gallery.folder_key_at_level(row, "model", image_index) == model]
    else:
        candidates = [row for row in rows
                      if gallery.media_type_of_row(row) == MediaType.VIDEO
                      and animations.label_of(row) == around.label]
    subject = content_stems(picture or current)
    ranked = sorted(
        (
            (gallery.folder_key_at_level(row, "model", image_index) != model,
             gallery.folder_key_at_level(row, "lora", image_index) != lora,
             -_likeness(subject, content_stems(animations.picture_of(row) or row)),
             row["prompt_id"],
             row)
            for row in candidates if row["prompt_id"] not in kept
        ),
        key=lambda scored: scored[:4],
    )
    return [scored[-1] for scored in ranked[:max(additions, 0)]]


def one_per_stretch(rows, *, image_index) -> list[dict]:
    """*rows* with every stretch of generating into one settings folder stood
    for by the newest of that stretch.

    A sitting makes several seeds of a configuration one after another, so a
    listing of everything newest-first is mostly runs; a show of it plays one
    of each, and the map's seed row reaches the rest.  What counts as one
    stretch is read off when the generations were MADE, not off where they sit
    in the listing handed over: Latest moves a picture to where its
    enhancement falls, which breaks a sitting's run into pieces wherever a
    picture of it was enhanced later.  The listing's own order is what comes
    back, minus what the stretches swallowed.
    """
    made = sorted(rows, key=lambda row: row.get("id") or 0, reverse=True)
    stands_for_the_stretch: list[str] = []
    folder_of_the_stretch = object()
    for row in made:
        folder = gallery.settings_folder_key(row, image_index)
        if folder != folder_of_the_stretch:
            stands_for_the_stretch.append(row["prompt_id"])
            folder_of_the_stretch = folder
    kept = set(stands_for_the_stretch)
    return [row for row in rows if row["prompt_id"] in kept]
