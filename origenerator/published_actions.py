from __future__ import annotations

import json

from origenerator.animation_names import item_actions_named
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import image_actions_row, start_images_among
from origenerator.item_actions import ItemActions, actions_if_any, actions_of, combined_actions
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


def combined_from(rows: list[dict], prompt_id: str) -> list[str]:
    found, sources = [], {prompt_id}
    while sources:
        made = [row["prompt_id"] for row in rows
                if row.get("source_video") in sources and row["prompt_id"] not in found]
        found += made
        sources = set(made)
    return found


Replaced = dict[str, ItemActions | None]


def set_actions(db, prompt_id: str, side: str, item_actions: ItemActions | None) -> Replaced:
    rows = db.list_generations()
    given = [prompt_id, *(combined_from(rows, prompt_id) if side == MediaType.VIDEO else ())]
    row_of = {row["prompt_id"]: row for row in rows}
    replaced = {each: actions_if_any(row_of.get(each) or {}, side) for each in given}
    for each in given:
        db.set_actions(each, side, item_actions)
    publish(db)
    return replaced


def put_back(db, side: str, replaced: Replaced) -> None:
    for prompt_id, item_actions in replaced.items():
        db.set_actions(prompt_id, side, item_actions)
    publish(db)


def _source_videos_actions(db, prompt_id: str) -> ItemActions:
    source = (db.get_generation(prompt_id) or {}).get("source_video")
    return actions_of(db.get_generation(source) or {}, MediaType.VIDEO) if source else ItemActions()


def give_the_launch_its_actions(db, prompt_id: str, name: str = "", checked=()) -> None:
    item_actions = (item_actions_named(name) if name
                    else ItemActions((), tuple(checked)) if checked
                    else _source_videos_actions(db, prompt_id))
    if item_actions.actions or item_actions.checked:
        set_actions(db, prompt_id, MediaType.VIDEO, item_actions)
