"""Run a session out of a branch worktree, skipping what only the live app does.

``launch_preview_branch.vbs`` in a worktree runs that branch's code as its own
instance with its own ``state/`` — but a fresh state dir made every launch
re-scan ComfyUI's whole output history ("Scanning for new images…" for minutes,
looking crashed) to rebuild a database the primary checkout already has. The
same problem fun_time's branch sessions solved, and the same answer: the
library-derived state is *seeded* from the live install rather than rebuilt,
and the maintenance passes that keep it healthy — the import scan, the
backfills, the reconciles, the trash sweep — are the live app's job alone, so a
branch session skips them (``origenerator.app.main`` gates on
:func:`is_branch_session`).

``ORIGENERATOR_BRANCH_SESSION=1`` in the environment is what marks one; the
preview launcher sets it, and the primary's launcher never does.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

ENV_FLAG = "ORIGENERATOR_BRANCH_SESSION"


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"


def seed_branch_db(primary_db: Path, branch_db: Path) -> bool:
    """Start the branch's database from the primary's, once; return whether it did.

    Copied with sqlite's online backup — the live app may be mid-write, and a
    plain file copy of a hot database can capture a torn page — and never
    written back: a branch is unfinished code, and the live session's library
    is not its to corrupt. Only when the branch has no database of its own yet;
    after that, its state is its own work. A branch that IS the primary (the
    flag set there by mistake) falls out naturally: its database either already
    exists or is the missing source.
    """
    primary_db, branch_db = Path(primary_db), Path(branch_db)
    if branch_db.exists() or not primary_db.exists():
        return False
    branch_db.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{primary_db.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source, \
            closing(sqlite3.connect(branch_db)) as destination:
        source.backup(destination)
    return True
