"""The upscale Evolver makes of a video sent to it, found where Evolver files it.

Evolver writes it to ``<orientation>/<source>/<name>_topaz.mp4`` under
``upscaled_by_orientation`` (Evolver's ``util/sidecar.upscaled_video_path``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from origenerator.media import media_type_from_filename

UPSCALE_SUFFIX = "_topaz"
ORIENTATIONS = ("landscape", "portrait")


@dataclass(frozen=True)
class EvolverUpscales:
    by_stem: dict[str, Path]

    @classmethod
    def scan(cls, upscaled_dir, source: str) -> EvolverUpscales:
        found = {}
        for orientation in ORIENTATIONS:
            folder = Path(upscaled_dir) / orientation / source
            if folder.is_dir():
                found.update((stem, path) for path in folder.iterdir()
                             if (stem := original_stem(path)) is not None)
        return cls(found)

    def upscale_of(self, video) -> Path | None:
        video = Path(video)
        upscale = self.by_stem.get(video.stem)
        if (upscale is None or media_type_from_filename(video.name) != "video"
                or not _predates(video, upscale)):
            return None
        return upscale


def original_stem(path) -> str | None:
    path = Path(path)
    if path.parent.parent.name not in ORIENTATIONS or not path.stem.endswith(UPSCALE_SUFFIX):
        return None
    return path.stem.removesuffix(UPSCALE_SUFFIX)


def _predates(video: Path, upscale: Path) -> bool:
    try:
        return video.stat().st_mtime <= upscale.stat().st_mtime
    except OSError:
        return False
