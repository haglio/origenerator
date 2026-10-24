"""What a generations row says about itself: where its run has got to, and what
put it there.

Each name stands for the very string the database has always held, so a row
read back compares equal to it and one written stores the same bytes as before --
which is what lets Evolver go on reading the table it opens read-only.
"""
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


MADE_ELSEWHERE = (GenerationSource.OUTSIDE, GenerationSource.STARTING_FRAME,
                  GenerationSource.LEFT_OUT)
OUT_OF_SIGHT = (GenerationSource.STARTING_FRAME, GenerationSource.LEFT_OUT)


def source_of(row: dict) -> str:
    return row.get("source") or GenerationSource.GENERATED


def made_here(row: dict) -> bool:
    return source_of(row) not in MADE_ELSEWHERE


def in_sight(row: dict) -> bool:
    return source_of(row) not in OUT_OF_SIGHT
