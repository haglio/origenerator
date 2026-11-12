from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

from app_support.gallery_records import GalleryReading, size_labels
from app_support.kino_folder import is_ai_video

from origenerator import config
from origenerator.evolver_agreement import evolver_checkout, records_folder
from origenerator.evolver_export import PARTIAL_MARKER
from origenerator.generation_state import made_here
from origenerator.media import MediaType, VideoHeader, media_type_from_filename, video_header

FILE_NAME = "gallery_records.json"


class PlayedFrom(NamedTuple):
    library_root: Path
    kino: Path
    genau: Path


def records_for_the_phone(rows: list[dict], played_from: PlayedFrom, *,
                          measured: Callable[[Path, dict, bool], dict]) -> dict[str, dict]:
    reading = GalleryReading(rows)
    records, measured_rows = {}, {}
    for folder in (played_from.kino, played_from.genau):
        for video in _videos_in(folder, played_from.library_root):
            row = reading.row_of(video)
            if row is None:
                continue
            genau = folder == played_from.genau
            row = measured_rows[row["prompt_id"]] = measured(
                video, measured_rows.get(row["prompt_id"], row), genau)
            records[video.relative_to(played_from.library_root).as_posix()] = reading.record_of(
                row, where=video, genau=genau)
    return records


def _videos_in(folder: Path, library_root: Path) -> Iterator[Path]:
    for video in sorted(folder.rglob("*")) if folder.is_dir() else ():
        if (media_type_from_filename(video.name) == MediaType.VIDEO
                and PARTIAL_MARKER not in video.name
                and is_ai_video(video.relative_to(library_root)) and video.is_file()):
            yield video


def _timer(seconds: float, work: Callable[[], object]) -> Callable[[], None]:
    timer = threading.Timer(seconds, work)
    timer.daemon = True
    timer.start()
    return timer.cancel


class PhoneRecords:
    QUIET_SECONDS = 30.0

    def __init__(self, db, *, write_to: Path | None, played_from: PlayedFrom,
                 later: Callable[[float, Callable], Callable[[], None]] = _timer,
                 measure: Callable[[Path], VideoHeader | None] = video_header) -> None:
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
                                            measured=self._measured)
            self._write_to.parent.mkdir(parents=True, exist_ok=True)
            partial = self._write_to.with_name(self._write_to.stem + self._partial)
            partial.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n",
                               encoding="utf-8", newline="\n")
            os.replace(partial, self._write_to)
        return len(records)

    def _measured(self, video: Path, row: dict, genau: bool) -> dict:
        wants_seconds = not genau and row.get("video_seconds") is None
        wants_size = made_here(row) and not row.get("video_resolution")
        header = self._measure(video) if wants_seconds or wants_size else None
        if header is None:
            return row
        found = {"video_seconds": header.seconds, **size_labels(header.width, header.height)}
        kept = {column: value for column, value in found.items() if row.get(column) in (None, "")}
        self._db.set_library_record(row["prompt_id"], **kept)
        return {**row, **kept}
