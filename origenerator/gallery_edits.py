from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator import trash_collection
from origenerator.db_generations import library_paths_in
from origenerator.gallery import (
    output_disk_files,
    remove_enhance_versions,
    resolve_preview,
)
from origenerator.gallery.output import with_files_renamed
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import generate_thumbnail
from origenerator.trash import Kino
from origenerator.undo_stack import UndoEntry, UndoStack

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GalleryEnvironment:
    release_files: Callable[..., None] | None = None
    cancel_enhancements: Callable[[list[dict]], None] | None = None
    thumb_dir: Path | None = None
    kino: Kino | None = None


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

    def delete_rows(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._stop_enhancements(rows)
        batches = self._trash_files(rows)
        for row, batch in batches:
            self._db.delete_generation(row["prompt_id"])
            self._db.record_trashed(row["prompt_id"], row, batch.record())

        def undo() -> str | None:
            for row, batch in batches:
                self._db.restore_generation(with_files_renamed(row, batch.restore()))
                self._db.forget_trashed(row["prompt_id"])
            return batches[0][0]["prompt_id"]

        self._history.push(UndoEntry(_delete_label(len(rows)), undo,
                              redo=lambda: self.delete_rows(rows)))

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
                     the_item_stays: bool = False):
        # Windows cannot move a file the app still holds open, as a preview does its video.
        by_row = self._files_by_row(rows, names)
        in_kino = [self._in_kino(row) if names is None else [] for row in rows]
        if self._environment.release_files is not None:
            self._environment.release_files([path for files in [*by_row, *in_kino] for path in files],
                                            the_item_stays=the_item_stays)
        batches = [(row, self._trash.store(files)) for row, files in zip(rows, by_row, strict=True)]
        for (_row, batch), videos in zip(batches, in_kino, strict=True):
            batch.sent_to_kino_trash = self._environment.kino.take_out(videos) if videos else []
        return batches

    def _in_kino(self, row: dict) -> list[Path]:
        kino = self._environment.kino
        if kino is None:
            return []
        return [video for video in map(Path, library_paths_in(row.get("output_files")))
                if kino.plays(video)]

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
        restored = None
        for prompt_id in prompt_ids:
            record = self._db.get_trashed(prompt_id)
            if record is not None:
                restored = trash_collection.restore(self._db, record)
        return restored

    def purge_deleted(self, prompt_ids) -> None:
        for prompt_id in prompt_ids:
            record = self._db.get_trashed(prompt_id)
            if record is not None:
                trash_collection.purge(self._db, record)

    def reject_experiment(self, row: dict) -> None:
        prompt_id = row["prompt_id"]
        self._stop_enhancements([row])
        ((_row, batch),) = self._trash_files([row])
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
                              redo=lambda: self.reject_experiment(row)))

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


def _delete_label(count: int) -> str:
    return f"Delete {count} item{'s' if count != 1 else ''}"


def _version_label(count: int) -> str:
    return f"Delete {count} version{'s' if count != 1 else ''}"


def _add_label(folders: list, items: list, name: str) -> str:
    what = [f"{len(things)} {word}{'s' if len(things) != 1 else ''}"
            for things, word in ((folders, "folder"), (items, "item")) if things]
    return f"Add {' and '.join(what)} to “{name}”"
