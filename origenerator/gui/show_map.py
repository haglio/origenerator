"""The map a show's HUD draws around the slide on screen, and the loop that
holds it still.

The players' map is a gamma: the clip on screen in the corner, its seed row
running right, its column running down, one cell lit for what is playing.  A
show draws the same gamma over its own generations — the seed row is the same
act under other seeds, the column what else was made of the same picture
(:mod:`origenerator.nav_map` says which is which) — and the
map hangs on whatever is on screen until a loop is started along one of its
axes, when it hangs on the slide the loop began on and the lit cell walks the
axis instead.

Qt-free records and one pure function.  :class:`~origenerator.gui.show_set.ShowSet`
keeps the loop and asks for the map; the gallery supplies the neighbors.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from origenerator.slideshow import Slide

# The two axes of the map, and what the loop key steps through: the row, then
# the column, then off.  "" is the off stop, and where a show that is not
# looping already stands, so the first press starts a seed loop.
SEED_AXIS = "seed"
ACTION_AXIS = "action"
LOOP_CYCLE: tuple[str, ...] = (SEED_AXIS, ACTION_AXIS, "")

Cell = tuple[str, int]  # ("corner", 0) | ("seed", i) | ("action", i)
CORNER: Cell = ("corner", 0)


class MapRow(NamedTuple):
    """One row down the column: the slide it draws, the name in its gutter, and
    whether that name is a configuration's folder rather than an act.

    The two are pressed differently — a configuration's button jumps to it and
    loops its seed row, an act's narrows the show to that act — so which it is
    travels with the row rather than being guessed from the words.
    """

    slide: Slide
    label: str
    configuration: bool = False


@dataclass(frozen=True)
class MapNeighbors:
    """What the library says about one generation: the slides showing its act
    under other seeds (the seed row), the column of rows under it — the same
    seed under other configurations, then what else was made of its picture —
    the act its own row is named for, and the rest of that picture's whole
    group, which is what a loop down the column plays."""

    seeds: tuple[Slide, ...] = ()
    column: tuple[MapRow, ...] = ()
    label: str = ""
    group: tuple[Slide, ...] = ()


NO_NEIGHBORS = MapNeighbors()


@dataclass(frozen=True)
class Loop:
    """A set played round and round along one axis of the map: which axis, and
    the slides in it with the one it began on first."""

    axis: str
    pool: tuple[Slide, ...]

    def position_of(self, slide: Slide) -> int | None:
        """Where *slide* sits in the pool, or ``None`` off it."""
        for index, held in enumerate(self.pool):
            if held is slide or (held.prompt_id is not None
                                 and held.prompt_id == slide.prompt_id):
                return index
        return None


@dataclass(frozen=True)
class ShowMap:
    """The gamma the HUD draws: the corner, the row, the column, the lit cell,
    the loop lighting one axis, and the words in the gutter."""

    corner: Slide
    seeds: tuple[Slide, ...]
    column: tuple[MapRow, ...]
    playing: Cell
    loop: str
    label: str

    @property
    def actions(self) -> tuple[Slide, ...]:
        """The slides down the column, in the order it draws them."""
        return tuple(row.slide for row in self.column)

    def cells(self) -> tuple[Slide, ...]:
        return (self.corner, *self.seeds, *self.actions)


def build_map(current: Slide, loop: Loop | None,
              neighbors_of: Callable[[str | None], MapNeighbors]) -> ShowMap:
    """The map around *current* — held on it, or on the slide *loop* began on.

    A running loop keeps the map where it started and walks the lit cell along
    the looped axis, so the row does not re-orient as it plays.  The column
    belongs to the lit seed rather than to the corner: it is what else was
    made of that seed's picture, and along the row every seed has its own.
    """
    at = loop.position_of(current) if loop is not None else None
    if loop is None or at is None:
        around = neighbors_of(current.prompt_id)
        return ShowMap(current, around.seeds, around.column, CORNER, "",
                       around.label)
    anchor = loop.pool[0]
    playing = CORNER if at == 0 else (loop.axis, at - 1)
    at_anchor = neighbors_of(anchor.prompt_id)
    if loop.axis == SEED_AXIS:
        lit = neighbors_of(current.prompt_id)
        return ShowMap(anchor, loop.pool[1:], lit.column, playing, loop.axis,
                       at_anchor.label)
    # A loop down the column plays the whole group, twins of an act included,
    # so every slide in it is a row of its own, named as the library names it.
    column = tuple(MapRow(slide, neighbors_of(slide.prompt_id).label)
                   for slide in loop.pool[1:])
    return ShowMap(anchor, at_anchor.seeds, column, playing, loop.axis,
                   at_anchor.label)


def acts_posted(query: str) -> str:
    """The act(s) a row's filter button posted, put back into words: the
    players' HUD lower-cases the row's label and writes its spaces as
    underscores, and a spoken act arrives the same way."""
    return " ".join(str(query or "").replace("_", " ").split()).lower()


def step_in_ring(cells: tuple[Slide, ...], at: int, step: int) -> Slide | None:
    """The slide *step* places from *at* along a ring of *cells* with the corner
    at its head, or ``None`` on a ring of the corner alone, which has nowhere
    to go.  *at* is 0 for the corner and ``i + 1`` for the axis's *i*-th cell."""
    if len(cells) < 2:
        return None
    return cells[(at + step) % len(cells)]
