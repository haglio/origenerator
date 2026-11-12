from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from app_support.gallery_records import GalleryReading
from app_support.kino_folder import is_ai_video

from origenerator import config
from origenerator.evolver_agreement import evolver_checkout, records_folder
from origenerator.evolver_export import PARTIAL_MARKER
from origenerator.media import MediaType, media_type_from_filename, video_header

FILE_NAME = "gallery_records.json"


class PlayedFrom(NamedTuple):
    library_root: Path
    kino: Path
    genau: Path


def records_for_the_phone(rows: list[dict], played_from: PlayedFrom, *,
                          length_of: Callable[[Path, dict], float | None]) -> dict[str, dict]:
    reading = GalleryReading(rows)
    records = {}
    for folder in (played_from.kino, played_from.genau):
        for video in _videos_in(folder, played_from.library_root):
            row = reading.row_of(video)
            if row is None:
                continue
            genau = folder == played_from.genau
            records[video.relative_to(played_from.library_root).as_posix()] = reading.record_of(
                row, where=video, genau=genau, seconds=None if genau else length_of(video, row))
    return records


def _videos_in(folder: Path, library_root: Path) -> Iterator[Path]:
    for video in sorted(folder.rglob("*")) if folder.is_dir() else ():
        if (media_type_from_filename(video.name) == MediaType.VIDEO
                and PARTIAL_MARKER not in video.name
                and is_ai_video(video.relative_to(library_root)) and video.is_file()):
            yield video


def measured_seconds(video: Path) -> float | None:
    header = video_header(video)
    return header.seconds if header is not None else None


def _timer(seconds: float, work: Callable[[], object]) -> Callable[[], None]:
    timer = threading.Timer(seconds, work)
    timer.daemon = True
    timer.start()
    return timer.cancel


class PhoneRecords:
    QUIET_SECONDS = 30.0

    def __init__(self, db, *, write_to: Path | None, played_from: PlayedFrom,
                 later: Callable[[float, Callable], Callable[[], None]] = _timer,
                 measure: Callable[[Path], float | None] = measured_seconds) -> None:
        self._db, self._write_to, self._played_from = db, write_to, played_from
        self._later, self._measure = later, measure
        self._writing = threading.Lock()
        self._cancel_the_wait: Callable[[], None] = lambda: None
        self._partial = f"{PARTIAL_MARKER}{uuid.uuid4().hex}.json"

    @classmethod
    def of_this_library(cls, db, *, preview: bool, **timing) -> PhoneRecords:
        records = None if preview else records_folder(evolver_checkout(), config.LIBRARY_ROOT)
        held = records is not None and records.is_dir()
        return cls(db, write_to=records / FILE_NAME if held else None,
                   played_from=PlayedFrom(config.LIBRARY_ROOT, config.KINO_UPSCALES_DIR,
                                          config.GENAU_DIR), **timing)

    def watch(self) -> None:
        if self._write_to is None:
            return
        self._db.when_changed(self._changed)
        self._later(0, self.write)

    def _changed(self) -> None:
        if self._writing.locked():
            return
        self._cancel_the_wait()
        self._cancel_the_wait = self._later(self.QUIET_SECONDS, self.write)

    def write(self) -> int:
        if self._write_to is None:
            return 0
        with self._writing:
            records = records_for_the_phone(self._db.list_generations(), self._played_from,
                                            length_of=self._length_of)
            self._write_to.parent.mkdir(parents=True, exist_ok=True)
            partial = self._write_to.with_name(self._write_to.stem + self._partial)
            partial.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n",
                               encoding="utf-8", newline="\n")
            os.replace(partial, self._write_to)
        return len(records)

    def _length_of(self, video: Path, row: dict) -> float | None:
        if row.get("video_seconds") is not None:
            return row["video_seconds"]
        seconds = self._measure(video)
        if seconds is not None:
            self._db.set_library_record(row["prompt_id"], video_seconds=seconds)
        return seconds
