"""Locate the sibling ``shared_ui`` package without hardcoding directory depth.

``shared_ui`` lives next to this project under the shared ``projects`` root and
is imported via ``sys.path`` rather than installed.  It uses a src-style layout
-- its importable package sits one level down, at
``shared_ui/shared_ui/__init__.py`` -- so we walk up to the directory that holds
the ``shared_ui`` *checkout* and put that checkout on ``sys.path`` (importing
``shared_ui`` then finds the package inside it).  Walking, rather than counting
parents, keeps this working whether the app is a normal clone or a
``.claude/worktrees/<name>`` worktree.
"""

from __future__ import annotations

import sys
from pathlib import Path


def projects_root() -> Path:
    """Return the ``shared_ui`` checkout dir (its ``shared_ui/`` child is the package)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        checkout = parent / "shared_ui"
        if (checkout / "shared_ui" / "__init__.py").exists():
            return checkout
    raise RuntimeError(f"Could not locate the shared_ui package above {here}")


def ensure_shared_ui_on_path() -> None:
    """Put the ``shared_ui`` checkout on ``sys.path`` so ``shared_ui`` is importable."""
    root = str(projects_root())
    if root not in sys.path:
        sys.path.insert(0, root)
