"""What a slideshow is handed when it opens: the acts it can ask for, and the facts
its HUD reads off the set.

:class:`~origenerator.gui.slideshow_view.SlideshowView` took nineteen
constructor arguments. Six were callbacks back into the gallery and three were
the Funestras' HUD's description of the set, and neither group ever travelled
alone: the six are passed at exactly one place and always all six, and the three
go together at every caller that passes any of them. Written out one argument at
a time they read as nine unrelated settings, and a caller could set the order
without the loop — which is the pair that has to move together, because a set
listed in its own order that says it is looping is the HUD making something up.

Both are frozen. They describe how a slideshow was opened; a caller wanting different
answers opens a different slideshow, or retunes this one with a fresh record.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from funestra.hud_title import SHUFFLE_LABEL
from funestra.volume import VolumeHud

from origenerator.slideshow import SlideshowFilters


@dataclass(frozen=True)
class SlideshowActions:
    """What a press on a slideshow asks the gallery to do on its behalf.

    A slideshow owns what happens to the slide *on screen* — the hold, the step, the
    cull off its own pass — but not what happens to the generation under it,
    which lives in a database the slideshow has never seen. Each of these is that
    second half, and each is optional: a slideshow handed none of them still answers
    every key, it just asks nobody. That is what a test's slideshow gets, and what a
    Standalone slideshow gets for the three that are a session's.

    ``delete``, ``favorite`` and ``unfavorite`` take the slide's prompt_id. ``enhance``
    takes one too and answers whether a run actually started, which is what
    the corner note goes on to say. ``lock`` takes one and is a session's: it
    opens the held item as a generate tab. ``reset`` takes the slideshow itself and
    is a session's too — hosted, "how it started" is the REGION's base state,
    which only the gallery knows. ``reorder`` takes the slideshow and whether to play
    its side's library newest first; ``browse_all`` takes the slideshow alone and
    plays that library in the order it is in. ``drive_toggle`` takes nothing: Space goes to
    the app's one OSR2 switch rather than straight to this slideshow's motion, and
    ``osr2_control`` is that same switch handed over whole, which is what the
    console's four control buttons read and set.
    ``omnipause`` takes nothing: a click on the slide asks the room to pause,
    the hosting session's or this app's own, and a slideshow handed none pauses
    itself.

    ``neighbors`` and ``widen`` take a prompt_id and answer for the library
    the slideshow cannot see: what shows that generation's act under other seeds
    and what else was made of its image (the map's two axes, as
    :class:`~origenerator.gui.slideshow_map.MapNeighbors`), and what lies just
    beyond the row (the slides "more seeds" adds to it).  ``acts`` takes
    prompt_ids and answers what each one's map row is named for, which is
    what an act filter matches it on, and ``slides`` the slides they play as,
    which a loop picked back up plays whatever set it reopened on.

    ``volume_moved`` takes the volume the viewer moved the slideshow's
    Funestra to.  In Standalone, that is Origenerator Radio's volume
    too, so a move of it turns the Radio on, and the next slideshow opens at it.
    """

    delete: Callable[[str], None] | None = None
    enhance: Callable[[str], bool] | None = None
    favorite: Callable[[str], None] | None = None
    unfavorite: Callable[[str], None] | None = None
    lock: Callable[[str], None] | None = None
    reset: Callable[[object], None] | None = None
    reorder: Callable[[object, bool], bool] | None = None
    browse_all: Callable[[object], bool] | None = None
    # The block at the HUD's foot: ``queue_now`` what is in it, ``move`` lets a row go
    # just ahead of another (past the last for None), ``clear_queue`` drops another app's
    # work off ComfyUI, ``start_now`` ends a video's wait, ``cancel_all`` asks, then cancels.
    queue_now: Callable[[], tuple[list, int]] | None = None
    move: Callable[[str, str | None], None] | None = None
    clear_queue: Callable[[], None] | None = None
    start_now: Callable[[], None] | None = None
    cancel_all: Callable[[], None] | None = None
    # Core's window, which shows the Job Queue itself whenever it can be seen.
    core_window: Callable[[], object] | None = None
    drive_toggle: Callable[[], None] | None = None
    osr2_control: object | None = None
    omnipause: Callable[[], None] | None = None
    move_hud: Callable[[str], None] | None = None
    neighbors: Callable[[str], object] | None = None
    widen: Callable[[str], tuple] | None = None
    acts: Callable[[list], dict] | None = None
    slides: Callable[[tuple], tuple] | None = None
    filters_changed: Callable[[SlideshowFilters], None] | None = None
    volume_moved: Callable[[VolumeHud], None] | None = None


@dataclass(frozen=True)
class HudFacts:
    """What this slideshow's own HUD says about the set it is playing.

    All of it is the Funestras' vocabulary, because the HUD is the Funestras'
    HUD: ``order_label`` is how the set is ordered — "Latest" for Latest and
    for a folder opened on one of its items, both of which play newest
    first, and "Shuffle" for everything else; ``favorite_ids`` is which of
    the items are favorites, so the star readout and the F-mode narrowing mean
    here what they mean on a Funestra.  Whether the slideshow is LOOPING is not a
    fact about the set at all: a loop is one axis of the map played round and
    round, started and ended from the slideshow, and the set is what it browses
    between loops.

    The defaults are a shuffled set with nothing favorited — a slideshow asked for by
    the toolbar, which is the ordinary case.
    """

    order_label: str = SHUFFLE_LABEL
    favorite_ids: Collection[str] = field(default_factory=frozenset)
    # Which of the items carry an enhancement, for the switch beside F-mode
    # that only a slideshow's HUD grows: the same shape as the favorites, over the
    # same set, and followed the same way as enhancements land.
    enhanced_ids: Collection[str] = field(default_factory=frozenset)
    enhancing: Mapping[str, str] = field(default_factory=dict)
