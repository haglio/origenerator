"""The upscale Evolver makes of a video sent to it, found where Evolver files it.

Evolver writes it to ``<orientation>/<source>/<name>_topaz.mp4`` under
``upscaled_by_orientation`` (Evolver's ``util/sidecar.upscaled_video_path``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from origenerator.media import MediaType, media_type_from_filename

UPSCALE_SUFFIX = "_topaz"
ORIENTATIONS = ("landscape", "portrait")


@dataclass(frozen=True)
class EvolverUpscales:
    by_stem: dict[str, Path]

    @classmethod
    def scan(cls, upscaled_dir, source: str) -> EvolverUpscales:
        return cls({stem: path for filed_under, path in filed_upscales(upscaled_dir)
                    if filed_under == source and (stem := original_stem(path)) is not None})

    def upscale_of(self, video) -> Path | None:
        video = Path(video)
        upscale = self.by_stem.get(video.stem)
        if (upscale is None or media_type_from_filename(video.name) != MediaType.VIDEO
                or not _predates(video, upscale)):
            return None
        return upscale


def filed_upscales(upscaled_dir) -> list[tuple[str, Path]]:
    filed = []
    for orientation in ORIENTATIONS:
        folder = Path(upscaled_dir) / orientation
        sources = sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
        for source in sources:
            filed.extend((source.name, path) for path in _filed_in(source))
    return filed


_READINGS: dict[Path, tuple[int, list[Path]]] = {}


def _filed_in(source: Path) -> list[Path]:
    written = source.stat().st_mtime_ns
    reading = _READINGS.get(source)
    if reading is None or reading[0] != written:
        reading = _READINGS[source] = (written, sorted(source.iterdir()))
    return reading[1]


def original_stem(path) -> str | None:
    path = Path(path)
    if path.parent.parent.name not in ORIENTATIONS or not path.stem.endswith(UPSCALE_SUFFIX):
        return None
    return path.stem.removesuffix(UPSCALE_SUFFIX)


def _predates(video: Path, upscale: Path) -> bool:
    try:
        written, upscaled = video.stat(), upscale.stat()
    except OSError:
        return False
    # Some upscales leave the encoder dated 1970, so an upscale is timed by when
    # its file was made rather than by when it was last written.
    return written.st_mtime <= getattr(upscaled, "st_birthtime", upscaled.st_mtime)
