from __future__ import annotations

import logging
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app_support.file_channel import retried_while_held

from origenerator.file_numbers import NUMBERED, next_number, numbered

logger = logging.getLogger(__name__)

_MOVE_ATTEMPTS = 12
_MOVE_RETRY_DELAY = 0.15


@dataclass
class TrashedBatch:
    moves: list[tuple[Path, Path]]
    subdir: Path | None
    sent_to_kino_trash: list[tuple[Path, Path]] = field(default_factory=list)

    def restore(self) -> dict[str, str]:
        renamed = self._renamed_where_taken()
        for original, trashed in self.moves:
            back = renamed.get(original, original)
            back.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(trashed), str(back))
        self._discard_subdir()
        for original, held in self.sent_to_kino_trash:
            if held.is_file() and not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                _move(held, original)
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
        if self.subdir is not None:
            shutil.rmtree(self.subdir, ignore_errors=True)

    def empty(self, *, keeping: Path | None) -> None:
        for _original, trashed in self.moves:
            if trashed != keeping:
                trashed.unlink(missing_ok=True)

    def holding(self, original: Path) -> Path | None:
        return next((trashed for was, trashed in self.moves if was == Path(original)), None)

    def record(self) -> dict:
        kino = {"sent_to_kino_trash": _as_recorded(self.sent_to_kino_trash)} if self.sent_to_kino_trash else {}
        return {
            "moves": _as_recorded(self.moves),
            "subdir": str(self.subdir) if self.subdir is not None else None,
            **kino,
        }

    @classmethod
    def from_record(cls, record: dict) -> TrashedBatch:
        subdir = (record or {}).get("subdir")
        return cls(
            moves=_as_read((record or {}).get("moves")),
            subdir=Path(subdir) if subdir else None,
            sent_to_kino_trash=_as_read((record or {}).get("sent_to_kino_trash")),
        )

    def _discard_subdir(self) -> None:
        if self.subdir is not None and self.subdir.exists():
            shutil.rmtree(self.subdir, ignore_errors=True)


class Trash:
    def __init__(self, root: Path):
        self.root = Path(root)

    def store(self, paths) -> TrashedBatch:
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
        if not self.root.is_dir():
            return set()
        return {_name_before(held.name) for batch in self.root.iterdir() if batch.is_dir()
                for held in batch.iterdir()}

    def purge_orphans(self, keep) -> int:
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


@dataclass(frozen=True)
class Kino:
    library: Path
    trash: Path

    def plays(self, video: Path) -> bool:
        return video.is_relative_to(self.library) and video.is_file()

    def take_out(self, videos) -> list[tuple[Path, Path]]:
        sent = []
        for video in videos:
            held = self.trash / video.name
            if held.exists():
                continue
            try:
                self.trash.mkdir(parents=True, exist_ok=True)
                _move(video, held)
            except OSError:
                logger.warning("Could not take %s out of Kino; it stays there", video.name,
                               exc_info=True)
                continue
            sent.append((video, held))
        return sent


def _as_recorded(moves: list[tuple[Path, Path]]) -> list[list[str]]:
    return [[str(was), str(now)] for was, now in moves]


def _as_read(recorded) -> list[tuple[Path, Path]]:
    return [(Path(was), Path(now)) for was, now in recorded or []]


def _held_as(index: int, name: str) -> str:
    return f"{index}_{name}"


def _name_before(held: str) -> str:
    return held.partition("_")[2]


def _move(src: Path, dest: Path) -> None:
    # Retry briefly: Qt's media backend closes a source on its own thread a beat after release, and Windows AV scanners or the indexer can lock any file
    retried_while_held(lambda: shutil.move(str(src), str(dest)),
                       attempts=_MOVE_ATTEMPTS, delay_s=_MOVE_RETRY_DELAY)
