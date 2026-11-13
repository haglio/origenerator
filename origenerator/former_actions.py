from __future__ import annotations

from app_support.gallery_rows import source_of
from funestra.video_families import normalized_text

from origenerator.action_vocabulary import names_in, vocabulary
from origenerator.content import load_content
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import start_images_among
from origenerator.generation_state import GenerationSource
from origenerator.item_actions import ItemActions, columns, has_actions
from origenerator.media import MediaType

_SIDES = (MediaType.IMAGE, MediaType.VIDEO)


def _read(rows, side: str, said, content) -> dict[str, ItemActions]:
    named = vocabulary(side, content)
    return {row["prompt_id"]: item_actions for row in rows
            if not has_actions(row, side) and (earlier := said(row))
            and (item_actions := named.read_as(earlier)) is not None}


def _a_video_made_here(row: dict) -> str | None:
    if media_type_of_row(row) != MediaType.VIDEO or source_of(row) == GenerationSource.OUTSIDE:
        return None
    return row.get("action")


def _site_words(content: dict) -> dict[str, dict[str, ItemActions]]:
    table = content.get("site_words")
    return {normalized_text(word): {side: ItemActions(*(names_in(means.get(key)) for key in columns(side)))
                                    for side in _SIDES}
            for word, means in (table.items() if isinstance(table, dict) else ())
            if isinstance(word, str) and isinstance(means, dict)}


def _meanings(site_action: str, table) -> list[dict[str, ItemActions]]:
    found = []
    for part in (part.strip() for part in site_action.split(",")):
        whole = table.get(normalized_text(part))
        first, _, rest = part.partition(" ")
        if whole is not None:
            found.append(whole)
        elif (prefix := table.get(normalized_text(first))) is not None and (
                after := table.get(normalized_text(rest))) is not None:
            found.extend((prefix, after))
    return found


def actions_of_site_words(site_action: str, content: dict) -> dict[str, ItemActions]:
    meanings = _meanings(site_action, _site_words(content))
    together = {side: ItemActions(tuple(dict.fromkeys(a for m in meanings for a in m[side].actions)),
                             tuple(dict.fromkeys(c for m in meanings for c in m[side].checked)))
                for side in _SIDES}
    return {side: item_actions for side, item_actions in together.items() if item_actions.actions or item_actions.checked}


def _from_other_sites(rows, content, images: dict[str, ItemActions]) -> dict[str, dict[str, ItemActions]]:
    start_image_of = start_images_among(
        [row for row in rows if media_type_of_row(row) == MediaType.IMAGE])
    found: dict[str, dict[str, ItemActions]] = {MediaType.IMAGE: {}, MediaType.VIDEO: {}}
    for video in rows:
        if (source_of(video) != GenerationSource.OUTSIDE or has_actions(video, MediaType.VIDEO)
                or media_type_of_row(video) != MediaType.VIDEO or not video.get("action")):
            continue
        item_actions = actions_of_site_words(video["action"], content)
        if MediaType.VIDEO in item_actions:
            found[MediaType.VIDEO][video["prompt_id"]] = item_actions[MediaType.VIDEO]
        frame = start_image_of(video)
        if (MediaType.IMAGE in item_actions and frame is not None and not has_actions(frame, MediaType.IMAGE)
                and frame["prompt_id"] not in images):
            found[MediaType.IMAGE].setdefault(frame["prompt_id"], item_actions[MediaType.IMAGE])
    return found


def fill_in_actions(db, content: dict | None = None) -> int:
    if content is None:
        content = load_content()
    rows = db.list_generations()
    images = _read(rows, MediaType.IMAGE, lambda row: row.get("image_state"), content)
    videos = _read(rows, MediaType.VIDEO, _a_video_made_here, content)
    sites = _from_other_sites(rows, content, images)
    found = {MediaType.IMAGE: {**images, **sites[MediaType.IMAGE]},
             MediaType.VIDEO: {**videos, **sites[MediaType.VIDEO]}}
    for side, actions_by_id in found.items():
        if actions_by_id:
            db.set_many_actions(side, actions_by_id)
    return sum(map(len, found.values()))
