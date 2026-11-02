from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from funestra.loop_cycle import SEED

from origenerator.slideshow import Slide

Cell = tuple[str, int]
CORNER: Cell = ("corner", 0)


class NavMapRow(NamedTuple):
    slide: Slide
    label: str
    configuration: bool = False


@dataclass(frozen=True)
class NavMapNeighbors:
    seeds: tuple[Slide, ...] = ()
    column: tuple[NavMapRow, ...] = ()
    label: str = ""
    group: tuple[Slide, ...] = ()


NO_NEIGHBORS = NavMapNeighbors()


@dataclass(frozen=True)
class Loop:
    axis: str
    pool: tuple[Slide, ...]

    def position_of(self, slide: Slide) -> int | None:
        for index, held in enumerate(self.pool):
            if held is slide or (held.prompt_id is not None
                                 and held.prompt_id == slide.prompt_id):
                return index
        return None


@dataclass(frozen=True)
class NavMap:
    corner: Slide
    seeds: tuple[Slide, ...]
    column: tuple[NavMapRow, ...]
    playing: Cell
    loop: str
    label: str

    @property
    def actions(self) -> tuple[Slide, ...]:
        return tuple(row.slide for row in self.column)

    def cells(self) -> tuple[Slide, ...]:
        return (self.corner, *self.seeds, *self.actions)


def build_nav_map(current: Slide, loop: Loop | None,
              neighbors_of: Callable[[str | None], NavMapNeighbors]) -> NavMap:
    at = loop.position_of(current) if loop is not None else None
    if loop is None or at is None:
        around = neighbors_of(current.prompt_id)
        return NavMap(current, around.seeds, around.column, CORNER, "",
                            around.label)
    anchor = loop.pool[0]
    playing = CORNER if at == 0 else (loop.axis, at - 1)
    at_anchor = neighbors_of(anchor.prompt_id)
    if loop.axis == SEED:
        lit = neighbors_of(current.prompt_id)
        return NavMap(anchor, loop.pool[1:], lit.column, playing, loop.axis,
                            at_anchor.label)
    column = tuple(NavMapRow(slide, neighbors_of(slide.prompt_id).label)
                   for slide in loop.pool[1:])
    return NavMap(anchor, at_anchor.seeds, column, playing, loop.axis,
                        at_anchor.label)


def actions_posted(query: str) -> str:
    return " ".join(str(query or "").replace("_", " ").split()).lower()


def step_in_ring(cells: tuple[Slide, ...], at: int, step: int) -> Slide | None:
    if len(cells) <= 1:
        return None
    return cells[(at + step) % len(cells)]
