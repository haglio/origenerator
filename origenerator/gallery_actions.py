"""Gallery mutations with undo: delete generations/folders, rename folders.

A Qt-free controller the gallery view drives. Every mutation records how to
reverse it on one undo stack, so a single Undo (button or Ctrl+Z) walks back the
most recent delete or rename. Deletes move the underlying files to the trash and
drop their rows; undo puts both back. The stack is session-scoped — anything
still on it when the app closes is committed (the trash is swept next launch).
When the stack overflows its limit, the oldest entry is committed for good,
purging its trashed files.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator.gallery import custom_folder_id, output_disk_files


@dataclass
class _UndoEntry:
    # ``undo`` returns a prompt_id to navigate back to (a restored generation), or
    # ``None`` when there's nowhere in particular to go (e.g. a rename).
    label: str
    undo: Callable[[], str | None]
    commit: Callable[[], None] | None = None  # run when dropped without undoing


class GalleryActions:
    def __init__(self, db, output_dir: Path, trash, limit: int = 50):
        self._db = db
        self._output_dir = Path(output_dir)
        self._trash = trash
        self._limit = limit
        self._stack: list[_UndoEntry] = []

    # --- deletion ----------------------------------------------------------

    def delete_rows(self, rows: list[dict]) -> None:
        """Trash each row's files and drop its DB record, as one undoable step."""
        if not rows:
            return
        # Move files out before touching the DB: if a move fails, nothing is lost.
        batch = self._trash.store(self._files_for_rows(rows))
        for row in rows:
            self._db.delete_generation(row["prompt_id"])

        captured = list(rows)

        def undo() -> str | None:
            batch.restore()
            for row in captured:
                self._db.restore_generation(row)
            return captured[0]["prompt_id"]  # a restored item to navigate back to

        self._push(_UndoEntry(_delete_label(len(rows)), undo, batch.purge))

    def _files_for_rows(self, rows: list[dict]) -> list[Path]:
        """Every on-disk file the rows own — outputs, sidecars, thumbnails."""
        files: list[Path] = []
        seen: set[str] = set()
        for row in rows:
            candidates = list(output_disk_files(row, self._output_dir))
            thumb = row.get("thumbnail_path")
            if thumb:
                candidates.append(Path(thumb))
            for path in candidates:
                if path.exists() and str(path) not in seen:
                    seen.add(str(path))
                    files.append(path)
        return files

    def reject_experiment(self, row: dict) -> None:
        """Reject a background experiment: trash its files and clear their
        references, keeping the row itself — its params and down-verdict are what
        the experiment policy learns from. One undoable step: undo restores the
        files and returns the item to the review shelf (verdict cleared).

        The verdict is recorded here, with the file cleanup, so the whole
        rejection is one reversible unit rather than half in the view.
        """
        prompt_id = row["prompt_id"]
        batch = self._trash.store(self._files_for_rows([row]))
        self._db.set_experiment_verdict(prompt_id, "down")
        self._db.update_generation(
            prompt_id, output_files=None, thumbnail_path=None
        )

        def undo() -> str | None:
            batch.restore()
            self._db.set_experiment_verdict(prompt_id, None)
            self._db.update_generation(
                prompt_id,
                output_files=row.get("output_files"),
                thumbnail_path=row.get("thumbnail_path"),
            )
            return None  # back on the review shelf, not in any folder

        self._push(_UndoEntry("Reject experiment", undo, batch.purge))

    # --- rename ------------------------------------------------------------

    def rename_folder(self, key: str, name: str | None) -> None:
        """Rename a folder. A derived folder gets an overlay name (blank resets it
        to the label its settings produce); a custom folder's name IS the folder,
        so a blank one is refused rather than leaving an unnamed row behind."""
        folder_id = custom_folder_id(key)
        if folder_id is not None:
            self._rename_custom_folder(folder_id, name)
            return
        previous = self._db.folder_meta_map().get(key, {}).get("custom_name")
        self._db.rename_folder(key, name)
        self._push(_UndoEntry(
            "Rename folder", lambda: self._db.rename_folder(key, previous)
        ))

    def _rename_custom_folder(self, folder_id: int, name: str | None) -> None:
        if not name:
            return  # nothing to fall back to — keep the name it has
        record = self._custom_folder(folder_id)
        if record is None:
            return
        previous = record["name"]
        self._db.rename_custom_folder(folder_id, name)
        self._push(_UndoEntry(
            "Rename folder",
            lambda: self._db.rename_custom_folder(folder_id, previous),
        ))

    # --- custom folders ----------------------------------------------------

    def create_custom_folder(self, name: str, members: list[tuple]) -> int:
        """Make a custom folder holding ``members`` — ``(folder_key, level,
        ref_prompt_id)`` triples — and return its id. Undo removes it again."""
        folder_id = self._db.create_custom_folder(name)
        self._db.add_custom_folder_members(folder_id, members)
        self._push(_UndoEntry(
            f"Create folder “{name}”",
            lambda: self._db.delete_custom_folder(folder_id),
        ))
        return folder_id

    def add_to_custom_folder(self, folder_id: int, members: list[tuple]) -> None:
        """Add folders to a custom folder, as one undoable step. Members already in
        it are left alone by the undo — they were there before this add."""
        record = self._custom_folder(folder_id)
        if record is None:
            return
        held = set(record["members"])
        added = [m for m in members if m[0] not in held]
        if not added:
            return
        self._db.add_custom_folder_members(folder_id, added)

        def undo() -> str | None:
            for folder_key, *_ in added:
                self._db.remove_custom_folder_member(folder_id, folder_key)
            return None

        self._push(_UndoEntry(_add_label(len(added), record["name"]), undo))

    def remove_from_custom_folder(self, folder_id: int, folder_key: str,
                                  *, level=None, ref_prompt_id=None) -> None:
        """Drop one gathered folder out of a custom folder. The folder itself and
        its generations are untouched — only the grouping loses it."""
        self._db.remove_custom_folder_member(folder_id, folder_key)
        self._push(_UndoEntry(
            "Remove from folder",
            lambda: self._db.add_custom_folder_members(
                folder_id, [(folder_key, level, ref_prompt_id)]),
        ))

    def delete_custom_folder(self, folder_id: int) -> None:
        """Remove a custom folder outright. Undo brings it back at the same id —
        so the key a saved session points at still resolves — with the folders it
        gathered, in order."""
        record = self._custom_folder(folder_id)
        if record is None:
            return
        members = [
            (m["folder_key"], m["level"], m["ref_prompt_id"])
            for m in self._db.custom_folder_members_full()
            if m["folder_id"] == folder_id and m["folder_key"] in set(record["members"])
        ]
        # Restore in the order the folder listed them, not the order the identity
        # query happened to return.
        order = {key: i for i, key in enumerate(record["members"])}
        members.sort(key=lambda m: order[m[0]])
        name = record["name"]
        self._db.delete_custom_folder(folder_id)

        def undo() -> str | None:
            self._db.create_custom_folder(name, folder_id)
            self._db.add_custom_folder_members(folder_id, members)
            return None

        self._push(_UndoEntry(f"Remove folder “{name}”", undo))

    def _custom_folder(self, folder_id: int) -> dict | None:
        for record in self._db.list_custom_folders():
            if record["id"] == folder_id:
                return record
        return None

    # --- undo stack --------------------------------------------------------

    def can_undo(self) -> bool:
        return bool(self._stack)

    def undo_label(self) -> str | None:
        return self._stack[-1].label if self._stack else None

    def undo(self) -> str | None:
        """Reverse the most recent mutation, returning a prompt_id to navigate
        back to (a restored generation) when the undone step has one."""
        if not self._stack:
            return None
        return self._stack.pop().undo()

    def _push(self, entry: _UndoEntry) -> None:
        self._stack.append(entry)
        while len(self._stack) > self._limit:
            evicted = self._stack.pop(0)
            if evicted.commit is not None:
                evicted.commit()


def _delete_label(count: int) -> str:
    return f"Delete {count} item{'s' if count != 1 else ''}"


def _add_label(count: int, name: str) -> str:
    return f"Add {count} folder{'s' if count != 1 else ''} to “{name}”"
