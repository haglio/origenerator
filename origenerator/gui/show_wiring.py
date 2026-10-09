"""What a show is handed when it opens: the acts it can ask for, and the facts
its HUD reads off the set.

:class:`~origenerator.gui.slideshow_view.SlideshowView` took nineteen
constructor arguments. Six were callbacks back into the gallery and three were
the players' HUD's description of the set, and neither group ever travelled
alone: the six are passed at exactly one place and always all six, and the three
go together at every caller that passes any of them. Written out one argument at
a time they read as nine unrelated settings, and a caller could set the order
without the loop — which is the pair that has to move together, because a set
listed in its own order that says it is looping is the HUD making something up.

Both are frozen. They describe how a show was opened; a caller wanting different
answers opens a different show, or retunes this one with a fresh record.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from player_core.hud_status import SHUFFLE_LABEL

from origenerator.slideshow import ShowFilters


@dataclass(frozen=True)
class ShowActions:
    """What a press on a show asks the gallery to do on its behalf.

    A show owns what happens to the slide *on screen* — the hold, the step, the
    cull off its own pass — but not what happens to the generation under it,
    which lives in a database the show has never seen. Each of these is that
    second half, and each is optional: a show handed none of them still answers
    every key, it just asks nobody. That is what a test's show gets, and what a
    show standing outside a session gets for the three that are a session's.

    ``delete``, ``favorite`` and ``unfavorite`` take the slide's prompt_id. ``enhance``
    takes one too and answers whether a run actually started, which is what
    the corner note goes on to say. ``lock`` takes one and is a session's: it
    opens the held item as a generate tab. ``reset`` takes the show itself and
    is a session's too — hosted, "how it started" is the REGION's base state,
    which only the gallery knows. ``reorder`` takes the show and whether to play
    its side's library newest first; ``browse_all`` takes the show alone and
    plays that library in the order it is in. ``drive_toggle`` takes nothing: Space goes to
    the app's one OSR2 switch rather than straight to this show's motion, and
    ``osr2_control`` is that same switch handed over whole, which is what the
    console's four control buttons read and set.
    ``omnipause`` takes nothing: a click on the picture asks the room to pause,
    the hosting session's or this app's own, and a show handed none pauses
    itself.

    ``neighbors`` and ``widen`` take a prompt_id and answer for the library
    the show cannot see: what shows that generation's act under other seeds
    and what else was made of its picture (the map's two axes, as
    :class:`~origenerator.gui.show_map.MapNeighbors`), and what lies just
    beyond the row (the slides "more seeds" adds to it).  ``acts`` takes
    prompt_ids and answers what each one's map row is named for, which is
    what an act filter matches it on.
    """

    delete: Callable[[str], None] | None = None
    enhance: Callable[[str], bool] | None = None
    favorite: Callable[[str], None] | None = None
    unfavorite: Callable[[str], None] | None = None
    lock: Callable[[str], None] | None = None
    reset: Callable[[object], None] | None = None
    reorder: Callable[[object, bool], bool] | None = None
    browse_all: Callable[[object], bool] | None = None
    # The generation queue's own two, for the block the panel hangs at its foot:
    # ``requeue`` takes the ids in the order the rows were dropped into, and
    # ``clear_queue`` drops another app's work off ComfyUI.
    requeue: Callable[[list], None] | None = None
    clear_queue: Callable[[], None] | None = None
    drive_toggle: Callable[[], None] | None = None
    osr2_control: object | None = None
    omnipause: Callable[[], None] | None = None
    move_hud: Callable[[str], None] | None = None
    neighbors: Callable[[str], object] | None = None
    widen: Callable[[str], tuple] | None = None
    acts: Callable[[list], dict] | None = None
    filters_changed: Callable[[ShowFilters], None] | None = None


@dataclass(frozen=True)
class HudFacts:
    """What this show's own HUD says about the set it is playing.

    All of it is the players' vocabulary, because the panel is the players'
    panel: ``order_label`` is how the set is ordered — "Latest" for Recents and
    for a folder opened on one of its pictures, both of which play newest
    first, and "Shuffle" for everything else; ``favorite_ids`` is which of
    the items are favorites, so the star readout and the F-mode narrowing mean
    here what they mean on a player.  Whether the show is LOOPING is not a
    fact about the set at all: a loop is one axis of the map played round and
    round, started and ended from the show, and the set is what it browses
    between loops.

    The defaults are a shuffled set with nothing favorited — a show asked for by
    the toolbar, which is the ordinary case.
    """

    order_label: str = SHUFFLE_LABEL
    favorite_ids: Collection[str] = field(default_factory=frozenset)
    # Which of the items carry an enhancement, for the switch beside F-mode
    # that only a show's HUD grows: the same shape as the favorites, over the
    # same set, and followed the same way as enhancements land.
    enhanced_ids: Collection[str] = field(default_factory=frozenset)
    enhancing: Mapping[str, str] = field(default_factory=dict)
