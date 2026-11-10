from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator import trash_collection
from origenerator.db_generations import library_paths_in
from origenerator.file_refs import frame_name
from origenerator.gallery import (
    generation_of_file,
    output_disk_files,
    remove_enhance_versions,
    resolve_preview,
    unreviewed_experiments,
)
from origenerator.gallery.output import row_output_files, stem_as_made, with_files_renamed
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import generate_thumbnail
from origenerator.trash import Genau, Kino, TrashedBatch, take_out_of_play
from origenerator.undo_stack import UndoEntry, UndoStack

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GalleryEnvironment:
    release_files: Callable[..., None] | None = None
    cancel_enhancements: Callable[[list[dict]], None] | None = None
    thumb_dir: Path | None = None
    kino: Kino | None = None
    genau: Genau | None = None
    bring_in: Callable[[Path], bool] | None = None
    delete_for_good: Callable[[list[Path]], None] | None = None


@dataclass(frozen=True)
class Pressed:
    video: Path
    already_at: Path | None = None


class GalleryEdits:
    def __init__(self, db, places: OutputPlaces, trash, limit: int = 50,
                 environment: GalleryEnvironment | None = None):
        self._db = db
        self._places = places
        self._trash = trash
        self._environment = environment or GalleryEnvironment()
        self._history = UndoStack(limit)
        self.custom_collections = CustomCollectionActions(db, self._history)

    @property
    def places(self) -> OutputPlaces:
        return self._places

    @property
    def thumb_dir(self) -> Path | None:
        return self._environment.thumb_dir

    def trash_file(self, path, already_at=None) -> None:
        pressed = Pressed(Path(path), Path(already_at) if already_at else None)
        row = self._entry_of(pressed.video) or self._entry_brought_in(pressed.video)
        if row is None:
            logger.warning("%s has no gallery entry, so it was not sent to Trash",
                           pressed.video.name)
            return
        self.trash(row, pressed=pressed)

    def _entry_of(self, video: Path) -> dict | None:
        prompt_id = generation_of_file(video, self._db.list_generations())
        return self._db.get_generation(prompt_id) if prompt_id is not None else None

    def _entry_brought_in(self, video: Path) -> dict | None:
        kino, bring_in = self._environment.kino, self._environment.bring_in
        if kino is None or bring_in is None or not kino.plays(video) or not bring_in(video):
            return None
        return self._entry_of(video)

    def trash(self, row: dict, *, pressed: Pressed | None = None) -> bool:
        if unreviewed_experiments([row]):
            self.reject_experiment(row, pressed=pressed)
            return True
        self.delete_rows([row], pressed=pressed)
        return False

    def delete_rows(self, rows: list[dict], *, pressed: Pressed | None = None) -> None:
        if not rows:
            return
        self._stop_enhancements(rows)
        batches = self._trash_files(rows, pressed=pressed)
        for row, batch in batches:
            self._db.delete_generation(row["prompt_id"])
            self._db.record_trashed(row["prompt_id"], row, batch.record())

        def undo() -> str | None:
            for row, batch in batches:
                self._db.restore_generation(with_files_renamed(row, batch.restore()))
                self._db.forget_trashed(row["prompt_id"])
            return batches[0][0]["prompt_id"]

        self._history.push(UndoEntry(_delete_label(len(rows)), undo,
                              redo=lambda: self.delete_rows(rows, pressed=pressed)))

    def delete_enhance_versions(self, row: dict, filenames: list[str]) -> bool:
        prompt_id = row["prompt_id"]
        updates = remove_enhance_versions(row, filenames)
        if not updates:
            return False
        before = {
            "output_files": row.get("output_files"),
            "original_files": row.get("original_files"),
            "enhance_history": row.get("enhance_history"),
            "thumbnail_path": row.get("thumbnail_path"),
        }
        ((_row, batch),) = self._trash_files([row], names=set(filenames), the_item_stays=True)
        self._db.update_generation(prompt_id, **updates)
        self._redraw_thumbnail(prompt_id)

        def undo() -> str | None:
            self._db.update_generation(prompt_id, **with_files_renamed(before, batch.restore()))
            self._redraw_thumbnail(prompt_id)
            return prompt_id

        self._history.push(UndoEntry(_version_label(len(filenames)), undo, batch.purge,
                              redo=lambda: self.delete_enhance_versions(row, filenames)))
        return True

    def _redraw_thumbnail(self, prompt_id: str) -> None:
        thumb_dir = self._environment.thumb_dir
        if thumb_dir is None:
            return
        row = self._db.get_generation(prompt_id)
        preview = resolve_preview(row, self._places) if row else None
        if preview is None:
            return
        try:
            path = generate_thumbnail(preview[0], preview[1], Path(thumb_dir),
                                      name=prompt_id)
        except Exception:
            logger.exception("Could not redraw the thumbnail for %s", prompt_id)
            return
        self._db.update_generation(prompt_id, thumbnail_path=str(path))

    def _stop_enhancements(self, rows: list[dict]) -> None:
        if self._environment.cancel_enhancements is not None:
            self._environment.cancel_enhancements(rows)

    def _trash_files(self, rows: list[dict], names: set[str] | None = None, *,
                     the_item_stays: bool = False, pressed: Pressed | None = None):
        # Windows cannot move a file the app still holds open, as a preview does its video.
        by_row = self._files_by_row(rows, names)
        in_play = self._in_play(rows, pressed) if names is None else [[] for _row in rows]
        if self._environment.release_files is not None:
            self._environment.release_files(
                [path for files in by_row for path in files]
                + [video for copies in in_play for _place, video in copies],
                the_item_stays=the_item_stays)
        batches = [(row, self._trash.store(files)) for row, files in zip(rows, by_row, strict=True)]
        for (_row, batch), copies in zip(batches, in_play, strict=True):
            batch.out_of_play = [taken for place, video in copies
                                 if (taken := take_out_of_play(place, video)) is not None]
        if pressed is not None and pressed.already_at is not None and batches:
            batches[0][1].out_of_play.append((pressed.video, pressed.already_at))
        return batches

    def _in_play(self, rows: list[dict], pressed: Pressed | None = None) -> list[list[tuple]]:
        kino, genau = self._environment.kino, self._environment.genau
        upscales = kino.upscales() if kino is not None else None
        genau_videos = genau.videos() if genau is not None else []
        pressed_now = [pressed.video] if pressed is not None and pressed.already_at is None else []
        return [[*self._in_kino(row, upscales, pressed_now),
                 *_in_genau(genau, row, genau_videos, pressed_now)]
                for row in rows]

    def _in_kino(self, row: dict, upscales, pressed_now: list[Path]) -> list[tuple]:
        kino = self._environment.kino
        if kino is None:
            return []
        return [(kino, video) for video in dict.fromkeys(filter(kino.plays, [
            *map(Path, library_paths_in(row.get("output_files"))),
            *self._upscale_in_kino(row, upscales), *pressed_now]))]

    def _upscale_in_kino(self, row: dict, upscales) -> list[Path]:
        preview = resolve_preview(row, self._places)
        upscale = upscales.upscale_of(preview[0]) if preview is not None else None
        return [upscale] if upscale is not None else []

    def _files_by_row(self, rows: list[dict],
                      names: set[str] | None = None) -> list[list[Path]]:
        seen: set[str] = set()
        by_row: list[list[Path]] = []
        for row in rows:
            candidates = list(output_disk_files(row, self._places, names))
            thumb = row.get("thumbnail_path")
            if thumb and names is None:
                candidates.append(Path(thumb))
            files = []
            for path in candidates:
                if path.exists() and str(path) not in seen:
                    seen.add(str(path))
                    files.append(path)
            by_row.append(files)
        return by_row

    def restore_deleted(self, prompt_ids) -> str | None:
        records = [record for prompt_id in prompt_ids
                   if (record := self._db.get_trashed(prompt_id)) is not None]
        if self._environment.release_files is not None and records:
            self._environment.release_files(
                [path for record in records
                 for path in TrashedBatch.from_record(record.get("batch") or {}).trashed_files()])
        restored = None
        for record in records:
            restored = trash_collection.restore(self._db, record)
        return restored


    def purge_deleted(self, prompt_ids) -> None:
        waiting = []
        for prompt_id in prompt_ids:
            record = self._db.get_trashed(prompt_id)
            if record is not None:
                waiting += TrashedBatch.from_record(record.get("batch") or {}).waiting_out_of_play()
                trash_collection.purge(self._db, record)
        if waiting and self._environment.delete_for_good is not None:
            self._environment.delete_for_good(waiting)

    def reject_experiment(self, row: dict, *, pressed: Pressed | None = None) -> None:
        prompt_id = row["prompt_id"]
        self._stop_enhancements([row])
        ((_row, batch),) = self._trash_files([row], pressed=pressed)
        self._db.set_experiment_verdict(prompt_id, "down")
        self._db.update_generation(
            prompt_id, output_files=None, thumbnail_path=None
        )

        def undo() -> str | None:
            restored = with_files_renamed(row, batch.restore())
            self._db.set_experiment_verdict(prompt_id, None)
            self._db.update_generation(
                prompt_id,
                output_files=restored.get("output_files"),
                thumbnail_path=restored.get("thumbnail_path"),
            )
            return None

        self._history.push(UndoEntry("Reject experiment", undo, batch.purge,
                              redo=lambda: self.reject_experiment(row, pressed=pressed)))

    def can_undo(self) -> bool:
        return self._history.can_undo()

    def undo_label(self) -> str | None:
        return self._history.undo_label()

    def undo(self) -> str | None:
        return self._history.undo()

    def can_redo(self) -> bool:
        return self._history.can_redo()

    def redo_label(self) -> str | None:
        return self._history.redo_label()

    def redo(self) -> None:
        self._history.redo()


class CustomCollectionActions:
    def __init__(self, db, history: UndoStack):
        self._db = db
        self._history = history

    def create(self, name: str, folders: list[tuple], shape: str | None = None) -> int:
        folder_id = self._db.create_custom_collection(name, shape=shape)
        self._db.add_folders_to_custom_collection(folder_id, folders)
        self._record_creation(name, folder_id, folders, shape)
        return folder_id

    def _record_creation(self, name: str, folder_id: int, folders: list[tuple],
                         shape: str | None) -> None:
        def redo() -> None:
            self._db.create_custom_collection(name, folder_id, shape)
            self._db.add_folders_to_custom_collection(folder_id, folders)
            self._record_creation(name, folder_id, folders, shape)

        self._history.push(UndoEntry(
            f"Create folder “{name}”",
            lambda: self._db.delete_custom_collection(folder_id),
            redo=redo,
        ))

    def add_to(self, folder_id: int, folders: list[tuple] = (),
               items: list[str] = ()) -> None:
        record = self._find(folder_id)
        if record is None:
            return
        held_folders, held_items = set(record["folders"]), set(record["items"])
        added_folders = [m for m in folders if m[0] not in held_folders]
        added_items = [p for p in items if p not in held_items]
        if not (added_folders or added_items):
            return
        self._db.add_folders_to_custom_collection(folder_id, added_folders)
        self._db.add_items_to_custom_collection(folder_id, added_items)

        def undo() -> str | None:
            for folder_key, *_ in added_folders:
                self._db.remove_folder_from_custom_collection(folder_id, folder_key)
            self._db.remove_items_from_custom_collection(folder_id, added_items)
            return None

        self._history.push(UndoEntry(
            _add_label(added_folders, added_items, record["name"]), undo,
            redo=lambda: self.add_to(folder_id, added_folders, added_items)))

    def remove_from(self, folder_id: int, folders: list[tuple] = (),
                    items: list[str] = ()) -> None:
        for folder_key, *_ in folders:
            self._db.remove_folder_from_custom_collection(folder_id, folder_key)
        self._db.remove_items_from_custom_collection(folder_id, items)

        def undo() -> str | None:
            self._db.add_folders_to_custom_collection(folder_id, list(folders))
            self._db.add_items_to_custom_collection(folder_id, list(items))
            return None

        self._history.push(UndoEntry("Remove from folder", undo,
                                     redo=lambda: self.remove_from(folder_id, folders, items)))

    def delete(self, folder_id: int) -> None:
        record = self._find(folder_id)
        if record is None:
            return
        folders = [
            (m["folder_key"], m["level"], m["ref_prompt_id"])
            for m in self._db.folders_in_custom_collections()
            if m["folder_id"] == folder_id and m["folder_key"] in set(record["folders"])
        ]
        order = {key: i for i, key in enumerate(record["folders"])}
        folders.sort(key=lambda m: order[m[0]])
        name, shape, items = record["name"], record["side"], record["items"]
        self._db.delete_custom_collection(folder_id)

        def undo() -> str | None:
            self._db.create_custom_collection(name, folder_id, shape)
            self._db.add_folders_to_custom_collection(folder_id, folders)
            self._db.add_items_to_custom_collection(folder_id, items)
            return None

        self._history.push(UndoEntry(f"Remove collection “{name}”", undo,
                                     redo=lambda: self.delete(folder_id)))

    def _find(self, folder_id: int) -> dict | None:
        for record in self._db.list_custom_collections():
            if record["id"] == folder_id:
                return record
        return None


def _in_genau(genau: Genau | None, row: dict, genau_videos: list[Path],
              pressed_now: list[Path]) -> list[tuple]:
    if genau is None:
        return []
    return [(genau, video) for video in dict.fromkeys(
        [*_copies_of(row, genau_videos), *filter(genau.plays, pressed_now)])]


def _copies_of(row: dict, genau_videos: list[Path]) -> list[Path]:

    made = {stem for file in row_output_files(row)
            if (stem := Path(frame_name(file.get("filename"))).stem)}
    return [video for video in genau_videos if stem_as_made(video) in made]


def _delete_label(count: int) -> str:

    return f"Delete {count} item{'s' if count != 1 else ''}"


def _version_label(count: int) -> str:
    return f"Delete {count} version{'s' if count != 1 else ''}"


def _add_label(folders: list, items: list, name: str) -> str:
    what = [f"{len(things)} {word}{'s' if len(things) != 1 else ''}"
            for things, word in ((folders, "folder"), (items, "item")) if things]
    return f"Add {' and '.join(what)} to “{name}”"
