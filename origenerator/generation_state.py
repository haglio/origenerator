from __future__ import annotations

from enum import StrEnum

from app_support import gallery_rows
from app_support.gallery_rows import source_of


class GenerationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class GenerationSource(StrEnum):
    GENERATED = gallery_rows.GENERATED
    IMPORTED = "imported"
    EXPERIMENT = "experiment"
    BASE_RENDER = "base_render"
    STROKE_TRIM = "stroke_trim"
    OUTSIDE = gallery_rows.OUTSIDE
    STARTING_FRAME = gallery_rows.STARTING_FRAME
    LEFT_OUT = gallery_rows.LEFT_OUT
    REPLACED = "replaced"


MADE_ELSEWHERE = tuple(sorted(GenerationSource(source) for source in gallery_rows.MADE_ELSEWHERE))
OUT_OF_SIGHT = (GenerationSource.STARTING_FRAME, GenerationSource.LEFT_OUT,
                GenerationSource.REPLACED)
UNLISTED = (GenerationSource.LEFT_OUT, GenerationSource.REPLACED)


def in_sight(row: dict) -> bool:
    return source_of(row) not in OUT_OF_SIGHT


def on_the_map(row: dict) -> bool:
    return in_sight(row) or source_of(row) == GenerationSource.STARTING_FRAME
