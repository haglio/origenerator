"""The pane holds no view: the back-pointer the split cut stays cut."""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PANE = REPO_ROOT / "origenerator" / "gui" / "browser_pane.py"


def _class_def(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == name)


def test_the_pane_holds_no_view():
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
