from __future__ import annotations

import json

from origenerator.action_labels import Labels, combined_actions, labels_of
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import image_labels_row, start_images_among
from origenerator.media import MediaType

PUBLISHED = "combined_labels"


def published(video: dict, holder: dict) -> tuple[str, ...]:
    image, own = labels_of(holder, MediaType.IMAGE), labels_of(video, MediaType.VIDEO)
    return tuple(dict.fromkeys((*combined_actions(image, own), *image.checked, *own.checked)))


def publish(db) -> int:
    rows = db.list_generations()
    start_image_of = start_images_among(
        [row for row in rows if media_type_of_row(row) == MediaType.IMAGE])
    changed = {}
    for video in rows:
        if media_type_of_row(video) != MediaType.VIDEO:
            continue
        said = json.dumps(list(published(video, image_labels_row(video, start_image_of(video)))))
        if video.get(PUBLISHED) != said:
            changed[video["prompt_id"]] = said
    if changed:
        db.fill_in(PUBLISHED, changed)
    return len(changed)


def set_labels(db, prompt_id: str, side: str, labels: Labels | None) -> None:
    db.set_labels(prompt_id, side, labels)
    publish(db)
