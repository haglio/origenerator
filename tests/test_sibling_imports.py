"""Every module that reaches for a sibling puts it on the path first.

``shared_ui`` and ``player_core`` are checkouts beside this one, not
dependencies pip installed into whatever interpreter happens to be running.
The suite hides that: pytest runs on a venv where both are installed editable,
so ``from shared_ui.spacing import ...`` resolves in any module, wired or not.

The launch does not have that venv.  ``launch_origenerator.vbs`` sets
PYTHONPATH to the checkouts' parent, and a Fun Time session launches this app
with the plain system Python it names in ``paths.origenerator_python_exe`` --
neither of which has a sibling installed.  There, a module that imports a
sibling without calling ``ensure_shared_ui_on_path`` /
``ensure_player_core_on_path`` first raises ModuleNotFoundError, and if it does
so early enough the process dies BEFORE logging is configured: no traceback
anywhere, no window, and a hosting session that waits out its startup timeout
on a satellite that was never coming.

That is not hypothetical -- ``origenerator.ui_scale`` shipped without the call,
main() imports it before anything else, and a Fun Time session came up missing
Origenerator entirely with an empty state/origenerator.log.  test_launch_smoke
replays the launch's imports but does it on ``sys.executable``, the very
interpreter that has the siblings installed, so it saw nothing.  This check is
static instead: it reads the source, so no interpreter can hide the break.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "origenerator"

# The sibling packages, and the call that has to precede importing each.
SIBLINGS = {
    "shared_ui": "ensure_shared_ui_on_path",
    "player_core": "ensure_player_core_on_path",
}


def _module_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py"))


def _first_sibling_import(tree: ast.Module) -> tuple[str, int] | None:
    """The earliest line importing a sibling package, as (sibling, lineno)."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            root = node.module.split(".")[0]
            if root in SIBLINGS:
                hits.append((root, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in SIBLINGS:
                    hits.append((root, node.lineno))
    return min(hits, key=lambda hit: hit[1]) if hits else None


def _guard_calls(tree: ast.Module) -> dict[str, int]:
    """Where each ensure_*_on_path() is CALLED, by the line it runs on."""
    calls: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        for sibling, guard in SIBLINGS.items():
            if node.func.id == guard:
                calls[sibling] = min(calls.get(sibling, node.lineno), node.lineno)
    return calls


def _offenders() -> list[str]:
    problems = []
    for path in _module_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        first = _first_sibling_import(tree)
        if first is None:
            continue
        sibling, import_line = first
        guard_line = _guard_calls(tree).get(sibling)
        rel = path.relative_to(PACKAGE_ROOT.parent)
        if guard_line is None:
            problems.append(
                f"{rel}: imports {sibling} at line {import_line} without ever "
                f"calling {SIBLINGS[sibling]}()"
            )
        elif guard_line > import_line:
            problems.append(
                f"{rel}: calls {SIBLINGS[sibling]}() at line {guard_line}, AFTER "
                f"importing {sibling} at line {import_line}"
            )
    return problems


def test_no_module_imports_a_sibling_before_putting_it_on_the_path():
    problems = _offenders()
    assert not problems, (
        "These modules import a sibling checkout the launch interpreter cannot "
        "resolve on its own:\n  " + "\n  ".join(problems)
    )


def test_the_walk_actually_finds_the_modules_it_is_guarding():
    """A negative control: if the walk found no sibling imports at all -- a
    renamed package, a parse returning nothing -- the check above would pass on
    an empty set and guard nothing."""
    with_siblings = [
        path for path in _module_files()
        if _first_sibling_import(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert len(with_siblings) > 10


@pytest.mark.parametrize("sibling,guard", sorted(SIBLINGS.items()))
def test_each_guard_exists_under_the_name_this_check_looks_for(sibling, guard):
    """The check matches on a call by name, so a renamed helper would turn it
    into a test of nothing rather than a failure."""
    from origenerator import paths

    assert callable(getattr(paths, guard))
