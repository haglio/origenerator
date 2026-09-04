"""Gallery mutations with undo/redo: delete generations/folders, rename folders.

A Qt-free controller the gallery view drives. Every mutation records how to
reverse it on one undo stack, so a single Undo (button or Ctrl+Z) walks back the
most recent delete or rename. Deletes move the underlying files to the trash and
drop their rows; undo puts both back. The stack is session-scoped, and the oldest
entry is dropped once it overflows.

An undone step also records how to re-apply itself, on a second stack that Redo
walks the other way. A redo is not a mirror-image of the undo but the *original
mutation, run again* — the same call with the same arguments — so it files fresh
trash batches and a fresh undo entry rather than trying to re-drive the ones the
undo already spent. That is what lets a delete be undone and redone any number
of times. Any new mutation empties the redo stack, as everywhere else: once
history has forked, the branch you left is gone.

Falling off that stack no longer ends anything, though: a delete also files the
row and its trashed files in the recovery bin, which holds them for weeks (see
:mod:`origenerator.recovery`). So the stack is the quick "that was a mistake",
and the bin — restored or ended from the gallery's Trash shelf, through
:meth:`GalleryActions.restore_deleted` and :meth:`GalleryActions.purge_deleted` —
is the slow one.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from origenerator import recovery
from origenerator.gallery import (
    custom_folder_id,
    output_disk_files,
    remove_enhance_levels,
    resolve_preview,
)
from origenerator.thumbnail import generate_thumbnail
from origenerator.undo_stack import UndoEntry, UndoStack

logger = logging.getLogger(__name__)


class GalleryActions:
    def __init__(self, db, output_dir: Path, trash, limit: int = 50,
                 release_files: Callable[[list[Path]], None] | None = None,
                 thumb_dir: Path | None = None,
                 cancel_enhancements: Callable[[list[dict]], None] | None = None):
        self._db = db
        self._output_dir = Path(output_dir)
        self._trash = trash
        self._release_files = release_files
        # Told which rows are losing their files, so an enhancement still being
        # made of one can be stopped before it outlives the image it improves.
        # Optional: without it an in-flight enhance runs on past its source.
        self._cancel_enhancements = cancel_enhancements
        # Where a row's tile picture lives, so deleting the version it was made
        # from can redraw it from whichever version now leads. Optional: without
        # it the row keeps a picture of a file that is no longer there.
        self._thumb_dir = Path(thumb_dir) if thumb_dir else None
        # Every mutation below records how to reverse itself here. Generic and
        # entirely unaware of what it is undoing (see origenerator.undo_stack).
        self._history = UndoStack(limit)

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
        # bin goes on holding the files until the user says otherwise.
        # Redo re-deletes the same rows: undo restored them exactly as captured,
        # so the dicts still describe what is there to take away again.
        self._history.push(UndoEntry(_delete_label(len(rows)), undo,
                              redo=lambda: self.delete_rows(rows)))

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

        self._history.push(UndoEntry(_level_label(len(filenames)), undo, batch.purge,
                              redo=lambda: self.delete_enhance_levels(row, filenames)))
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
        tab or a slideshow — would otherwise fail outright.
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
        """End held deletions for good — nothing else ever will: the files
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

        self._history.push(UndoEntry("Reject experiment", undo, batch.purge,
                              redo=lambda: self.reject_experiment(row)))

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
        self._history.push(UndoEntry(
            "Rename folder", lambda: self._db.rename_folder(key, previous),
            redo=lambda: self.rename_folder(key, name),
        ))

    def _rename_custom_folder(self, folder_id: int, name: str | None) -> None:
        if not name:
            return  # nothing to fall back to — keep the name it has
        record = self._custom_folder(folder_id)
        if record is None:
            return
        previous = record["name"]
        self._db.rename_custom_folder(folder_id, name)
        self._history.push(UndoEntry(
            "Rename folder",
            lambda: self._db.rename_custom_folder(folder_id, previous),
            redo=lambda: self._rename_custom_folder(folder_id, name),
        ))

    # --- custom folders ----------------------------------------------------

    def create_custom_folder(self, name: str, members: list[tuple]) -> int:
        """Make a custom folder holding ``members`` — ``(folder_key, level,
        ref_prompt_id)`` triples — and return its id. Undo removes it again."""
        folder_id = self._db.create_custom_folder(name)
        self._db.add_custom_folder_members(folder_id, members)
        self._record_folder_creation(name, folder_id, members)
        return folder_id

    def _record_folder_creation(self, name: str, folder_id: int,
                                members: list[tuple]) -> None:
        """File a just-made custom folder as one undoable step, and say how to
        make it again. The redo re-creates it at the id it had rather than
        letting the database allocate a new one, so the key a saved session
        points at still resolves after undo-then-redo."""
        def redo() -> None:
            self._db.create_custom_folder(name, folder_id)
            self._db.add_custom_folder_members(folder_id, members)
            self._record_folder_creation(name, folder_id, members)

        self._history.push(UndoEntry(
            f"Create folder “{name}”",
            lambda: self._db.delete_custom_folder(folder_id),
            redo=redo,
        ))

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

        self._history.push(UndoEntry(_add_label(len(added), record["name"]), undo,
                              redo=lambda: self.add_to_custom_folder(folder_id, added)))

    def remove_from_custom_folder(self, folder_id: int, folder_key: str,
                                  *, level=None, ref_prompt_id=None) -> None:
        """Drop one gathered folder out of a custom folder. The folder itself and
        its generations are untouched — only the grouping loses it."""
        self._db.remove_custom_folder_member(folder_id, folder_key)
        self._history.push(UndoEntry(
            "Remove from folder",
            lambda: self._db.add_custom_folder_members(
                folder_id, [(folder_key, level, ref_prompt_id)]),
            redo=lambda: self.remove_from_custom_folder(
                folder_id, folder_key, level=level, ref_prompt_id=ref_prompt_id),
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

        self._history.push(UndoEntry(f"Remove folder “{name}”", undo,
                              redo=lambda: self.delete_custom_folder(folder_id)))

    def _custom_folder(self, folder_id: int) -> dict | None:
        for record in self._db.list_custom_folders():
            if record["id"] == folder_id:
                return record
        return None

    # --- what the gallery's Undo and Redo drive ----------------------------

    def can_undo(self) -> bool:
        return self._history.can_undo()

    def undo_label(self) -> str | None:
        return self._history.undo_label()

    def undo(self) -> str | None:
        """Reverse the most recent mutation, returning a prompt_id to navigate
        back to (a restored generation) when the undone step has one."""
        return self._history.undo()

    def can_redo(self) -> bool:
        return self._history.can_redo()

    def redo_label(self) -> str | None:
        return self._history.redo_label()

    def redo(self) -> None:
        """Re-apply the most recently undone mutation, by running it again."""
        self._history.redo()


def _delete_label(count: int) -> str:
    return f"Delete {count} item{'s' if count != 1 else ''}"


def _level_label(count: int) -> str:
    return f"Delete {count} version{'s' if count != 1 else ''}"


def _add_label(count: int, name: str) -> str:
    return f"Add {count} folder{'s' if count != 1 else ''} to “{name}”"
