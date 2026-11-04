# ruff: noqa: PLC0415
# Imports below are late on purpose: origenerator.app imports this file before QT_SCALE_FACTOR is set and before the voice runtimes load.
from __future__ import annotations

from typing import TYPE_CHECKING

from origenerator.output_places import OutputFolders

if TYPE_CHECKING:
    from origenerator.boot_passes import Library


def copy_the_records_for_backup(library: Library):
    from origenerator import config
    from origenerator.records_copy import copy_the_records

    return len(copy_the_records(
        library.db.path, config.LIBRARY_OVERLAY_PATH, config.RECORDS_DIR))


def reconnect_to_running_generations(library: Library):
    from origenerator.inflight import reconcile_in_flight

    reconcile_in_flight(library.db, library.client,
                        OutputFolders(library.places, library.thumb_dir))


def file_what_comfyui_left(library: Library):
    from origenerator.library_filing import file_what_comfyui_left

    return file_what_comfyui_left(library.places)


def follow_moved_files(library: Library):
    from origenerator.relocate import relocate_moved_outputs

    return relocate_moved_outputs(library.db, library.places)


def put_the_backfill_in_place(library: Library):
    from origenerator import config, enhanced_start_backfill, evolver_agreement

    evolver = enhanced_start_backfill.Evolver(
        places=library.places, upscaled_dir=config.EVOLVER_UPSCALED_DIR,
        records_folder=evolver_agreement.records_folder(evolver_agreement.evolver_checkout(),
                                                        config.LIBRARY_ROOT))

    def trash(rows: list[dict]) -> None:
        scrap(library, rows)

    enhanced_start_backfill.cancel_backfill(library.db, library.client)
    folded = enhanced_start_backfill.fold_completed_backfill(
        library.db, library.places, library.thumb_dir, trash=trash)
    enhanced_start_backfill.pay_the_owed_favorites(library.db, evolver)
    return folded


def tend_the_trash(library: Library):
    from origenerator import trash_collection

    return trash_collection.tend_the_trash(library.db, library.places)


def hand_the_remakes_down_again(library: Library):
    from origenerator import enhanced_start_backfill

    return enhanced_start_backfill.hand_the_remakes_down_again(
        library.db, library.places, library.inbox)


def scrap(library: Library, rows: list[dict]) -> int:
    from origenerator import config
    from origenerator.gallery_edits import GalleryEdits
    from origenerator.trash import Trash

    GalleryEdits(library.db, library.places, Trash(config.TRASH_DIR)).delete_rows(rows)
    return len(rows)
