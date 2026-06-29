"""Locate sibling packages without hardcoding directory depth.

``shared_ui`` lives next to this project under the shared ``projects`` root
and is imported via ``sys.path`` rather than installed.  The checkout depth
differs between a normal clone and a ``.claude/worktrees/<name>`` worktree, so
we discover the root by walking up to the directory that contains
``shared_ui`` instead of counting parents.
"""

from __future__ import annotations

import sys
from pathlib import Path


def projects_root() -> Path:
    """Return the ancestor directory that contains the ``shared_ui`` package."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared_ui" / "__init__.py").exists():
            return parent
    raise RuntimeError(f"Could not locate the shared_ui package above {here}")


def ensure_shared_ui_on_path() -> None:
    """Put the projects root on ``sys.path`` so ``shared_ui`` is importable."""
    root = str(projects_root())
    if root not in sys.path:
        sys.path.insert(0, root)
