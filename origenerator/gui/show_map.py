"""The map a show's HUD draws around the slide on screen, and the loop that
holds it still.

The players' map is a gamma: the clip on screen in the corner, its seed row
running right, its column running down, one cell lit for what is playing.  A
show draws the same gamma over its own generations — the seed row is the same
configuration under other seeds, the column the same seed under other
configurations (:mod:`origenerator.nav_map` says which is which) — and the
map hangs on whatever is on screen until a loop is started along one of its
axes, when it hangs on the slide the loop began on and the lit cell walks the
axis instead.

Qt-free records and one pure function.  :class:`~origenerator.gui.show_set.ShowSet`
keeps the loop and asks for the map; the gallery supplies the neighbors.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from origenerator.slideshow import Slide

# The two axes of the map, and what the loop key steps through: the row, then
# the column, then off.  "" is the off stop, and where a show that is not
# looping already stands, so the first press starts a seed loop.
SEED_AXIS = "seed"
CONFIG_AXIS = "config"
LOOP_CYCLE: tuple[str, ...] = (SEED_AXIS, CONFIG_AXIS, "")

Cell = tuple[str, int]  # ("corner", 0) | ("seed", i) | ("config", i)
CORNER: Cell = ("corner", 0)


@dataclass(frozen=True)
class MapNeighbors:
    """What the library says about one generation: the slides that share its
    configuration (the seed row) and its seed (the config column), what its own
    row is labeled, and what each configuration down the column is called."""

    seeds: tuple[Slide, ...] = ()
    configs: tuple[Slide, ...] = ()
    label: str = ""
    config_labels: tuple[str, ...] = ()


NO_NEIGHBORS = MapNeighbors()


@dataclass(frozen=True)
class Loop:
    """A set played round and round along one axis of the map: which axis, and
    the slides in it with the one it began on first."""

    axis: str
    pool: tuple[Slide, ...]

    def position_of(self, slide: Slide | None) -> int | None:
        """Where *slide* sits in the pool, or ``None`` off it."""
        if slide is None:
            return None
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
    configs: tuple[Slide, ...]
    playing: Cell
    loop: str
    label: str
    config_labels: tuple[str, ...]

    def cells(self) -> tuple[Slide, ...]:
        return (self.corner, *self.seeds, *self.configs)


def build_map(current: Slide, loop: Loop | None,
              neighbors_of: Callable[[str | None], MapNeighbors]) -> ShowMap:
    """The map around *current* — held on it, or on the slide *loop* began on.

    A running loop keeps the map where it started and walks the lit cell along
    the looped axis, so the row does not re-orient as it plays.  The column
    belongs to the lit seed rather than to the corner: it is the same seed
    under other configurations, and along the row every seed has its own.
    """
    at = loop.position_of(current) if loop is not None else None
    if loop is None or at is None:
        around = neighbors_of(current.prompt_id)
        return ShowMap(current, around.seeds, around.configs, CORNER, "",
                       around.label, around.config_labels)
    anchor = loop.pool[0]
    playing = CORNER if at == 0 else (loop.axis, at - 1)
    at_anchor = neighbors_of(anchor.prompt_id)
    if loop.axis == SEED_AXIS:
        lit = neighbors_of(current.prompt_id)
        return ShowMap(anchor, loop.pool[1:], lit.configs, playing, loop.axis,
                       at_anchor.label, lit.config_labels)
    labels = tuple(neighbors_of(slide.prompt_id).label for slide in loop.pool[1:])
    return ShowMap(anchor, at_anchor.seeds, loop.pool[1:], playing, loop.axis,
                   at_anchor.label, labels)


def label_query(label: str) -> str:
    """*label* as the players' HUD posts it when its row's filter button is
    pressed: lower-cased, its spaces collapsed and then written as
    underscores — the one spelling a show has to recognize a row by."""
    return "_".join(str(label or "").split()).lower()


def step_in_ring(cells: tuple[Slide, ...], at: int, step: int) -> Slide | None:
    """The slide *step* places from *at* along a ring of *cells* with the corner
    at its head, or ``None`` on a ring of the corner alone, which has nowhere
    to go.  *at* is 0 for the corner and ``i + 1`` for the axis's *i*-th cell."""
    if len(cells) < 2:
        return None
    return cells[(at + step) % len(cells)]
