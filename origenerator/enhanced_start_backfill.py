from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from origenerator import gallery
from origenerator.base_backfill import BATCH_MINUTES, queue_within_budget
from origenerator.db_generations import was_kept, was_sent
from origenerator.evolver_export import EvolverInbox
from origenerator.evolver_upscales import EvolverUpscales
from origenerator.export_lane import EXPORT_LANES, EXPORT_LANES_BY_KEY, KINO
from origenerator.generation_config import filled_params
from origenerator.generation_state import GenerationSource, source_of
from origenerator.inflight import drop_in_flight
from origenerator.media import MediaType, media_type_from_filename
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import mark_a_favorite, record_of
from origenerator.record_fold import fold_record_into, lanes_owed
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


def videos_to_backfill(rows: list[dict]) -> list[tuple[dict, dict]]:
    images = {row["prompt_id"]: row for row in rows
              if gallery.media_type_of_row(row) == MediaType.IMAGE}
    start_frames = gallery.build_image_config_index(list(images.values()))
    on_their_way = {row.get("backfill_of") for row in rows
                    if source_of(row) == GenerationSource.BACKFILL}
    names = Counter(name for row in rows for name in _video_names(row))
    found = []
    for video in rows:
        if (not _a_kept_video_it_can_make_again(video) or video["prompt_id"] in on_their_way
                or (was_sent(video) and any(names[name] > 1 for name in _video_names(video)))):
            continue
        image = images.get(gallery.source_image_id_in(video, start_frames))
        if image is not None and _started_from_plain(video, image):
            found.append((video, image))
    return found


def queue_backfill(rows: list[dict], launch, *, enhance,
                   budget_minutes: float = BATCH_MINUTES) -> int:
    found = videos_to_backfill(rows)
    plain = {image["prompt_id"]: image for _video, image in found
             if not gallery.is_enhanced_row(image)}
    enhanced = enhance(gallery.rows_awaiting_enhancement(list(plain.values()), rows))
    starts = {video["prompt_id"]: image for video, image in found
              if gallery.is_enhanced_row(image)}

    def launch_one(video: dict) -> bool:
        params = backfill_params_for(video, starts[video["prompt_id"]])
        return launch(video, WORKFLOW_REGISTRY[video["workflow_name"]], params) is not None

    queued, spent = queue_within_budget(
        rows, [video for video, _image in found if video["prompt_id"] in starts],
        launch_one, budget_minutes=budget_minutes)
    if queued:
        logger.info("Queued %d video(s) of the enhanced-start backfill (~%d min) to run "
                    "while the app is closed", queued, round(spent / 60))
    return enhanced + queued


@dataclass
class Evolver:
    inbox: EvolverInbox
    places: OutputPlaces
    upscaled_dir: Path
    records_folder: Path | None

    @cached_property
    def _kino_copies(self) -> EvolverUpscales:
        return EvolverUpscales.scan(self.upscaled_dir, KINO.source)

    def _video_of(self, row: dict) -> Path | None:
        shown = gallery.resolve_preview(row, self.places)
        return shown[0] if shown is not None and shown[1] == MediaType.VIDEO else None

    def kino_copy_of(self, row: dict) -> Path | None:
        video = self._video_of(row)
        return self._kino_copies.upscale_of(video) if video is not None else None

    def is_a_fun_time_favorite(self, row: dict) -> bool:
        return self._on_the_kino_copy(row, lambda copy, folder: record_of(copy, folder).favorite)

    def mark_a_fun_time_favorite(self, row: dict) -> bool:
        return self._on_the_kino_copy(row, mark_a_favorite)

    def _on_the_kino_copy(self, row: dict, answer: Callable[[Path, Path], bool]) -> bool:
        copy = self.kino_copy_of(row)
        return copy is not None and self.records_folder is not None and answer(
            copy, self.records_folder)

    def still_holds(self, old: dict, backfilled: dict | None) -> bool:
        video = self._video_of(backfilled) if backfilled is not None else None
        waiting = video is not None and any(self.inbox.holds(video, lane.source)
                                            for lane in EXPORT_LANES if old.get(lane.unsent_flag))
        return waiting or self.kino_copy_of(old) is not None


def fold_completed_backfill(db, evolver: Evolver, *, trash) -> int:
    folded = 0
    for run in db.list_generations():
        if source_of(run) != GenerationSource.BACKFILL or gallery.is_in_progress(run):
            continue
        if not gallery.produced_output(run):
            db.delete_generation(run["prompt_id"])
        elif not run.get("backfill_of"):
            continue
        elif (old := db.get_generation(run["backfill_of"])) is None:
            trash([run])
        elif _put_in_place(db, run, old, evolver):
            folded += 1
    return folded


def pay_the_owed_favorites(db, evolver: Evolver) -> int:
    paid = [row["prompt_id"] for row in db.list_generations()
            if row.get("fun_time_favorite_owed") and evolver.mark_a_fun_time_favorite(row)]
    for prompt_id in paid:
        db.pay_a_fun_time_favorite(prompt_id)
    return len(paid)


def cancel_backfill(db, client) -> int:
    return drop_in_flight(db, client, GenerationSource.BACKFILL, "backfill run")


def trash_what_the_backfill_replaced(db, evolver: Evolver, *, trash) -> int:
    backfilled = {row["backfill_of"]: row for row in db.list_generations()
                  if row.get("backfill_of")}
    let_go = [{**old, "source": GenerationSource.GENERATED} for old in db.replaced_generations()
              if not evolver.still_holds(old, backfilled.get(old["prompt_id"]))]
    trash(let_go)
    return len(let_go)


def _put_in_place(db, backfilled: dict, old: dict, evolver: Evolver) -> bool:
    try:
        for lane in lanes_owed(old, backfilled):
            EXPORT_LANES_BY_KEY[lane].send_video_of(backfilled, db=db, inbox=evolver.inbox,
                                                    places=evolver.places)
    except Exception:
        logger.warning("Could not send %s where %s had gone; both wait for the next launch",
                       backfilled["prompt_id"], old["prompt_id"], exc_info=True)
        return False
    _carry_over(db, old, backfilled, evolver)
    _take_back(db, old)
    db.set_source(backfilled["prompt_id"], GenerationSource.GENERATED)
    return True


def _carry_over(db, old: dict, backfilled: dict, evolver: Evolver) -> None:
    fold_record_into(db, db.list_generations(), old, backfilled)
    db.set_settings_source(backfilled["prompt_id"], category=old.get("act"),
                           video_prompt_id=old.get("source_video"))
    if old.get("genau_requested_at"):
        db.mark_genau_requested(backfilled["prompt_id"])
    if evolver.is_a_fun_time_favorite(old):
        db.owe_a_fun_time_favorite(backfilled["prompt_id"])


def _take_back(db, old: dict) -> None:
    for lane in EXPORT_LANES:
        if old.get(lane.flag):
            lane.unmark(db, old["prompt_id"])
    db.set_generation_favorite(old["prompt_id"], False)
    db.set_source(old["prompt_id"], GenerationSource.REPLACED)


def backfill_params_for(video: dict, image: dict) -> dict:
    params = filled_params(video, WORKFLOW_REGISTRY[video["workflow_name"]])
    params["input_image"] = gallery.enhanced_version_of(params["input_image"], image)
    return params


def _a_kept_video_it_can_make_again(row: dict) -> bool:
    return (gallery.media_type_of_row(row) == MediaType.VIDEO and was_kept(row)
            and _in_the_gallery(row) and gallery.rerollable(row))


def _video_names(row: dict) -> set[str]:
    return {Path(name).stem for file in gallery.row_output_files(row)
            if media_type_from_filename(name := file.get("filename") or "") == MediaType.VIDEO}


def _in_the_gallery(row: dict) -> bool:
    if source_of(row) == GenerationSource.EXPERIMENT:
        return row.get("experiment_verdict") == "up"
    return source_of(row) in (GenerationSource.GENERATED, GenerationSource.IMPORTED)


def _started_from_plain(video: dict, image: dict) -> bool:
    start = gallery.parse_params(video.get("params_json")).get("input_image")
    return (not gallery.is_enhanced_row(image)
            or gallery.enhanced_version_of(start, image) is not None)
