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
from __future__ import annotations

import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import retried_while_held

from origenerator.file_numbers import NUMBERED, next_number, numbered

_MOVE_ATTEMPTS = 12     # a freshly-closed media file can stay locked for a beat
_MOVE_RETRY_DELAY = 0.15


@dataclass
class TrashedBatch:
    """One deletion's files parked in the trash, with how to put them back."""

    moves: list[tuple[Path, Path]]  # (original_path, trashed_path)
    subdir: Path | None  # the batch's holding folder, or None when empty

    def restore(self) -> dict[str, str]:
        """Put every file back, under the next free number where its name is taken."""
        renamed = self._renamed_where_taken()
        for original, trashed in self.moves:
            back = renamed.get(original, original)
            back.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trashed), str(back))
        self._discard_subdir()
        return {original.name: back.name for original, back in renamed.items()}

    def _renamed_where_taken(self) -> dict[Path, Path]:
        families: dict[tuple[str, str], list[tuple[Path, Path]]] = defaultdict(list)
        for original, trashed in self.moves:
            if match := NUMBERED.match(original.name):
                families[(match["stem"], match["counter"])].append((original, trashed))
        held = Trash(self.subdir.parent).held_names() if self.subdir is not None else set()
        renamed: dict[Path, Path] = {}
        for (stem, _counter), family in families.items():
            if not any(original.exists() and original != trashed for original, trashed in family):
                continue
            number = next_number(stem, {original.parent for original, _ in family}, held)
            renamed.update({original: original.with_name(numbered(original.name, stem, number))
                            for original, _ in family})
        return renamed

    def purge(self) -> None:
        """Delete the held files for good — the opposite of ``restore``."""
        if self.subdir is not None:
            shutil.rmtree(self.subdir, ignore_errors=True)

    def holding(self, original: Path) -> Path | None:
        return next((trashed for was, trashed in self.moves if was == Path(original)), None)

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
    def from_record(cls, record: dict) -> TrashedBatch:
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
            dest = subdir / _held_as(i, path.name)
            _move(path, dest)
            moves.append((path, dest))
        return TrashedBatch(moves=moves, subdir=subdir)

    def held_names(self) -> set[str]:
        """The names its files had, whichever folder each was deleted from."""
        if not self.root.is_dir():
            return set()
        return {_name_before(held.name) for batch in self.root.iterdir() if batch.is_dir()
                for held in batch.iterdir()}

    def purge_orphans(self, keep) -> int:
        """Delete every batch folder not named in ``keep``, and say how many went.

        The recovery bin holds a batch indefinitely, so clearing the trash
        wholesale (what a launch used to do) would destroy exactly what is now
        recoverable. What is left over once the bin's own folders are spared is
        genuinely unreachable: a rejected experiment's batch that fell off the
        undo stack, a batch from before the bin existed, or a folder left over
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


def _held_as(index: int, name: str) -> str:
    # The index keeps same-named files from distinct folders apart.
    return f"{index}_{name}"


def _name_before(held: str) -> str:
    return held.partition("_")[2]


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
    retried_while_held(lambda: shutil.move(str(src), str(dest)),
                       attempts=_MOVE_ATTEMPTS, delay_s=_MOVE_RETRY_DELAY)
