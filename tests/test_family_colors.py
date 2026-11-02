from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from shared_ui import palette

pytestmark = pytest.mark.repo_check

_ROOT = Path(__file__).resolve().parent.parent
_TESTS = _ROOT / "tests"

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _family_hex() -> dict[str, str]:
    named: dict[str, list[str]] = {}
    for name in dir(palette):
        value = getattr(palette, name)
        if (name.isupper() and isinstance(value, tuple) and len(value) == 3
                and all(isinstance(channel, int) for channel in value)):
            named.setdefault(palette.as_hex(value), []).append(name)
    return {hexed: "/".join(sorted(names)) for hexed, names in named.items()}


def _sources() -> list[Path]:
    files = sorted(_TESTS.rglob("*.py"))
    assert files, f"no modules found under {_ROOT}"
    return files


def _painted_strings(tree: ast.AST):
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


def test_no_test_spells_out_a_family_color_by_hand():
    family = _family_hex()
    offenders = [f"{path.name}:{node.lineno} {found} is shared_ui.palette.{family[found.lower()]}"
                 for path in _sources()
                 for node in _painted_strings(ast.parse(path.read_text(encoding="utf-8")))
                 for found in _HEX.findall(node.value)
                 if found.lower() in family]
    assert not offenders, (
        "a family color written out by hand instead of read from "
        "shared_ui.palette: " + ", ".join(offenders))
