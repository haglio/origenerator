from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from origenerator.config import EVOLVER_INBOX_DIR


@dataclass(frozen=True)
class EvolverInbox:
    inbox_dir: Path

    def hand_over(self, video: Path, source: str, *, funscript: Path | None = None) -> Path:
        if not source:
            raise ValueError("that lane has no folder to send to")
        return export_video(video, Path(self.inbox_dir) / source, funscript=funscript)

    def holds(self, video: Path, source: str) -> bool:
        folder = Path(self.inbox_dir) / source
        return folder.is_dir() and any(_a_copy_of(Path(video), waiting.name)
                                       for waiting in folder.iterdir())


def default_inbox() -> EvolverInbox:
    return EvolverInbox(EVOLVER_INBOX_DIR)


def export_video(src: Path, dest_dir: Path, *, funscript: Path | None = None) -> Path:
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


# Evolver skips any name containing this marker, per evolver_contract.json, so it goes between the stem and the extension.
PARTIAL_MARKER = ".partial."


def partial_name(final: Path) -> Path:
    return final.with_name(f"{final.stem}{PARTIAL_MARKER}{final.suffix.lstrip('.')}")


FUNSCRIPT_SUFFIX = ".funscript"


def _unique_path(path: Path) -> Path:
    def taken(candidate: Path) -> bool:
        return candidate.exists() or candidate.with_suffix(FUNSCRIPT_SUFFIX).exists()

    n = 2
    candidate = path
    while taken(candidate):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def _a_copy_of(video: Path, name: str) -> bool:
    return name == video.name or re.fullmatch(
        rf"{re.escape(video.stem)} \(\d+\){re.escape(video.suffix)}", name) is not None
