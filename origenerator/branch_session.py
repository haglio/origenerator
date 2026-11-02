from __future__ import annotations

import os
from pathlib import Path

from shared_ui.preview import Preview, preview_of

ENV_FLAG = "ORIGENERATOR_BRANCH_SESSION"
LAUNCHER = "launch_preview_branch.vbs"


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"


def shown_as(checkout: Path) -> Preview | None:
    return preview_of(checkout) if is_branch_session() else None
