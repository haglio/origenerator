"""pytest-qt's waits hand back a context manager, and wait only as its `with` block ends."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.repo_check

_TESTS = Path(__file__).resolve().parent

_WAITS_AS_THE_WITH_ENDS = {
    "assertNotEmitted", "captureExceptions", "waitActive", "waitCallback", "waitExposed",
    "waitSignal", "waitSignals",
    "assert_not_emitted", "capture_exceptions", "wait_active", "wait_callback",
    "wait_exposed", "wait_signal", "wait_signals",
}


def _waits_called_bare(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr in _WAITS_AS_THE_WITH_ENDS):
            yield f"{path.relative_to(_TESTS).as_posix()}:{node.lineno}"


def test_no_qtbot_wait_is_called_bare_where_it_waits_for_nothing():
    bare = [where for path in sorted(_TESTS.rglob("*.py")) for where in _waits_called_bare(path)]

    assert bare == [], (
        "these qtbot waits are called as statements, so each waits for nothing; write "
        "`with qtbot.waitExposed(window): window.show()` instead: " + ", ".join(bare))
