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

from origenerator.gallery import output_disk_files


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

    # --- rename ------------------------------------------------------------

    def rename_folder(self, key: str, name: str | None) -> None:
        previous = self._db.folder_meta_map().get(key, {}).get("custom_name")
        self._db.rename_folder(key, name)
        self._push(_UndoEntry(
            "Rename folder", lambda: self._db.rename_folder(key, previous)
        ))

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
