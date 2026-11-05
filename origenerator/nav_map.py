from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass

from origenerator import gallery
from origenerator.action_settings import action_of
from origenerator.generation_state import made_here
from origenerator.media import MediaType
from origenerator.search import content_stems

WIDEN_ADDITIONS = 6

SOURCE_IMAGE = "Source image"


def _others(current: dict, rows) -> list[dict]:
    workflow = current.get("workflow_name")
    return [row for row in rows
            if row["prompt_id"] != current["prompt_id"]
            and row.get("workflow_name") == workflow]


def seed_family(current: dict, rows, *, image_index) -> list[dict]:
    key = gallery.settings_folder_key(current, image_index)
    return [current, *(row for row in _others(current, rows)
                       if gallery.settings_folder_key(row, image_index) == key)]


def config_family(current: dict, rows, *, image_index) -> list[dict]:
    seed = gallery.generation_seed(current)
    if seed is None:
        return [current]
    model = gallery.folder_key_at_level(current, "model", image_index)
    settings = gallery.settings_folder_key(current, image_index)
    return [current, *(
        row for row in _others(current, rows)
        if gallery.generation_seed(row) == seed
        and gallery.folder_key_at_level(row, "model", image_index) == model
        and gallery.settings_folder_key(row, image_index) != settings
    )]


def _likeness(one: frozenset[str], other: frozenset[str]) -> float:
    if not one or not other:
        return 0.0
    return len(one & other) / len(one | other)


@dataclass(frozen=True)
class Surroundings:
    label: str = ""
    seeds: tuple[dict, ...] = ()
    configs: tuple[dict, ...] = ()
    actions: tuple[tuple[dict, str], ...] = ()
    group: tuple[dict, ...] = ()


def _source_image_id(row: dict, image_index) -> str | None:
    if gallery.media_type_of_row(row) != MediaType.VIDEO:
        return None
    return gallery.source_image_id_in(row, image_index)


class _Animations:
    def __init__(self, rows, image_index) -> None:
        images = {row["prompt_id"]: row for row in rows
                  if gallery.media_type_of_row(row) != MediaType.VIDEO}
        self._image_of: dict[str, dict] = {}
        self._videos_of: dict[str, list[dict]] = {}
        for row in rows:
            image = images.get(_source_image_id(row, image_index))
            if image is not None:
                self._image_of[row["prompt_id"]] = image
                self._videos_of.setdefault(image["prompt_id"], []).append(row)

    def image_of(self, row: dict) -> dict | None:
        return self._image_of.get(row["prompt_id"])

    def videos_of(self, image: dict) -> list[dict]:
        return self._videos_of.get(image["prompt_id"], [])

    def label_of(self, row: dict) -> str:
        source = SOURCE_IMAGE if self.videos_of(row) else ""
        return ", ".join(action for action in (source, action_of(row)) if action)

    def group_of(self, row: dict) -> list[dict]:
        image = self.image_of(row) or row
        return [image, *self.videos_of(image)]


def _one_per_action(labeled) -> tuple[tuple[dict, str], ...]:
    first: dict[str, dict] = {}
    for row, label in labeled:
        first.setdefault(label, row)
    return tuple((row, label) for label, row in first.items())


def action_labels(rows, *, image_index) -> dict[str, str]:
    animations = _Animations(rows, image_index)
    return {row["prompt_id"]: animations.label_of(row) for row in rows}


def surroundings(current: dict, rows, *, image_index) -> Surroundings:
    animations = _Animations(rows, image_index)
    own = animations.label_of(current)
    image = animations.image_of(current)
    if image is None:
        seeds = seed_family(current, rows, image_index=image_index)[1:]
    else:
        seeds = [video
                 for sibling in seed_family(image, rows, image_index=image_index)
                 for video in animations.videos_of(sibling)
                 if video["prompt_id"] != current["prompt_id"]
                 and animations.label_of(video) == own]
    group = [row for row in animations.group_of(current)
             if row["prompt_id"] != current["prompt_id"] and made_here(row)]
    return Surroundings(
        label=own,
        seeds=tuple(filter(made_here, seeds)),
        configs=() if image is not None else tuple(filter(made_here, config_family(
            current, rows, image_index=image_index)[1:])),
        actions=_one_per_action(
            (row, label) for row, label in ((row, animations.label_of(row)) for row in group)
            if label != own),
        group=tuple(group),
    )


def group_keys(rows, *, image_index, by_seed_family: bool = False) -> dict[str, Hashable]:
    animations = _Animations(rows, image_index)

    def by_its_image(row: dict) -> Hashable:
        return (animations.image_of(row) or row)["prompt_id"]

    def by_its_seed_family(row: dict) -> Hashable:
        image = animations.image_of(row)
        if image is None:
            return (row.get("workflow_name"), gallery.settings_folder_key(row, image_index))
        return (image.get("workflow_name"), gallery.settings_folder_key(image, image_index),
                animations.label_of(row))

    key_of = by_its_seed_family if by_seed_family else by_its_image
    return {row["prompt_id"]: key_of(row) for row in rows if made_here(row)}


def beyond_the_row(current: dict, rows, *, image_index,
                   additions: int = WIDEN_ADDITIONS) -> list[dict]:
    animations = _Animations(rows, image_index)
    around = surroundings(current, rows, image_index=image_index)
    kept = {current["prompt_id"], *(row["prompt_id"] for row in around.seeds)}
    model = gallery.folder_key_at_level(current, "model", image_index)
    lora = gallery.folder_key_at_level(current, "lora", image_index)
    image = animations.image_of(current)
    if image is None:
        candidates = [row for row in _others(current, rows)
                      if gallery.folder_key_at_level(row, "model", image_index) == model]
    else:
        candidates = [row for row in rows
                      if gallery.media_type_of_row(row) == MediaType.VIDEO
                      and animations.label_of(row) == around.label]
    subject = content_stems(image or current)
    ranked = sorted(
        (
            (gallery.folder_key_at_level(row, "model", image_index) != model,
             gallery.folder_key_at_level(row, "lora", image_index) != lora,
             -_likeness(subject, content_stems(animations.image_of(row) or row)),
             row["prompt_id"],
             row)
            for row in candidates if row["prompt_id"] not in kept and made_here(row)
        ),
        key=lambda scored: scored[:4],
    )
    return [scored[-1] for scored in ranked[:max(additions, 0)]]


def one_per_stretch(rows, *, image_index) -> list[dict]:
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


_MADE_HERE, _FILED, _GROUPS = "made here", "filed", "groups"


class SlideGroups:
    def __init__(self, *, library: Callable[[], object], sources) -> None:
        self._library = library
        self._record_group_of = sources.record_group_of
        self.learn = sources.learn_weights
        self._read = None
        self._found: dict = {}

    def _kept(self, key, work_out):
        reading = self._library()
        if reading is not self._read:
            self._read, self._found = reading, {}
        if key not in self._found:
            self._found[key] = work_out()
        return self._found[key]

    def __call__(self, slide, by_seed_family: bool, *, shape: str) -> Hashable | None:
        library = self._library()
        made_here = self._kept((_GROUPS, shape, by_seed_family), lambda: group_keys(
            library.on_the_map(shape), image_index=library.image_index,
            by_seed_family=by_seed_family))
        if slide.prompt_id in made_here:
            return (_MADE_HERE, made_here[slide.prompt_id])
        filed = (self._record_group_of(slide.path, by_seed_family)
                 if self._record_group_of is not None else None)
        return (_FILED, filed) if filed is not None else None
