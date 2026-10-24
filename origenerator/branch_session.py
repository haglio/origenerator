"""What a run out of a branch worktree still leaves to the live app.

``launch_preview_branch.vbs`` in a worktree runs that branch's code as its own
instance, on the live install's own library (the database in :data:`origenerator.config.
LIBRARY_STATE_DIR`, the thumbnails and trash in the library's app_data folder), so every instance
shows every generation whichever of them made it. What such a session must not
do is hand the *shared ComfyUI* work for the coming absence -- background
experiments and base re-renders (:mod:`origenerator.downtime`) -- or clear
the absence work the live app
queued: those outlive the preview in a queue only the app that queued them can
account for.

``ORIGENERATOR_BRANCH_SESSION=1`` in the environment is what marks one; the
preview launcher sets it, and the primary's launcher never does.
"""

from __future__ import annotations

import os
from pathlib import Path

from shared_ui.preview import Preview, preview_of

ENV_FLAG = "ORIGENERATOR_BRANCH_SESSION"
LAUNCHER = "launch_preview_branch.vbs"


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"


def shown_as(checkout: Path) -> Preview | None:
    """What the copy running out of ``checkout`` shows itself as: a preview,
    named after the session whose branch it is, or ``None`` for the production
    app -- which is what decides its ink, its title and its taskbar group."""
    return preview_of(checkout) if is_branch_session() else None
