from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app_support.video_names import UPSCALE_SUFFIX

from origenerator.media import MediaType, media_type_from_filename

SHAPES = ("landscape", "portrait")


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
    for shape in SHAPES:
        folder = Path(upscaled_dir) / shape
        sources = sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
        for source in sources:
            filed.extend((source.name, path) for path in _filed_in(source))
    return filed


def filed_under(upscaled_dir, video) -> str | None:
    try:
        shape, source, *_inside = Path(video).relative_to(upscaled_dir).parts
    except ValueError:
        return None
    return source if shape in SHAPES and _inside else None


def _filed_in(source: Path) -> list[Path]:

    return sorted(source.iterdir())


def original_stem(path) -> str | None:
    path = Path(path)
    if path.parent.parent.name not in SHAPES or not path.stem.endswith(UPSCALE_SUFFIX):
        return None
    return path.stem.removesuffix(UPSCALE_SUFFIX)


def _predates(video: Path, upscale: Path) -> bool:
    try:
        written, upscaled = video.stat(), upscale.stat()
    except OSError:
        return False
    return written.st_mtime <= getattr(upscaled, "st_birthtime", upscaled.st_mtime)
