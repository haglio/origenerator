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

import importlib.util
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


def ensure_sibling_on_path(name: str) -> None:
    """Put the *name* checkout on ``sys.path`` so ``name`` is importable.

    Only when it is REALLY importable already: a hosting session (or a test
    run) that put a specific checkout of the sibling on ``PYTHONPATH`` has
    chosen which copy this app runs, and inserting the walked-up primary AHEAD
    of that choice would silently un-choose it — the hosted app then imports a
    sibling missing the very modules the branch under judgment added there.

    Really, because a checkout laid out beside this one answers ``find_spec``
    without being the package at all: the repo directory shares the package's
    name, so with the checkouts' parent on the path it resolves as an empty
    namespace package, and every submodule under it is missing.  A namespace
    hit is not a choice anyone made — it is the shadow this function exists to
    step past.
    """
    spec = importlib.util.find_spec(name)
    if spec is not None and spec.origin is not None:
        return
    root = str(sibling_checkout(name))
    if root not in sys.path:
        sys.path.insert(0, root)


def ensure_shared_ui_on_path() -> None:
    """Put the ``shared_ui`` checkout on ``sys.path``."""
    ensure_sibling_on_path("shared_ui")


def ensure_player_core_on_path() -> None:
    """Put the ``player_core`` checkout on ``sys.path``.

    That package holds the family's stroke: the waveform and its dials
    (``robot_hand``), the console and the drive readout that show them, and
    where that readout's parts sit (``drive_layout``).  Genau drives the OSR2
    from exactly these, so this app does too rather than growing a second set
    that drifts from them.  Hands-free comes from there as well; what this app
    puts around it is :mod:`origenerator.stroke_engine`.
    """
    ensure_sibling_on_path("player_core")
