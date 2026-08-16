"""Every annotation must name something its module actually binds.

This exists because the suite cannot see the failure it guards. Python 3.14
evaluates annotations lazily (PEP 649), so a signature like ``def f(x: Missing)``
imports fine on the machine this is developed on; the merge gate runs 3.12, which
evaluates them as the ``def`` executes and raises ``NameError`` at import time.
The result is a branch that is green locally and cannot be collected in CI — which
is exactly what happened to ``InFlightCard.__init__(self, item: InFlightItem)``,
whose module imported ``queue_wait_text`` from ``inflight`` and not the class
beside it.

So the check is static rather than an import: read every module, collect what it
binds at any scope, and complain about any bare name in an annotation that isn't
among them. A module that opts into ``from __future__ import annotations`` is
skipped — nothing there is evaluated on either version.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "origenerator"

_BUILTINS = frozenset(dir(builtins)) | {"None", "True", "False"}


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name the module binds anywhere — imports, defs, assignments, args.

    Deliberately flat and generous: this is looking for a name that is bound
    *nowhere*, so a scope-accurate walk would only add false alarms.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _annotations(tree: ast.Module) -> list[ast.expr]:
    """Every annotation the interpreter would evaluate at definition time."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in args.posonlyargs + args.args + args.kwonlyargs:
                if arg.annotation is not None:
                    found.append(arg.annotation)
            for arg in (args.vararg, args.kwarg):
                if arg is not None and arg.annotation is not None:
                    found.append(arg.annotation)
            if node.returns is not None:
                found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
    return found


def _defers_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _unbound_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if _defers_annotations(tree):
        return []
    defined = _bound_names(tree) | _BUILTINS
    return sorted({
        f"{path.name}:{name.lineno}: {name.id}"
        for annotation in _annotations(tree)
        for name in ast.walk(annotation)
        if isinstance(name, ast.Name) and name.id not in defined
    })


def test_every_annotation_names_something_the_module_binds():
    offenders = [
        line
        for path in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in path.parts
        for line in _unbound_in(path)
    ]
    assert offenders == [], (
        "these annotations would raise NameError on the merge gate's Python:\n"
        + "\n".join(offenders)
    )


def test_the_check_catches_a_missing_import(tmp_path):
    # The shape that got through: the class used in the signature is not among
    # the names imported beside it.
    module = tmp_path / "example.py"
    module.write_text(
        "from origenerator.gui.inflight import queue_wait_text\n"
        "\n"
        "\n"
        "def build(item: InFlightItem):\n"
        "    return item\n",
        encoding="utf-8",
    )
    assert _unbound_in(module) == ["example.py:4: InFlightItem"]


def test_a_module_deferring_its_annotations_is_left_alone(tmp_path):
    module = tmp_path / "deferred.py"
    module.write_text(
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def build(item: InFlightItem):\n"
        "    return item\n",
        encoding="utf-8",
    )
    assert _unbound_in(module) == []
