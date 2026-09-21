"""No color in this app is a hand-typed copy of one the family already owns.

This app keeps a small palette of its own (``gui/palette.py``): the greys its
cards and rows share and nothing else does.  That is fine and deliberate.  What
is not fine is a hex literal whose value is a shared_ui token -- the family's
one blue written out as ``#3080e0``, its one green as ``#30a030`` -- because a
copy is a thing that drifts, and this family has already watched one do it: Fun
Time's reference page mirrored seven shared_ui colors by hand and its border
ended up three points off the token it was copied from.

Only hex literals are checked.  ``(255, 255, 255)`` is white to anything that
draws, and refusing every triple that happens to equal a token would refuse
plain white pixels in a test fixture.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from shared_ui import palette

_ROOT = Path(__file__).resolve().parent.parent
_TREES = (_ROOT / "origenerator", _ROOT / "tools", _ROOT / "tests")

# "#abc" and "#aabbcc" -- how a color reaches a Qt stylesheet or an HTML page
# when it did not come from a token.
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _family_hex() -> dict[str, str]:
    """Every shared_ui token's ``#rrggbb``, and the names that spell it."""
    named: dict[str, list[str]] = {}
    for name in dir(palette):
        value = getattr(palette, name)
        if (name.isupper() and isinstance(value, tuple) and len(value) == 3
                and all(isinstance(channel, int) for channel in value)):
            named.setdefault(palette.as_hex(value), []).append(name)
    return {hexed: "/".join(sorted(names)) for hexed, names in named.items()}


def _sources() -> list[Path]:
    files = sorted(path for tree in _TREES if tree.is_dir()
                   for path in tree.rglob("*.py"))
    assert files, f"no modules found under {_ROOT}"
    return files


def _painted_strings(tree: ast.AST):
    """Every string constant except a docstring.

    A docstring is prose -- this file's own names the colors it forbids, to
    explain the rule -- and nothing ever paints with one.
    """
    documented = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                documented.add(id(first.value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in documented):
            yield node


def test_no_color_in_this_app_is_a_hand_copy_of_a_family_token():
    # Parsed rather than grepped, so a "#" in a comment or a path is not a hit --
    # only text the app actually paints with, or a test asserts on.
    family = _family_hex()
    offenders = []
    for path in _sources():
        for node in _painted_strings(ast.parse(path.read_text(encoding="utf-8"))):
            for found in _HEX.findall(node.value):
                if found.lower() in family:
                    offenders.append(
                        f"{path.name}:{node.lineno} {found} is "
                        f"shared_ui.palette.{family[found.lower()]}")
    assert not offenders, (
        "a family color written out by hand instead of read from "
        "shared_ui.palette: " + ", ".join(offenders))
