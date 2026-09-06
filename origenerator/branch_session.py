"""What a run out of a branch worktree still leaves to the live app.

``launch_preview_branch.vbs`` in a worktree runs that branch's code as its own
instance, on the live install's own library (:data:`origenerator.config.
LIBRARY_STATE_DIR`): the same database, thumbnails and trash, so every instance
shows every generation whichever of them made it. What such a session must not
do is hand the *shared ComfyUI* work for the coming absence -- background
experiments and base re-renders (``GalleryView.queue_experiments_for_absence``,
``queue_base_renders_for_absence``) -- or clear the absence work the live app
queued: those outlive the preview in a queue only the app that queued them can
account for.

``ORIGENERATOR_BRANCH_SESSION=1`` in the environment is what marks one; the
preview launcher sets it, and the primary's launcher never does.
"""

from __future__ import annotations

import os

from origenerator.config import BRANCH_SESSION_FLAG as ENV_FLAG


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"
