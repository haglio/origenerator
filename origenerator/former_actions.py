from __future__ import annotations

from funestra.video_families import normalized_text

from origenerator.action_labels import Labels, columns, is_labeled
from origenerator.action_vocabulary import names_in, vocabulary
from origenerator.content import load_content
from origenerator.gallery import media_type_of_row
from origenerator.gallery.source_image import start_images_among
from origenerator.generation_state import GenerationSource, source_of
from origenerator.media import MediaType

_SIDES = (MediaType.IMAGE, MediaType.VIDEO)


def _read(rows, side: str, said, content) -> dict[str, Labels]:
    named = vocabulary(side, content)
    return {row["prompt_id"]: labels for row in rows
            if not is_labeled(row, side) and (earlier := said(row))
            and (labels := named.read_as(earlier)) is not None}


def _a_video_made_here(row: dict) -> str | None:
    if media_type_of_row(row) != MediaType.VIDEO or source_of(row) == GenerationSource.OUTSIDE:
        return None
    return row.get("action")


def _site_words(content: dict) -> dict[str, dict[str, Labels]]:
    table = content.get("site_words")
    return {normalized_text(word): {side: Labels(*(names_in(means.get(key)) for key in columns(side)))
                                    for side in _SIDES}
            for word, means in (table.items() if isinstance(table, dict) else ())
            if isinstance(word, str) and isinstance(means, dict)}


def _meanings(said: str, table) -> list[dict[str, Labels]]:
    found = []
    for part in (part.strip() for part in said.split(",")):
        whole = table.get(normalized_text(part))
        first, _, rest = part.partition(" ")
        if whole is not None:
            found.append(whole)
        elif (prefix := table.get(normalized_text(first))) is not None and (
                after := table.get(normalized_text(rest))) is not None:
            found.extend((prefix, after))
    return found


def site_labels(said: str, content: dict) -> dict[str, Labels]:
    meanings = _meanings(said, _site_words(content))
    together = {side: Labels(tuple(dict.fromkeys(a for m in meanings for a in m[side].actions)),
                             tuple(dict.fromkeys(c for m in meanings for c in m[side].checked)))
                for side in _SIDES}
    return {side: labels for side, labels in together.items() if labels.actions or labels.checked}


def _from_other_sites(rows, content, images: dict[str, Labels]) -> dict[str, dict[str, Labels]]:
    start_image_of = start_images_among(
        [row for row in rows if media_type_of_row(row) == MediaType.IMAGE])
    found: dict[str, dict[str, Labels]] = {MediaType.IMAGE: {}, MediaType.VIDEO: {}}
    for video in rows:
        if (source_of(video) != GenerationSource.OUTSIDE or is_labeled(video, MediaType.VIDEO)
                or media_type_of_row(video) != MediaType.VIDEO or not video.get("action")):
            continue
        labels = site_labels(video["action"], content)
        if MediaType.VIDEO in labels:
            found[MediaType.VIDEO][video["prompt_id"]] = labels[MediaType.VIDEO]
        frame = start_image_of(video)
        if (MediaType.IMAGE in labels and frame is not None and not is_labeled(frame, MediaType.IMAGE)
                and frame["prompt_id"] not in images):
            found[MediaType.IMAGE].setdefault(frame["prompt_id"], labels[MediaType.IMAGE])
    return found


def fill_in_labels(db, content: dict | None = None) -> int:
    if content is None:
        content = load_content()
    rows = db.list_generations()
    images = _read(rows, MediaType.IMAGE, lambda row: row.get("image_state"), content)
    videos = _read(rows, MediaType.VIDEO, _a_video_made_here, content)
    sites = _from_other_sites(rows, content, images)
    found = {MediaType.IMAGE: {**images, **sites[MediaType.IMAGE]},
             MediaType.VIDEO: {**videos, **sites[MediaType.VIDEO]}}
    for side, labeled in found.items():
        if labeled:
            db.set_many_labels(side, labeled)
    return sum(map(len, found.values()))
