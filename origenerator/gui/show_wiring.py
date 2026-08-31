"""What a show is handed when it opens: the acts it can ask for, and the facts
its HUD reads off the set.

:class:`~origenerator.gui.slideshow_view.SlideshowView` took nineteen
constructor arguments. Six were callbacks back into the gallery and three were
the players' HUD's description of the set, and neither group ever travelled
alone: the six are passed at exactly one place and always all six, and the three
go together at every caller that passes any of them. Written out one argument at
a time they read as nine unrelated knobs, and a caller could set the order
without the loop — which is the pair that has to move together, because a set
listed in its own order that says it is looping is the HUD making something up.

Both are frozen. They describe how a show was opened; a caller wanting different
answers opens a different show, or retunes this one with a fresh record.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShowActions:
    """What a press on a show asks the gallery to do on its behalf.

    A show owns what happens to the slide *on screen* — the hold, the step, the
    cull off its own pass — but not what happens to the generation behind it,
    which lives in a database the show has never seen. Each of these is that
    second half, and each is optional: a show handed none of them still answers
    every key, it just asks nobody. That is what a test's show gets, and what a
    show standing outside a session gets for the two that are a session's.

    ``delete`` and ``star`` take the slide's prompt_id. ``enhance`` takes one
    too and answers whether a run actually started, which is what the corner
    note goes on to say. ``lock`` takes one and is a session's: it opens the
    held item as a generate tab. ``reset`` takes the show itself and is a
    session's too — hosted, "how it started" is the REGION's base state, which
    only the gallery knows. ``drive_toggle`` takes nothing: Space goes to the
    app's one OSR2 switch rather than straight to this show's stroke.
    """

    delete: Callable[[str], None] | None = None
    enhance: Callable[[str], bool] | None = None
    star: Callable[[str], None] | None = None
    lock: Callable[[str], None] | None = None
    reset: Callable[[object], None] | None = None
    drive_toggle: Callable[[], None] | None = None


@dataclass(frozen=True)
class HudFacts:
    """What this show's own HUD says about the set it is playing.

    All three are the players' vocabulary, because the panel is the players'
    panel: ``order_label`` is how the set is ordered (Recents plays "Latest",
    everything else "Shuffle", and a folder opened in the browser's own order
    says nothing at all rather than making one up); ``looping`` is whether this
    is a LOOP as a player means it, a set someone asked for played round and
    round, which a region's base state is not; ``starred_ids`` is which of the
    items are favorites, so the star readout and the F-mode narrowing mean here
    what they mean on a player.

    The defaults are a shuffled loop with nothing starred — a show asked for by
    the toolbar, which is the ordinary case.
    """

    order_label: str = "Shuffle"
    looping: bool = True
    starred_ids: Collection[str] = field(default_factory=frozenset)
