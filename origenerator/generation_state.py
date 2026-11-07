from __future__ import annotations

from enum import StrEnum


class GenerationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class GenerationSource(StrEnum):
    GENERATED = "generated"
    IMPORTED = "imported"
    EXPERIMENT = "experiment"
    BASE_RENDER = "base_render"
    STROKE_TRIM = "stroke_trim"
    OUTSIDE = "outside"
    STARTING_FRAME = "starting_frame"
    LEFT_OUT = "left_out"
    REPLACED = "replaced"


MADE_ELSEWHERE = (GenerationSource.OUTSIDE, GenerationSource.STARTING_FRAME,
                  GenerationSource.LEFT_OUT)
OUT_OF_SIGHT = (GenerationSource.STARTING_FRAME, GenerationSource.LEFT_OUT,
                GenerationSource.REPLACED)
UNLISTED = (GenerationSource.LEFT_OUT, GenerationSource.REPLACED)


def source_of(row: dict) -> str:
    return row.get("source") or GenerationSource.GENERATED


def made_here(row: dict) -> bool:
    return source_of(row) not in MADE_ELSEWHERE


def in_sight(row: dict) -> bool:
    return source_of(row) not in OUT_OF_SIGHT


def on_the_map(row: dict) -> bool:
    return in_sight(row) or source_of(row) == GenerationSource.STARTING_FRAME
