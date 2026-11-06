# ruff: noqa: PLC0415
# Imports below are late on purpose: origenerator.app imports this file before QT_SCALE_FACTOR is set and before the voice runtimes load.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator.output_places import OutputPlaces
from origenerator.passes_on_the_files import (
    copy_the_records_for_backup,
    file_what_comfyui_left,
    follow_moved_files,
    hand_the_remakes_down_again,
    put_the_backfill_in_place,
    reconnect_to_running_generations,
    scrap,
    tend_the_trash,
)


@dataclass(frozen=True)
class Library:
    db: object
    client: object
    places: OutputPlaces
    thumb_dir: Path
    log_dir: Path
    inbox: object


@dataclass(frozen=True)
class BootPass:
    status: str | None
    run: Callable[[Library], object]
    failure: str
    counted: str | None = None


def _import_new_files(library: Library):
    from origenerator.importer import import_comfyui_output

    return import_comfyui_output(library.places, library.db, library.thumb_dir)


def _tidy_video_previews(library: Library):
    from origenerator.importer import (
        first_frames_filed_apart_from_their_videos,
        merge_video_sidecar_rows,
    )

    merged = merge_video_sidecar_rows(library.db)
    return merged + scrap(library, first_frames_filed_apart_from_their_videos(
        library.db.list_generations()))


def _merge_soundless_copies(library: Library):
    from origenerator.export_lane import EXPORT_LANES_BY_KEY
    from origenerator.importer import (
        fold_sound_versions_into_their_videos,
        merge_soundless_copy_rows,
    )

    def send_down(video: dict, lane_key: str) -> None:
        EXPORT_LANES_BY_KEY[lane_key].send_video_of(
            video, db=library.db, inbox=library.inbox, places=library.places)

    return (merge_soundless_copy_rows(library.db, send_down=send_down)
            + fold_sound_versions_into_their_videos(library.db))


def _backfill_workflow_labels(library: Library):
    from origenerator.importer import (
        backfill_import_workflows,
        refile_enhancements_another_workflow_made,
    )

    return (backfill_import_workflows(library.db)
            + refile_enhancements_another_workflow_made(library.db))


def _backfill_import_params(library: Library):
    from origenerator.importer import backfill_import_params

    return backfill_import_params(library.db, library.places)


def _backfill_imported_video_seeds(library: Library):
    from origenerator.importer import backfill_imported_video_seeds

    return backfill_imported_video_seeds(library.db)


def _fold_enhancements(library: Library):
    from origenerator import config
    from origenerator.gallery import enhancements_of_images_gone, fold_completed_enhancements

    fold_completed_enhancements(library.db)
    return scrap(library, enhancements_of_images_gone(library.db.list_generations(),
                                                       places=library.places,
                                                       input_dir=config.COMFYUI_INPUT_DIR))


def _disown_foreign_runs(library: Library):
    from origenerator.gallery import disown_foreign_runs

    return disown_foreign_runs(library.db)


def _repair_thumbnails(library: Library):
    from origenerator.importer import backfill_shared_thumbnails

    return backfill_shared_thumbnails(library.db, library.places, library.thumb_dir)


def _recover_generation_times(library: Library):
    from origenerator.log_backfill import backfill_durations_from_logs

    return backfill_durations_from_logs(
        library.db, sorted(library.log_dir.glob("comfyui*.log")))


def _record_workflow_versions(library: Library):
    from origenerator.provenance import stamp_unstamped

    return stamp_unstamped(library.db)


def _record_shapes(library: Library):
    from origenerator.item_shape import record_shapes

    return record_shapes(library.db)


def _read_actions_off_earlier_answers(library: Library):
    from origenerator.former_actions import fill_in_labels

    return fill_in_labels(library.db)


def _publish_labels(library: Library):
    from origenerator.published_labels import publish

    return publish(library.db)


def _reconcile_favorites(library: Library):
    from origenerator.favorite_reconcile import reconcile_favorites

    reconcile_favorites(library.db)


MAINTENANCE = (
    BootPass("Backing up the records...", copy_the_records_for_backup,
             counted="Copied %d record file(s) for backup",
             failure="Copying the records for backup failed: %s"),
    BootPass("Reconnecting to running generations...", reconnect_to_running_generations,
             failure="Reconcile of in-flight generations failed: %s"),
    BootPass(None, tend_the_trash,
             counted="Emptied %d item(s) that had been in the Trash for a day",
             failure="Tending the Trash failed: %s"),
    BootPass(None, file_what_comfyui_left,
             counted="Filed %d file(s) ComfyUI had saved into the library",
             failure="Filing what ComfyUI saved failed: %s"),
    BootPass("Finding files that moved...", follow_moved_files,
             counted="Followed %d output file(s) to where they moved",
             failure="Relocating moved output files failed: %s"),
    BootPass(None, put_the_backfill_in_place,
             counted="Put %d backfilled video(s) in the place of the videos they replace",
             failure="Putting backfilled videos in place failed: %s"),
    BootPass(None, hand_the_remakes_down_again,
             counted="Handed %d remade video(s) down the lanes their old ones went down",
             failure="Handing remade videos down their lanes again failed: %s"),
    BootPass("Scanning for new images...", _import_new_files,
             counted="Imported %d existing files from ComfyUI output",
             failure="Import failed: %s"),
    BootPass("Tidying up video previews...", _tidy_video_previews,
             counted="Consolidated %d video sidecar previews and first frames",
             failure="Sidecar consolidation failed: %s"),
    BootPass(None, _merge_soundless_copies,
             counted="Folded %d soundless copies into the videos they came from",
             failure="Folding soundless copies failed: %s"),
    BootPass("Updating workflow labels...", _backfill_workflow_labels,
             counted="Refiled %d imports under the workflow that could have made them",
             failure="Workflow backfill failed: %s"),
    BootPass("Sorting imports by what made them...", _backfill_import_params,
             counted="Read settings off the graph of %d imports",
             failure="Reading settings off imports failed: %s"),
    BootPass(None, _backfill_imported_video_seeds,
             counted="Put back the seed of %d video imports",
             failure="Video-import seed repair failed: %s"),
    BootPass("Folding enhancements into their images...", _fold_enhancements,
             counted="Moved %d enhancement(s) of deleted images to the Trash",
             failure="Enhancement fold failed: %s"),
    BootPass(None, _disown_foreign_runs,
             counted="Disowned a preview's run id on %d enhanced image(s)",
             failure="Disowning foreign enhancement runs failed: %s"),
    BootPass("Repairing thumbnails...", _repair_thumbnails,
             counted="Repaired %d colliding thumbnails",
             failure="Thumbnail repair failed: %s"),
    BootPass("Recovering generation times...", _recover_generation_times,
             counted="Backfilled generation time for %d imports from logs",
             failure="Duration backfill failed: %s"),
    BootPass("Recording workflow versions...", _record_workflow_versions,
             counted="Recorded the workflow version of %d generation(s)",
             failure="Recording workflow versions failed: %s"),
    BootPass(None, _record_shapes,
             counted="Recorded the shape of %d item(s)",
             failure="Recording shapes failed: %s"),
    BootPass(None, _read_actions_off_earlier_answers,
             counted="Read the actions of %d item(s) off their earlier answers",
             failure="Reading actions off earlier answers failed: %s"),
    BootPass(None, _publish_labels,
             counted="Published the labels of %d video(s)",
             failure="Publishing the labels of videos failed: %s"),
    BootPass("Restoring folder bookmarks...", _reconcile_favorites,
             failure="Folder bookmark reconcile failed: %s"),
)

def run_maintenance(library: Library, passes, status, logger) -> None:
    for boot_pass in passes:
        if boot_pass.status is not None:
            status(boot_pass.status)
        try:
            count = boot_pass.run(library)
            if boot_pass.counted and count:
                logger.info(boot_pass.counted, count)
        except Exception as e:
            logger.warning(boot_pass.failure, e)
