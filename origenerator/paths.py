"""Locate the sibling packages this app imports without hardcoding directory depth.

``shared_ui`` and ``player_core`` live next to this project under the shared
``projects`` root and are imported via ``sys.path`` rather than installed.  Both
use a src-style layout -- the importable package sits one level down, at
``<name>/<name>/__init__.py`` -- so we walk up to the directory that holds the
*checkout* and put that checkout on ``sys.path`` (importing ``<name>`` then finds
the package inside it).  Walking, rather than counting parents, keeps this
working whether the app is a normal clone or a ``.claude/worktrees/<name>``
worktree.
"""

from __future__ import annotations

import sys
from pathlib import Path


def sibling_checkout(name: str) -> Path:
    """Return the *name* checkout dir (its ``name/`` child is the package)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        checkout = parent / name
        if (checkout / name / "__init__.py").exists():
            return checkout
    raise RuntimeError(f"Could not locate the {name} package above {here}")


def projects_root() -> Path:
    """Return the ``shared_ui`` checkout dir."""
    return sibling_checkout("shared_ui")


def ensure_sibling_on_path(name: str) -> None:
    """Put the *name* checkout on ``sys.path`` so ``name`` is importable."""
    root = str(sibling_checkout(name))
    if root not in sys.path:
        sys.path.insert(0, root)


def ensure_shared_ui_on_path() -> None:
    """Put the ``shared_ui`` checkout on ``sys.path``."""
    ensure_sibling_on_path("shared_ui")


def ensure_player_core_on_path() -> None:
    """Put the ``player_core`` checkout on ``sys.path``.

    That package holds the family's stroke: the waveform and its dials
    (``direct_control``), the hands-free variation of them (``cruise_control``),
    and where the drive readout's parts sit (``drive_layout``).  Genau drives the
    OSR2 from exactly these, so this app does too rather than growing a second
    set that drifts from them.
    """
    ensure_sibling_on_path("player_core")
