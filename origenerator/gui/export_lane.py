"""The lanes a finished clip is handed down to a sibling app.

One :class:`ExportLane` per lane, and :data:`EXPORT_LANES` is all of them, in
the order their buttons sit in the config tab's bank.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtWidgets import QPushButton

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
    """

    name: str
    source: str
    flag: str
    mark: Callable[[Database, str], None]
    noun: str
    tooltip: str
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


# In the order they sit in the button bank.
EXPORT_LANES = (
    ExportLane(
        name="Evolver", source=EVOLVER_SOURCE, flag="evolver_exported_at",
        mark=lambda db, prompt_id: db.mark_evolver_exported(prompt_id),
        noun="video",
        tooltip="Copy this video into Evolver's inbox for sorting and upscaling.",
    ),
    ExportLane(
        name="Genau", source=GENAU_SOURCE, flag="genau_exported_at",
        mark=lambda db, prompt_id: db.mark_genau_exported(prompt_id),
        noun="clip",
        tooltip="Send this clip down the Genau lane: Evolver upscales it on its "
                "usual schedule, then delivers it to the folder Genau plays from.",
    ),
)
