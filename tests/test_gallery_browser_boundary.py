"""The GalleryView / BrowserPane boundary, held at zero — and the split's sizes.

The audit measured the coupling no length or coverage gate can see: the pane
reached into the view 93 times (83 of them at private names, one of them a
write), the view reached back at pane privates, and 48 of the pane's 54
six-month commits also touched the view. The inversion took that to zero in
both directions; these tests are what keep it there. They read source, not
running objects, so they fire before anything is constructed and hold in both
directions symmetrically.

Every count is an EQUALITY, not a ceiling. Above the number is a new
violation; below it means a change lowered the real value and forgot to lower
the gate, which would leave that much silent headroom for the next violation
to hide in. A commit that moves a number says so, in the same commit.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VIEW = REPO_ROOT / "origenerator" / "gui" / "gallery_view.py"
PANE = REPO_ROOT / "origenerator" / "gui" / "browser_pane.py"

# A private member read through a privately held object — self._x._y — the
# reach-through shape the audit counted 93 of. Zero everywhere in both files:
# scoping it to one attribute name would let a renamed handle walk past it.
_REACH_THROUGH = re.compile(r"self\._[a-z_]+\._[a-z_]")


def _private_chains(path: Path) -> list[str]:
    return _REACH_THROUGH.findall(path.read_text())


def _ast_private_chains(path: Path) -> int:
    """The same count off the syntax tree, so a chain the regex cannot see —
    one split across lines, or oddly spaced — still counts."""
    found = 0
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Attribute) and node.attr.startswith("_")
                and isinstance(node.value, ast.Attribute)
                and node.value.attr.startswith("_")
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"):
            found += 1
    return found


def _class_def(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def test_neither_knot_file_reaches_a_private_through_a_private():
    for path in (VIEW, PANE):
        assert _private_chains(path) == [], path.name
        assert _ast_private_chains(path) == 0, path.name


def test_the_pane_holds_no_view():
    """The back-pointer stays deleted. The regex above would miss a re-added
    self._v that only called public members, so the handle itself is banned:
    no name in browser_pane.py mentions GalleryView, and the constructor's
    parameters are exactly the collaborators the split ended on."""
    tree = ast.parse(PANE.read_text())
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} \
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} \
        | {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
           for a in n.names}
    assert "GalleryView" not in named  # docstring prose may say it; code may not
    assert not re.search(r"self\._v\b", PANE.read_text())
    init = next(n for n in _class_def(PANE, "BrowserPane").body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert [a.arg for a in init.args.args] == [
        "self", "scroll", "db", "reroll", "auto", "tree", "host"]


def test_the_classes_hold_the_splits_sizes_as_equalities():
    """The per-class method count, ratcheted to what the inversion left.

    This is the number the audit said to gate (Q14): the god object measured
    368 methods, and a class this size only ever grows quietly. Shrink it and
    the gate shrinks with you, in the same commit; grow it and this fails,
    which is the gate doing its job."""
    assert sum(isinstance(x, ast.FunctionDef)
               for x in _class_def(VIEW, "GalleryView").body) == 368
    assert sum(isinstance(x, ast.FunctionDef)
               for x in _class_def(PANE, "BrowserPane").body) == 81
