"""App-managed trash that holds deleted files so a deletion can be undone.

Deleting a generation moves its files here instead of removing them, so an undo
can move them straight back to where they were. Each deleted item gets its own
subdirectory, keyed by a unique token, so items never tread on one another and
ending one is a single ``rmtree``.

How long a batch is held is not decided here, and nothing decides it anywhere:
the recovery bin records each one alongside the row it belonged to and holds it
until the user restores it or ends it (see :mod:`origenerator.recovery`), so a
batch outlives the session that made it for as long as it is left alone.
:meth:`Trash.purge_orphans` is the other half of that — it clears whatever the
bin does *not* name, which is the only thing left that nothing can reach.
"""

import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_MOVE_ATTEMPTS = 12     # a freshly-closed media file can stay locked for a beat
_MOVE_RETRY_DELAY = 0.15


@dataclass
class TrashedBatch:
    """One deletion's files parked in the trash, with how to put them back."""

    moves: list[tuple[Path, Path]]  # (original_path, trashed_path)
    subdir: Path | None  # the batch's holding folder, or None when empty

    def restore(self) -> None:
        """Move every file back to the path it was deleted from."""
        for original, trashed in self.moves:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trashed), str(original))
        self._discard_subdir()

    def purge(self) -> None:
        """Delete the held files for good — the opposite of ``restore``."""
        if self.subdir is not None:
            shutil.rmtree(self.subdir, ignore_errors=True)

    def record(self) -> dict:
        """This batch as plain data, so it can be stored and re-made later.

        What the recovery bin keeps in the database beside the deleted row: the
        moves are how to put the files back, the subdir is what to remove when
        the item is ended instead.
        """
        return {
            "moves": [[str(original), str(trashed)] for original, trashed in self.moves],
            "subdir": str(self.subdir) if self.subdir is not None else None,
        }

    @classmethod
    def from_record(cls, record: dict) -> "TrashedBatch":
        """Re-make a batch from what :meth:`record` stored — the handle a session
        that never performed the delete needs in order to undo or end it."""
        subdir = (record or {}).get("subdir")
        return cls(
            moves=[(Path(original), Path(trashed))
                   for original, trashed in (record or {}).get("moves") or []],
            subdir=Path(subdir) if subdir else None,
        )

    def _discard_subdir(self) -> None:
        if self.subdir is not None and self.subdir.exists():
            shutil.rmtree(self.subdir, ignore_errors=True)


class Trash:
    def __init__(self, root: Path):
        self.root = Path(root)

    def store(self, paths) -> TrashedBatch:
        """Move ``paths`` into a fresh batch folder and return its undo handle."""
        paths = [Path(p) for p in paths]
        if not paths:
            return TrashedBatch(moves=[], subdir=None)
        subdir = self.root / uuid.uuid4().hex
        subdir.mkdir(parents=True, exist_ok=True)
        moves: list[tuple[Path, Path]] = []
        for i, path in enumerate(paths):
            # The index prefix keeps same-named files from distinct folders apart.
            dest = subdir / f"{i}_{path.name}"
            _move(path, dest)
            moves.append((path, dest))
        return TrashedBatch(moves=moves, subdir=subdir)

    def purge_orphans(self, keep) -> int:
        """Delete every batch folder not named in ``keep``, and say how many went.

        The recovery bin holds a batch indefinitely, so clearing the trash
        wholesale (what a launch used to do) would destroy exactly what is now
        recoverable. What is left over once the bin's own folders are spared is
        genuinely unreachable: a rejected experiment's batch that fell off the
        undo stack, a batch from before the bin existed, or a folder left behind
        by a crash between the move and the record. Without this the trash only
        ever grows.
        """
        if not self.root.exists():
            return 0
        held = {Path(path).resolve() for path in keep if path}
        removed = 0
        for child in self.root.iterdir():
            if not child.is_dir() or child.resolve() in held:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        return removed


class NoTrash:
    """A trash that takes nothing: every delete leaves its files where they are.

    What a session with no standing to destroy library files gets instead of a
    real one — see :func:`origenerator.branch_session.session_trash`. Deleting
    still drops the row; the empty batch returned here restores and purges
    nothing, and purging orphans never reaches what an earlier session parked.
    """

    def store(self, paths) -> TrashedBatch:
        return TrashedBatch(moves=[], subdir=None)

    def purge_orphans(self, keep) -> int:
        return 0


def _move(src: Path, dest: Path) -> None:
    """Move a file into the trash, retrying briefly past a transient lock.

    A video the preview only just let go of can stay open for a moment — the
    media backend closes its source on its own thread, a beat after being told
    to — and AV scanners or the indexer can grab any file, so a one-shot move
    would fail where a second or two of retries succeeds. What retrying can't
    outlast is a pane still *showing* the file: that handle never goes away on
    its own, which is why the release runs first (see
    ``GalleryActions._trash_files``).
    """
    for attempt in range(_MOVE_ATTEMPTS):
        try:
            shutil.move(str(src), str(dest))
            return
        except PermissionError:
            if attempt == _MOVE_ATTEMPTS - 1:
                raise
            time.sleep(_MOVE_RETRY_DELAY)
