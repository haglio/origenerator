"""The lanes a finished clip is handed down to a sibling app.

One :class:`ExportLane` per lane, and :data:`EXPORT_LANES` is all of them, in
the order their buttons sit in the config tab's bank.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QPushButton

from origenerator import stroke_trim
from origenerator.config import EVOLVER_SOURCE, GENAU_SOURCE
from origenerator.db import Database


@dataclass(frozen=True)
class ExportLane:
    """One outbound lane: a folder in Evolver's inbox, a column on the row, and
    the words its button and its failure wear.

    Both lanes are the same errand — copy the clip on display into the inbox
    Evolver watches, then stamp the row so the send survives a restart — and
    they differ in nothing but the fields below. Written out twice they were
    fifty lines of code with four literals swapped, and the panel's own docstring
    said so; a third lane would have been a third copy. It is a row of this
    table now.

    ``source`` is the sub-folder Evolver reads the destination from, so it is a
    name agreed with another repo and must stay spelled exactly as
    :mod:`origenerator.config` has it. ``flag`` is the persisted column and
    ``mark`` stamps it — two halves of one fact, spelled apart, which is why a
    test pins that every lane's pair agrees. ``mark`` names the database method
    outright rather than by a string the panel would have to look up: reached by
    name, a stamp nothing else calls reads as dead code and is deleted by the
    next person to run the scan. ``noun`` is what the failure dialog calls the
    file: the two lanes call the same file a video and a clip, and each says it
    in the words of the app it is bound for.
    ``single_stroke`` is the one difference that is not a word: a lane that wants
    one stroke is handed a CUT of the clip rather than the clip (see
    :meth:`clip_for` and :mod:`origenerator.stroke_trim`). It is a field here,
    beside the folder and the column, because the two callers that hand a clip
    down a lane -- the button, and the spoken "genau it" that sends without one --
    must not be able to disagree about it.
    """

    name: str
    source: str
    flag: str
    mark: Callable[[Database, str], None]
    noun: str
    tooltip: str
    single_stroke: bool = False
    # The button this lane wears, filled in per panel when the bank is built
    # (see :meth:`GenerateConfigPanel._build_ui`). ``None`` on the table's own
    # rows, which describe the lanes rather than any one panel's buttons.
    button: QPushButton | None = None

    @property
    def send_caption(self) -> str:
        return f"Send to {self.name}"

    @property
    def sent_caption(self) -> str:
        return f"Sent to {self.name} ✓"

    @property
    def failure_title(self) -> str:
        return f"Send to {self.name} failed"

    def failure_body(self, error) -> str:
        return f"Could not send this {self.noun} to {self.name}:\n\n{error}"

    def clip_for(self, row: dict, video_path, db, *, output_dir, thumb_dir) -> Path:
        """The file this lane is actually handed for ``row``.

        The clip itself for a lane that plays what it is given, and one stroke
        cut out of it for a lane that scrubs what it is given against a device
        (:func:`origenerator.stroke_trim.single_stroke_clip`, which raises rather
        than falling back -- a lane asking for one stroke must never be handed
        four). The cut is a video in the gallery of its own, so this both writes
        a file and adds a row.
        """
        if not self.single_stroke:
            return Path(video_path)
        return stroke_trim.single_stroke_clip(
            row, video_path, db, output_dir=output_dir, thumb_dir=thumb_dir)


EVOLVER = ExportLane(
    name="Evolver", source=EVOLVER_SOURCE, flag="evolver_exported_at",
    mark=lambda db, prompt_id: db.mark_evolver_exported(prompt_id),
    noun="video",
    tooltip="Copy this video into Evolver's inbox for sorting and upscaling.",
)

GENAU = ExportLane(
    name="Genau", source=GENAU_SOURCE, flag="genau_exported_at",
    mark=lambda db, prompt_id: db.mark_genau_exported(prompt_id),
    noun="clip",
    # Genau scrubs a clip against the device's phase, so it reads whatever it is
    # given as exactly one stroke; a whole generated loop holds however many
    # strokes its frames and its cadence fit, and gets steered as one anyway.
    single_stroke=True,
    tooltip="Send one stroke of this clip down the Genau lane: it is cut down to "
            "a single stroke, Evolver upscales that on its usual schedule, then "
            "delivers it to the folder Genau plays from.",
)

# In the order they sit in the button bank. Named above as well, because the
# spoken "genau it" hands its clip down this lane with no button to read it off.
EXPORT_LANES = (EVOLVER, GENAU)
