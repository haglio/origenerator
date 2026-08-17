"""Gallery mutations with undo: delete generations/folders, rename folders.

A Qt-free controller the gallery view drives. Every mutation records how to
reverse it on one undo stack, so a single Undo (button or Ctrl+Z) walks back the
most recent delete or rename. Deletes move the underlying files to the trash and
drop their rows; undo puts both back. The stack is session-scoped, and the oldest
entry is dropped once it overflows.

Falling off that stack no longer ends anything, though: a delete also files the
row and its trashed files in the recovery bin, which holds them for weeks (see
:mod:`origenerator.recovery`). So the stack is the quick "that was a mistake",
and the bin — restored or ended from the gallery's Trash shelf, through
:meth:`GalleryActions.restore_deleted` and :meth:`GalleryActions.purge_deleted` —
is the slow one.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator import recovery
from origenerator.gallery import (
    custom_folder_id,
    output_disk_files,
    remove_enhance_levels,
    resolve_preview,
)
from origenerator.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)


@dataclass
class _UndoEntry:
    # ``undo`` returns a prompt_id to navigate back to (a restored generation), or
    # ``None`` when there's nowhere in particular to go (e.g. a rename).
    label: str
    undo: Callable[[], str | None]
    commit: Callable[[], None] | None = None  # run when dropped without undoing


class GalleryActions:
    def __init__(self, db, output_dir: Path, trash, limit: int = 50,
                 release_files: Callable[[list[Path]], None] | None = None,
                 thumb_dir: Path | None = None,
                 cancel_enhancements: Callable[[list[dict]], None] | None = None):
        self._db = db
        self._output_dir = Path(output_dir)
        self._trash = trash
        self._limit = limit
        self._release_files = release_files
        # Told which rows are losing their files, so an enhancement still being
        # made of one can be stopped before it outlives the image it improves.
        # Optional: without it an in-flight enhance runs on past its source.
        self._cancel_enhancements = cancel_enhancements
        # Where a row's tile picture lives, so deleting the version it was made
        # from can redraw it from whichever version now leads. Optional: without
        # it the row keeps a picture of a file that is no longer there.
        self._thumb_dir = Path(thumb_dir) if thumb_dir else None
        self._stack: list[_UndoEntry] = []

    # --- deletion ----------------------------------------------------------

    def delete_rows(self, rows: list[dict]) -> None:
        """Trash each row's files and drop its DB record, as one undoable step.

        Each row's files go into a batch of their own, filed in the recovery bin
        beside the row it dropped — so an item stays restorable from the Trash
        shelf long after this session's undo stack has forgotten the delete, and
        one item of a deleted folder can be brought back without the rest.
        """
        if not rows:
            return
        self._stop_enhancements(rows)
        # Move files out before touching the DB: if a move fails, nothing is lost.
        batches = self._trash_files(rows)
        for row, batch in batches:
            self._db.delete_generation(row["prompt_id"])
            self._db.record_deletion(row["prompt_id"], row, batch.record())

        def undo() -> str | None:
            for row, batch in batches:
                batch.restore()
                self._db.restore_generation(row)
                self._db.forget_deletion(row["prompt_id"])
            return batches[0][0]["prompt_id"]  # a restored item to navigate back to

        # No commit hook: an entry falling off the stack ends nothing now — the
        # bin goes on holding the files until they expire or the user says so.
        self._push(_UndoEntry(_delete_label(len(rows)), undo))

    def delete_enhance_levels(self, row: dict, filenames: list[str]) -> bool:
        """Trash some of one image's versions, keeping the generation itself.

        A level is a file, not a generation: binning the 0.3-denoise experiment
        leaves the image where it is, in its folder, with its star and its other
        versions. So this trashes those files and rewrites only the row's version
        bookkeeping (:func:`~origenerator.gallery.enhance.remove_enhance_levels`),
        as one undoable step.

        Returns whether anything was deleted — ``False`` when the names match no
        file, or when they would take every version the row has: an image with no
        file left is a deleted generation, and that is the gallery's own delete,
        reached from the thumbnail rather than from this list.

        Nothing is filed in the recovery bin: the bin holds a row and the files
        it was deleted with, and this row was not deleted. So these files keep
        the old arrangement — the trash holds them, and the undo entry falling
        off the stack is what ends them.
        """
        prompt_id = row["prompt_id"]
        updates = remove_enhance_levels(row, filenames)
        if not updates:
            return False
        before = {
            "output_files": row.get("output_files"),
            "original_files": row.get("original_files"),
            "enhance_history": row.get("enhance_history"),
            "thumbnail_path": row.get("thumbnail_path"),
        }
        # Files out first, as everywhere: a move that fails loses nothing.
        ((_row, batch),) = self._trash_files([row], names=set(filenames))
        self._db.update_generation(prompt_id, **updates)
        self._redraw_thumbnail(prompt_id)

        def undo() -> str | None:
            batch.restore()
            self._db.update_generation(prompt_id, **before)
            self._redraw_thumbnail(prompt_id)
            return prompt_id

        self._push(_UndoEntry(_level_label(len(filenames)), undo, batch.purge))
        return True

    def _redraw_thumbnail(self, prompt_id: str) -> None:
        """Rebuild a row's tile picture from whichever version now leads it.

        The thumbnail is a separate JPEG keyed by prompt_id, so deleting the
        version it was rendered from leaves it showing a file that is gone —
        the gallery would still be advertising the enhancement you just binned.
        Rendering is best-effort: a row that can't be redrawn keeps the picture
        it has rather than losing its tile.
        """
        if self._thumb_dir is None:
            return
        row = self._db.get_generation(prompt_id)
        preview = resolve_preview(row, self._output_dir) if row else None
        if preview is None:
            return
        try:
            path = generate_thumbnail(preview[0], preview[1], self._thumb_dir,
                                      name=prompt_id)
        except Exception:
            logger.exception("Could not redraw the thumbnail for %s", prompt_id)
            return
        self._db.update_generation(prompt_id, thumbnail_path=str(path))

    def _stop_enhancements(self, rows: list[dict]) -> None:
        """Stop any enhancement still being made of ``rows``, before their files go.

        An enhancement is not a generation of its own: it is a version of the
        image it improves, folded onto that row when it lands. So a run whose
        image is being deleted has nowhere left to fold — left going, it holds
        the queue for minutes and then produces an enhanced file with no
        original to belong to, which lands in the gallery as a stray
        ``image_enhance`` row (:func:`~origenerator.gallery.enhance
        .fold_enhancement` declines a fold it can't find a source for). So the
        run is cancelled here, at the same choke point the media release uses,
        and for the same reason: every path into the trash passes through, so
        no caller can forget it.

        Not reversed by undo. Restoring the image does not put a cancelled run
        back in ComfyUI's queue — enhancing it again is one press of the button,
        and re-queuing minutes of GPU work on an undo nobody asked to re-launch
        would be the worse surprise.

        The versions delete (:meth:`delete_enhance_levels`) deliberately does
        NOT come through here: it takes files off a row that stays, and an
        enhance re-derives from the original either way, so its run is still
        going to have somewhere to land.
        """
        if self._cancel_enhancements is not None:
            self._cancel_enhancements(rows)

    def _trash_files(self, rows: list[dict], names: set[str] | None = None):
        """Move the files ``rows`` own into the trash — a batch per row — after
        telling the app to let go of them. Returns ``(row, batch)`` pairs.

        A batch per row is what lets the bin restore or end one item on its own;
        deleting a whole folder is still one undo step, made of them.

        ``names`` narrows each row to those output files, for a delete that takes
        some of a row's files rather than the row.

        The release comes first because a file the app itself still holds open
        can't be moved on Windows at all: a preview keeps its video's file open
        for as long as it's showing it, so deleting what's on screen — in any
        tab, a slideshow, or a fullscreen view — would otherwise fail outright.
        Every path in and out of the trash runs through here so no caller can
        forget it.
        """
        by_row = self._files_by_row(rows, names)
        if self._release_files is not None:
            self._release_files([path for files in by_row for path in files])
        return [(row, self._trash.store(files)) for row, files in zip(rows, by_row)]

    def _files_by_row(self, rows: list[dict],
                      names: set[str] | None = None) -> list[list[Path]]:
        """Each row's on-disk files — outputs, sidecars, thumbnail — in row order.

        A path two rows both claim (a shared sidecar) goes to the first of them:
        it can only be moved once, and the batch that took it is the one that has
        to put it back.

        ``names`` narrows each row to those output files, and leaves the
        thumbnail where it is: a delete of some of a row's versions is not a
        delete of the row, and its tile still has a picture to show.
        """
        seen: set[str] = set()
        by_row: list[list[Path]] = []
        for row in rows:
            candidates = list(output_disk_files(row, self._output_dir, names))
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

    # --- the recovery bin: putting a delete back, or ending it ---------------

    def restore_deleted(self, prompt_ids) -> str | None:
        """Bring deleted items back out of the bin — files to where they were,
        rows to the gallery — and return one to navigate to.

        Not pushed onto the undo stack: undoing a restore is just deleting the
        item again, which the user can do directly and which would only file it
        back in the bin. Unknown ids (already restored, already ended) are
        skipped rather than treated as an error.
        """
        restored = None
        for prompt_id in prompt_ids:
            record = self._db.get_deletion(prompt_id)
            if record is not None:
                restored = recovery.restore(self._db, record)
        return restored

    def purge_deleted(self, prompt_ids) -> None:
        """End held deletions now rather than waiting out their window: the files
        are removed and the bin forgets them. Irreversible, and deliberately not
        undoable — the caller confirms with the user first."""
        for prompt_id in prompt_ids:
            record = self._db.get_deletion(prompt_id)
            if record is not None:
                recovery.purge(self._db, record)

    def reject_experiment(self, row: dict) -> None:
        """Reject a background experiment: trash its files and clear their
        references, keeping the row itself — its params and down-verdict are what
        the experiment policy learns from. One undoable step: undo restores the
        files and returns the item to the review shelf (verdict cleared).

        The verdict is recorded here, with the file cleanup, so the whole
        rejection is one reversible unit rather than half in the view.

        Nothing is filed in the recovery bin: the bin holds *deleted rows*, and
        this row is kept — it stays in the gallery's own hands, verdict and all,
        so there is no orphan for a Trash shelf to offer back.

        An enhancement being made of the rejected item is stopped like any
        delete's would be (:meth:`_stop_enhancements`): the row survives, but
        with no files left it is no longer a source anything can fold onto, so
        the run would leave the same stray behind — and resurrect a rejection
        as an enhanced image if it did land.
        """
        prompt_id = row["prompt_id"]
        self._stop_enhancements([row])
        ((_row, batch),) = self._trash_files([row])
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


def _level_label(count: int) -> str:
    return f"Delete {count} version{'s' if count != 1 else ''}"


def _add_label(count: int, name: str) -> str:
    return f"Add {count} folder{'s' if count != 1 else ''} to “{name}”"
