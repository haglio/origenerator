from __future__ import annotations

import os
from pathlib import Path

from shared_ui.preview import Preview, preview_of, window_title

ENV_FLAG = "ORIGENERATOR_BRANCH_SESSION"
LAUNCHER = "launch_preview_branch.vbs"
THIS_CHECKOUT = Path(__file__).resolve().parents[1]


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"


def shown_as(checkout: Path) -> Preview | None:
    return preview_of(checkout) if is_branch_session() else None


def titled(title: str) -> str:
    return window_title(title, shown_as(THIS_CHECKOUT))
