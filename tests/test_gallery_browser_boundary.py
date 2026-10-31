"""The GalleryView / BrowserPane boundary, held at zero, and the two classes'
sizes, held under ceilings that only come down."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VIEW = REPO_ROOT / "origenerator" / "gui" / "gallery_view.py"
PANE = REPO_ROOT / "origenerator" / "gui" / "browser_pane.py"
MAX_GALLERY_VIEW_METHODS = 269
MAX_BROWSER_PANE_METHODS = 79

# A private attribute read through a privately held object — self._x._y — the
# reach-through shape the audit counted 93 of. Zero everywhere in both files:
# scoping it to one attribute name would let a renamed handle walk past it.
_REACH_THROUGH = re.compile(r"self\._[a-z_]+\._[a-z_]")


def _private_chains(path: Path) -> list[str]:
    return _REACH_THROUGH.findall(path.read_text(encoding="utf-8"))


def _ast_private_chains(path: Path) -> int:
    """The same count off the syntax tree, so a chain the regex cannot see —
    one split across lines, or oddly spaced — still counts."""
    found = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Attribute) and node.attr.startswith("_")
                and isinstance(node.value, ast.Attribute)
                and node.value.attr.startswith("_")
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"):
            found += 1
    return found


def _class_def(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def test_neither_knot_file_reaches_a_private_through_a_private():
    for path in (VIEW, PANE):
        assert _private_chains(path) == [], path.name
        assert _ast_private_chains(path) == 0, path.name


def test_the_pane_holds_no_view():
    """The back-pointer stays deleted. The regex above would miss a re-added
    self._v that only called public attributes, so the handle itself is banned:
    no name in browser_pane.py mentions GalleryView, and the constructor's
    parameters are exactly the collaborators the split ended on."""
    tree = ast.parse(PANE.read_text(encoding="utf-8"))
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} \
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} \
        | {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
           for a in n.names}
    assert "GalleryView" not in named  # docstring prose may say it; code may not
    assert "_v" not in named  # the handle itself, under the name it had
    init = next(n for n in _class_def(PANE, "BrowserPane").body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert [a.arg for a in init.args.args] == [
        "self", "scroll", "db", "jobs", "auto", "tree", "host"]


@pytest.mark.parametrize(("path", "name", "ceiling"), [
    (VIEW, "GalleryView", MAX_GALLERY_VIEW_METHODS),
    (PANE, "BrowserPane", MAX_BROWSER_PANE_METHODS),
], ids=["GalleryView", "BrowserPane"])
def test_neither_class_outgrows_its_ceiling(path, name, ceiling):
    methods = sum(isinstance(x, ast.FunctionDef) for x in _class_def(path, name).body)

    assert methods <= ceiling, (
        f"{name} has {methods} methods, over its ceiling of {ceiling}. The ceiling only "
        "comes down: give what the new method does to one of the collaborators the class "
        "already hands its work to, or to a new one, rather than raising it. Lower the "
        "ceiling when you take methods out."
    )
