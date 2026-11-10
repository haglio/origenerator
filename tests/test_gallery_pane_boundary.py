from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PANE = REPO_ROOT / "origenerator" / "gui" / "gallery_pane.py"


def _class_def(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def test_the_panes_own_tests_build_it_with_no_view_in_sight():
    its_tests = Path(__file__).with_name("test_gallery_pane.py")
    imported = {ast.unparse(node) for node in ast.walk(ast.parse(its_tests.read_text(encoding="utf-8")))
                if isinstance(node, (ast.Import, ast.ImportFrom))}
    assert not [line for line in imported if "gallery_view" in line], (
        "the Gallery pane, constructed alone: how the view answers the pane's signals stays "
        "pinned where the view is built, and what lives there is the pane's own promise")


def test_the_pane_holds_no_view():
    tree = ast.parse(PANE.read_text(encoding="utf-8"))
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} \
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} \
        | {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
           for a in n.names}
    assert "GalleryView" not in named
    assert "_v" not in named
    init = next(n for n in _class_def(PANE, "GalleryPane").body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assert [a.arg for a in init.args.args] == [
        "self", "scroll", "db", "jobs", "populate", "host"]
