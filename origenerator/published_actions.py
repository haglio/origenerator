from __future__ import annotations

import json

from origenerator.animation_names import item_actions_named
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import image_actions_row, start_images_among
from origenerator.item_actions import ItemActions, actions_of, combined_actions
from origenerator.media import MediaType

PUBLISHED = "combined_labels"


def published(video: dict, holder: dict) -> tuple[str, ...]:
    image, own = actions_of(holder, MediaType.IMAGE), actions_of(video, MediaType.VIDEO)
    return tuple(dict.fromkeys((*combined_actions(image, own), *image.checked, *own.checked)))


def publish(db) -> int:
    rows = db.list_generations()
    start_image_of = start_images_among(
        [row for row in rows if media_type_of_row(row) == MediaType.IMAGE])
    changed = {}
    for video in rows:
        if media_type_of_row(video) != MediaType.VIDEO:
            continue
        said = json.dumps(list(published(video, image_actions_row(video, start_image_of(video)))))
        if video.get(PUBLISHED) != said:
            changed[video["prompt_id"]] = said
    if changed:
        db.fill_in(PUBLISHED, changed)
    return len(changed)


def set_actions(db, prompt_id: str, side: str, item_actions: ItemActions | None) -> None:
    db.set_actions(prompt_id, side, item_actions)
    publish(db)


def give_the_launch_its_actions(db, prompt_id: str, name: str = "", checked=()) -> None:
    item_actions = item_actions_named(name) if name else ItemActions((), tuple(checked))
    if item_actions.actions or item_actions.checked:
        set_actions(db, prompt_id, MediaType.VIDEO, item_actions)
