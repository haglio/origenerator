"""Copy a video, and its funscript, into the Evolver pipeline's inbox.

Evolver is a sibling app that watches ``0_inbox/<source>/`` and ingests any
*finalized* video it finds there. This module is the Origenerator side of that
handoff: it copies a gallery video into a given inbox folder.

The folder is the whole message. Evolver routes by source name, so both of this
app's lanes come through here and differ only in which one they are given: a
plain video goes to the library lane, a Genau loop to the lane whose upscaled
output Evolver delivers to Genau's clips folder.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from origenerator.config import EVOLVER_INBOX_DIR


@dataclass(frozen=True)
class EvolverInbox:
    """Where this app hands a finished clip over, and the only thing that knows.

    The destination used to be a config constant that two Qt widgets reached for
    in the middle of a send, so the one fact the whole hand-off turns on -- which
    folder -- was written in no single place, and the only way to point a test
    somewhere else was to patch the module each of them had imported it from.
    One of these is built where the app is put together and handed to whoever
    sends, so a view asks for a hand-off instead of performing one.
    """

    inbox_dir: Path

    def hand_over(self, video: Path, source: str, *, funscript: Path | None = None) -> Path:
        """Copy *video*, with its *funscript*, into the folder Evolver routes *source* by.

        A lane with no folder is refused rather than dropped in the inbox root,
        where Evolver -- which routes by folder and nothing else -- would read it
        as belonging to no source at all.
        """
        if not source:
            raise ValueError("that lane has no folder to send to")
        return export_video(video, Path(self.inbox_dir) / source, funscript=funscript)


def default_inbox() -> EvolverInbox:
    """The inbox this app sends to, for whoever is not given one."""
    return EvolverInbox(EVOLVER_INBOX_DIR)


def export_video(src: Path, dest_dir: Path, *, funscript: Path | None = None) -> Path:
    """Copy ``src``, with *funscript* under its name, into ``dest_dir``; where it landed.

    Each copy wears :data:`PARTIAL_MARKER`, which Evolver skips, until all are complete.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = _unique_path(dest_dir / Path(src).name)
    copies = [(Path(src), final)]
    if funscript is not None:
        copies.append((Path(funscript), final.with_suffix(FUNSCRIPT_SUFFIX)))
    try:
        for source, destination in copies:
            shutil.copy2(source, partial_name(destination))
    except BaseException:
        for _, destination in copies:
            partial_name(destination).unlink(missing_ok=True)
        raise
    for _, destination in copies:
        os.replace(partial_name(destination), destination)
    return final


#: What Evolver walks past while a copy is still being written. Its own
#: spelling, published in ``evolver_contract.json``; matched anywhere in the
#: name, so it goes between the stem and the extension.
PARTIAL_MARKER = ".partial."


def partial_name(final: Path) -> Path:
    """A sibling of ``final`` wearing :data:`PARTIAL_MARKER`, so Evolver ignores
    it mid-copy."""
    return final.with_name(f"{final.stem}{PARTIAL_MARKER}{final.suffix.lstrip('.')}")


FUNSCRIPT_SUFFIX = ".funscript"


def _unique_path(path: Path) -> Path:
    """``path`` if free, else the same name with a `` (2)``, ``(3)``… suffix.

    Keeps an export from overwriting a video, or its funscript, waiting in the inbox.
    """
    def taken(candidate: Path) -> bool:
        return candidate.exists() or candidate.with_suffix(FUNSCRIPT_SUFFIX).exists()

    n = 2
    candidate = path
    while taken(candidate):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate
