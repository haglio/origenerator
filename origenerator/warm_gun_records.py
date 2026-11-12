from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from app_support.video_kind import classify
from app_support.watch_weights import WATCH_BLOCK, WEIGHT_KEY, weight_for

from origenerator import config
from origenerator.db_generations import WATCH_COLUMNS
from origenerator.evolver_agreement import evolver_checkout, records_folder
from origenerator.evolver_export import PARTIAL_MARKER
from origenerator.media import MediaType, media_type_from_filename, video_header
from origenerator.video_records import GalleryReading

FILE_NAME = "gallery_records.json"
NON_AI_FOLDER = "non_AI"


class PlayedFrom(NamedTuple):
    library_root: Path
    kino: Path
    genau: Path


def records_for_the_phone(rows: list[dict], played_from: PlayedFrom, *,
                          length_of: Callable[[Path], float | None]) -> dict[str, dict]:
    reading = GalleryReading(rows)
    records = {}
    for folder in (played_from.kino, played_from.genau):
        for video in _videos_in(folder):
            row = reading.row_of(video)
            if row is None:
                continue
            record = reading.record_of(row)
            counts = {field: int(row.get(column) or 0) for field, column in WATCH_COLUMNS}
            kind = classify(genau=folder == played_from.genau, excerpt=False,
                            duration_seconds=length_of(video))
            records[video.relative_to(played_from.library_root).as_posix()] = {
                **record, "video": {**record["video"], "type": kind},
                "favorite": bool(row.get("starred")),
                WATCH_BLOCK: {**counts, WEIGHT_KEY: weight_for(counts)}}
    return records


def _videos_in(folder: Path) -> Iterator[Path]:
    for video in sorted(folder.rglob("*")) if folder.is_dir() else ():
        if (media_type_from_filename(video.name) == MediaType.VIDEO
                and PARTIAL_MARKER not in video.name
                and NON_AI_FOLDER not in video.relative_to(folder).parts and video.is_file()):
            yield video


class _Lengths:
    def __init__(self) -> None:
        self._known: dict[tuple[str, int], float | None] = {}

    def __call__(self, video: Path) -> float | None:
        key = (str(video), video.stat().st_mtime_ns)
        if key not in self._known:
            header = video_header(video)
            self._known[key] = header.seconds if header is not None else None
        return self._known[key]


class PhoneRecords:
    QUIET_SECONDS = 30.0

    def __init__(self, db, *, write_to: Path | None, played_from: PlayedFrom,
                 clock: Callable[[], float] = time.monotonic,
                 length_of: Callable[[Path], float | None] | None = None) -> None:
        self._db, self._write_to, self._played_from, self._clock = db, write_to, played_from, clock
        self._length_of = length_of or _Lengths()
        self._written: object = None
        self._seen: object = None
        self._changed_at = clock()
        self._writing = False

    @classmethod
    def of_this_library(cls, db, *, preview: bool) -> PhoneRecords:
        records = None if preview else records_folder(evolver_checkout(), config.LIBRARY_ROOT)
        return cls(db, write_to=records / FILE_NAME if records is not None else None,
                   played_from=PlayedFrom(config.LIBRARY_ROOT, config.KINO_UPSCALES_DIR,
                                   config.GENAU_DIR))

    def write_when_due(self, off_thread: Callable[[Callable, Callable], None]) -> None:
        if self._writing or not self.due():
            return
        self._writing = True
        off_thread(self.write, self._written_out)

    def _written_out(self, _count) -> None:
        self._writing = False

    def due(self) -> bool:
        if self._write_to is None:
            return False
        version = self._db.library_version()
        if self._written is None:
            return True
        if version != self._seen:
            self._seen, self._changed_at = version, self._clock()
        return version != self._written and self._clock() - self._changed_at >= self.QUIET_SECONDS

    def write(self) -> int:
        version = self._db.library_version()
        records = records_for_the_phone(self._db.list_generations(), self._played_from,
                                        length_of=self._length_of)
        self._write_to.parent.mkdir(parents=True, exist_ok=True)
        partial = self._write_to.with_name(f"{self._write_to.stem}{PARTIAL_MARKER}json")
        partial.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
        os.replace(partial, self._write_to)
        self._written = self._seen = version
        return len(records)
