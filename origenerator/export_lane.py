"""The lanes a finished video is handed down to a sibling app.

One :class:`ExportLane` per lane, :data:`EXPORT_LANES` is all of them, and
:func:`lane_for` is the one lane the Generate tab offers a video.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from origenerator.act_settings import loops
from origenerator.config import EVOLVER_SOURCE, GENAU_SOURCE
from origenerator.db import Database
from origenerator.funscript import funscript_of
from origenerator.gallery import resolve_preview
from origenerator.gallery_contract import LANES
from origenerator.media import MediaType


@dataclass(frozen=True)
class ExportLane:
    """One outbound lane: a folder in Evolver's inbox, a column on the row, and
    the words its button and its failure wear.

    Both lanes are the same errand — copy the video on display into the inbox
    Evolver watches, then stamp the row so the send survives a restart — and
    they differ in nothing but the fields below. Written out twice they were
    fifty lines of code with four literals swapped, and the tab's own docstring
    said so; a third lane would have been a third copy. It is a row of this
    table now.

    ``source`` is the sub-folder Evolver reads the destination from, so it is a
    name agreed with another repo and must stay spelled exactly as
    :mod:`origenerator.config` has it. ``source_key`` is this lane's name in
    :data:`origenerator.gallery_contract.LANES`, which holds the two persisted
    columns — the send and its withdrawal — because the reader on the other
    side selects them by name and they are the promise this repo publishes.
    ``mark`` stamps the first and ``unmark`` the second. Each names the database method
    outright rather than by a string the tab would have to look up: reached by
    name, a stamp nothing else calls reads as dead code and is deleted by the
    next person to run the scan. ``noun`` is what the failure dialog calls the
    file: the two lanes call the same file a video and a clip, and each says it
    in the words of the app it is bound for.
    """

    name: str
    source_key: str
    source: str
    mark: Callable[[Database, str], None]
    unmark: Callable[[Database, str], None]
    noun: str
    tooltip: str
    unsend_tooltip: str
    withdrawn_tooltip: str
    hands_over_funscript: bool
    carries_loops: bool

    @property
    def flag(self) -> str:
        """The column a send is stamped on, from the promise this repo publishes."""
        return LANES[self.source_key]["sent"]

    @property
    def unsent_flag(self) -> str:
        """The column a withdrawal is stamped on, from that same promise."""
        return LANES[self.source_key]["unsent"]

    @property
    def send_caption(self) -> str:
        return f"→ Send to {self.name}"

    @property
    def sent_caption(self) -> str:
        return f"Sent to {self.name}"

    @property
    def failure_title(self) -> str:
        return f"Send to {self.name} failed"

    def failure_body(self, error) -> str:
        return f"Could not send this {self.noun} to {self.name}:\n\n{error}"

    def send(self, video: Path, prompt_id: str, *, db, inbox, places) -> Path:
        funscript = (funscript_of(video, places=places)
                     if self.hands_over_funscript else None)
        landed = inbox.hand_over(video, self.source, funscript=funscript)
        self.mark(db, prompt_id)
        return landed

    def send_video_of(self, row: dict, *, db, inbox, places) -> Path:
        shown = resolve_preview(row, places)
        if shown is None or shown[1] != MediaType.VIDEO:
            raise FileNotFoundError(f"{row['prompt_id']} has no video on disk")
        return self.send(shown[0], row["prompt_id"], db=db, inbox=inbox, places=places)

KINO = ExportLane(
    name="Kino", source_key="evolver", source=EVOLVER_SOURCE,
    mark=lambda db, prompt_id: db.mark_evolver_exported(prompt_id),
    unmark=lambda db, prompt_id: db.mark_evolver_unsent(prompt_id),
    noun="video",
    tooltip="Send this video down the Kino lane: Evolver sorts and upscales it on its usual "
            "schedule, then files it where Kino plays it.",
    unsend_tooltip="Delete the copy Evolver holds, wherever it has filed it by "
                   "now. It goes on Evolver's next run.",
    withdrawn_tooltip="An earlier copy of this video is down for deletion in "
                      "Evolver. Sending puts a fresh one in its inbox.",
    hands_over_funscript=True,
    carries_loops=False,
)

GENAU = ExportLane(
    name="Genau", source_key="genau", source=GENAU_SOURCE,
    mark=lambda db, prompt_id: db.mark_genau_exported(prompt_id),
    unmark=lambda db, prompt_id: db.mark_genau_unsent(prompt_id),
    noun="clip",
    tooltip="Send this clip down the Genau lane: Evolver upscales it on its "
            "usual schedule, then delivers it to the folder Genau plays from.",
    unsend_tooltip="Delete this clip from the folder Genau plays from. Evolver "
                   "does it on its next run.",
    withdrawn_tooltip="An earlier copy of this clip is down for deletion in "
                      "Genau's folder. Sending starts a fresh one down the lane.",
    hands_over_funscript=False,
    carries_loops=True,
)

EXPORT_LANES = (KINO, GENAU)
EXPORT_LANES_BY_KEY = {lane.source_key: lane for lane in EXPORT_LANES}

UNSEND_CAPTION = "Unsend"


def lane_for(row: dict) -> ExportLane:
    own = next(lane for lane in EXPORT_LANES if lane.carries_loops == loops(row))
    holding_a_stray_copy = (lane for lane in EXPORT_LANES
                            if lane is not own and row.get(lane.flag))
    return next(holding_a_stray_copy, own)
