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


def source_of(row: dict) -> str:
    return row.get("source") or GenerationSource.GENERATED
