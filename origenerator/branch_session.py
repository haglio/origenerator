from __future__ import annotations

import os
from pathlib import Path

from app_support import haglio_settings, siblings
from shared_ui.preview import Preview, preview_of, window_title

ENV_FLAG = "ORIGENERATOR_BRANCH_SESSION"
LAUNCHER = "launch_preview_branch.vbs"
THIS_CHECKOUT = Path(__file__).resolve().parents[1]


def is_branch_session(environ=os.environ) -> bool:
    return environ.get(ENV_FLAG) == "1"


def the_librarys_checkout(roots: tuple[Path, ...] | None = None) -> Path:
    return siblings.project_dir("origenerator", haglio_settings.project_roots() if roots is None else roots)


def production_checkout(environ=os.environ, roots: tuple[Path, ...] | None = None) -> Path:
    return the_librarys_checkout(roots) if is_branch_session(environ) else THIS_CHECKOUT


def shown_as(checkout: Path) -> Preview | None:
    return preview_of(checkout) if is_branch_session() else None


def titled(title: str) -> str:
    return window_title(title, shown_as(THIS_CHECKOUT))
