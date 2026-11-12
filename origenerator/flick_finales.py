from __future__ import annotations

import logging

from origenerator import combine_runs, gallery
from origenerator.action_settings import VIDEO
from origenerator.action_vocabulary import Vocabulary, vocabulary
from origenerator.animation_names import Animation, animation_of, image_button_of, named
from origenerator.combine_runs import CombineRun
from origenerator.content import genau_flick_word, load_content
from origenerator.generation_state import GenerationStatus
from origenerator.inflight import drop_runs
from origenerator.media import MediaType
from origenerator.workflows.duration import lasting

SWITCHED_ON = False
SECONDS = 15
FINALE_COLUMN = "finale_id"

logger = logging.getLogger(__name__)


def finale_checkbox() -> str:
    return str(load_content().get("genau_finale_checkbox") or "")


def _owed_finales(rows: list[dict]) -> list[dict]:
    failed = {row["prompt_id"] for row in rows if row.get("status") == GenerationStatus.ERROR}
    return [row for row in rows if row.get("genau_exported_at")
            and (not row.get(FINALE_COLUMN) or row[FINALE_COLUMN] in failed)]


def queue_finales(jobs, db, rows: list[dict]) -> int:
    words, box = vocabulary(MediaType.VIDEO), finale_checkbox()
    if box not in words.checkboxes:
        logger.warning("No video is made for any Genau %s: the overlay's "
                       "genau_finale_checkbox names none of the video checkboxes", genau_flick_word())
        return 0
    images = [row for row in rows if gallery.media_type_of_row(row) == MediaType.IMAGE]
    videos = combine_runs.rebuildable_videos(rows)
    index = gallery.image_config_index_of(rows)
    queued = 0
    for flick in _owed_finales(rows):
        finale = _finale_of(flick, images, videos, words, box)
        if finale is None:
            continue
        name, run = finale
        key = gallery.folder_key_for(run.workflow.name, run.params, index, run.workflow.version)
        prompt_id = combine_runs.launch(jobs, db, key, run, name=name)
        if prompt_id:
            db.fill_in(FINALE_COLUMN, {flick["prompt_id"]: prompt_id})
            queued += 1
    return queued


def _finale_of(flick: dict, images: list[dict], videos: list[dict], words: Vocabulary,
               box: str) -> tuple[str, CombineRun] | None:
    animation = named(animation_of(flick, words), words)
    if not animation.action:
        return None
    checked = tuple(each for each in words.checkboxes if each in (*animation.checked, box))
    name = Animation(animation.action, checked).name
    start = gallery.source_image_of(flick, images)
    reference = gallery.input_image_reference(start)
    state = image_button_of(start)
    if (reference is None
            or animation.action not in combine_runs.offered_actions(videos, VIDEO, checked, state)):
        return None
    run = combine_runs.as_action(reference, name, VIDEO, state, videos)
    if run is None:
        return None
    return name, run._replace(params=lasting(run.params, run.workflow, SECONDS))


def drop_finales_in_flight(db, client) -> int:
    rows = db.list_generations()
    finale_of = {row[FINALE_COLUMN]: row["prompt_id"] for row in rows if row.get(FINALE_COLUMN)}
    dropped = drop_runs(db, client, [row for row in rows if row["prompt_id"] in finale_of],
                        f"video for a Genau {genau_flick_word()}")
    db.fill_in(FINALE_COLUMN, {finale_of[prompt_id]: None for prompt_id in dropped})
    return len(dropped)
