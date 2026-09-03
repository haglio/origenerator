"""Import a module from this repo's top-level ``tools/`` by file path.

The bare package name ``tools`` is ambiguous once the suite runs with sibling
``player_core`` on ``sys.path``: that checkout carries its own top-level
``tools`` package, and on the windows-latest CI layout it sorts ahead of this
repo's, so ``from tools import ...`` binds to player_core's ``tools`` -- which
does not have these modules -- and collection fails.  It is masked on a macOS
checkout only because this repo's root happens to sort first there.

Loading by file path binds to this checkout's module no matter what a bare
``import tools`` would resolve to, so it is correct on both platforms.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


def load_repo_tool(module_name: str):
    """Return ``tools/<module_name>.py`` from this checkout, imported by path."""
    path = _TOOLS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so a module that looks itself up by name during
    # import finds this instance rather than resolving the shadowed ``tools``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
