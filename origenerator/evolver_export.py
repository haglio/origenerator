"""Copy a video into the Evolver pipeline's inbox.

Evolver is a sibling app that watches ``0_inbox/<source>/`` and ingests any
*finalized* video it finds there. This module is the Origenerator side of that
handoff: it copies a gallery video into a given inbox folder.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def export_video(src: Path, dest_dir: Path) -> Path:
    """Copy ``src`` into ``dest_dir`` and return the final destination path.

    The copy lands under a ``.partial.`` name and is renamed into place only
    once complete. Evolver skips any file whose name contains ``.partial.``, so
    it never ingests a half-written video; the rename is atomic within the dir.
    """
    src = Path(src)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = _unique_path(dest_dir / src.name)
    partial = _partial_name(final)
    shutil.copy2(src, partial)
    os.replace(partial, final)
    return final


def _partial_name(final: Path) -> Path:
    """A sibling of ``final`` marked ``.partial.`` so Evolver ignores it mid-copy."""
    return final.with_name(f"{final.stem}.partial{final.suffix}")


def _unique_path(path: Path) -> Path:
    """``path`` if free, else the same name with a `` (2)``, ``(3)``… suffix.

    Keeps an export from overwriting a video already waiting in the inbox.
    """
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1
