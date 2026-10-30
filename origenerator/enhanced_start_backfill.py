from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from origenerator import gallery
from origenerator.base_backfill import BATCH_MINUTES, queue_within_budget
from origenerator.db_generations import was_kept, was_sent
from origenerator.evolver_upscales import EvolverUpscales
from origenerator.export_lane import KINO
from origenerator.file_numbers import NUMBERED
from origenerator.funscript import funscript_path_for
from origenerator.generation_config import filled_params
from origenerator.generation_state import GenerationSource, source_of
from origenerator.inflight import drop_in_flight
from origenerator.media import MediaType, media_type_from_filename
from origenerator.output_places import OutputPlaces
from origenerator.outside_videos import mark_a_favorite
from origenerator.record_fold import fold_record_into
from origenerator.thumbnail import animated_thumbnail_path
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
    places: OutputPlaces
    upscaled_dir: Path
    records_folder: Path | None

    @cached_property
    def _kino_copies(self) -> EvolverUpscales:
        return EvolverUpscales.scan(self.upscaled_dir, KINO.source)

    def kino_copy_of(self, row: dict) -> Path | None:
        video = gallery.video_file_of(row, self.places)
        return self._kino_copies.upscale_of(video) if video is not None else None

    def mark_a_fun_time_favorite(self, row: dict) -> bool:
        copy = self.kino_copy_of(row)
        return copy is not None and self.records_folder is not None and mark_a_favorite(
            copy, self.records_folder)


def fold_completed_backfill(db, places: OutputPlaces, thumb_dir: Path, *, trash) -> int:
    folded = 0
    for row in db.list_generations():
        old = (_old_video_of_a_finished_run(db, row, trash)
               if source_of(row) == GenerationSource.BACKFILL else _old_video_left_beside(db, row))
        if old is not None and _remake_in_place(db, row, old, places, thumb_dir, trash):
            folded += 1
    return folded


def _old_video_of_a_finished_run(db, run: dict, trash) -> dict | None:
    if gallery.is_in_progress(run):
        return None
    if not gallery.produced_output(run):
        db.delete_generation(run["prompt_id"])
        return None
    if not run.get("backfill_of"):
        return None
    old = db.get_generation(run["backfill_of"])
    if old is None:
        trash([run])
    return old


def _old_video_left_beside(db, row: dict) -> dict | None:
    old = db.get_generation(row["backfill_of"]) if row.get("backfill_of") else None
    return old if old is not None and source_of(old) == GenerationSource.REPLACED else None


def pay_the_owed_favorites(db, evolver: Evolver) -> int:
    paid = [row["prompt_id"] for row in db.list_generations()
            if row.get("fun_time_favorite_owed") and evolver.mark_a_fun_time_favorite(row)]
    for prompt_id in paid:
        db.pay_a_fun_time_favorite(prompt_id)
    return len(paid)


def cancel_backfill(db, client) -> int:
    return drop_in_flight(db, client, GenerationSource.BACKFILL, "backfill run")


def _remake_in_place(db, remade: dict, old: dict, places: OutputPlaces, thumb_dir: Path,
                     trash) -> bool:
    if gallery.video_file_of(remade, places) is None:
        logger.warning("%s has no video on disk to remake %s with; both wait for the next "
                       "launch", remade["prompt_id"], old["prompt_id"])
        return False
    names = _names_of(remade), _names_of(old)
    if None in names:
        logger.warning("%s or %s is filed under a name with no number; both wait",
                       remade["prompt_id"], old["prompt_id"])
        return False
    renamed = _renamed(*names)
    try:
        if gallery.video_file_of(old, places) is not None:
            _send_the_old_version_to_the_trash(db, old, thumb_dir, trash)
        _move_animated_preview(thumb_dir, remade["prompt_id"], old["prompt_id"])
        for path in _files_ending_with_the_video(remade, places):
            path.replace(path.with_name(renamed(path.name)))
    except OSError:
        logger.warning("Could not put %s's files under %s's names; both wait for the next launch",
                       remade["prompt_id"], old["prompt_id"], exc_info=True)
        return False
    fold_record_into(db, db.list_generations(), remade, old)
    db.take_the_content_of(old["prompt_id"], {
        **remade, "output_files": json.dumps(
            [{**entry, "filename": renamed(entry.get("filename") or "")}
             for entry in gallery.row_output_files(remade)])})
    db.set_source(old["prompt_id"], GenerationSource.GENERATED)
    db.mark_remade(old["prompt_id"])
    db.delete_generation(remade["prompt_id"])
    db.forget_item_numbers([remade["prompt_id"]])
    return True


def _names_of(row: dict) -> str | None:
    for entry in gallery.row_output_files(row):
        if match := NUMBERED.match(entry.get("filename") or ""):
            return f"{match['stem']}_{match['counter']}"
    return None


def _renamed(remade_name: str, old_name: str):
    def renamed(name: str) -> str:
        return old_name + name[len(remade_name):] if name.startswith(remade_name) else name
    return renamed


def _files_ending_with_the_video(row: dict, places: OutputPlaces) -> list[Path]:
    files = gallery.output_disk_files(row, places)
    videos = [path for path in files if media_type_from_filename(path.name) == MediaType.VIDEO]
    scripts = [script for script in (funscript_path_for(video, places=places) for video in videos)
               if script.exists()]
    return scripts + [path for path in files if path not in videos] + videos


_LEFT_WITH_THE_VIDEO = {
    "starred": 0, "shielded": 0, "fun_time_favorite_owed": 0, "remade_at": None,
    "backfill_of": None, "genau_requested_at": None, "evolver_exported_at": None,
    "evolver_unsent_at": None, "genau_exported_at": None, "genau_unsent_at": None,
}


def _send_the_old_version_to_the_trash(db, old: dict, thumb_dir: Path, trash) -> None:
    version = {**{column: value for column, value in old.items() if column != "id"},
               **_LEFT_WITH_THE_VIDEO, "prompt_id": str(uuid.uuid4()),
               "source": GenerationSource.GENERATED, "old_version_of": old["prompt_id"]}
    db.insert_rows([version])
    try:
        trash([db.get_generation(version["prompt_id"])])
    except OSError:
        db.delete_generation(version["prompt_id"])
        raise
    _move_animated_preview(thumb_dir, old["prompt_id"], version["prompt_id"])


def _move_animated_preview(thumb_dir: Path, shown_for: str, now_for: str) -> None:
    preview = animated_thumbnail_path(thumb_dir, shown_for)
    if preview.exists():
        preview.replace(animated_thumbnail_path(thumb_dir, now_for))


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
