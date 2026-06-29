"""App-managed trash that holds deleted files so a deletion can be undone.

Deleting a generation moves its files here instead of removing them, so an undo
can move them straight back to where they were. Files that fall out of the undo
window are purged for good; whatever survives a session is swept on next launch.
Each delete gets its own subdirectory, keyed by a unique token, so batches never
tread on one another and purging one is a single ``rmtree``.
"""

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


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
            shutil.move(str(path), str(dest))
            moves.append((path, dest))
        return TrashedBatch(moves=moves, subdir=subdir)

    def sweep(self) -> None:
        """Permanently clear all batches — leftovers from a prior session."""
        shutil.rmtree(self.root, ignore_errors=True)
