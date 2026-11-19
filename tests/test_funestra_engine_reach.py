from __future__ import annotations

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "origenerator"
_RUNS_A_FUNESTRA_HERE = {"funestra.mpv_engine": {"MpvEngine"}, "funestra.funestra": {"Funestra"}}


def runs_a_funestra_here(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        match node:
            case ast.ImportFrom(module=module, names=names) if module in _RUNS_A_FUNESTRA_HERE:
                if {alias.name for alias in names} & (_RUNS_A_FUNESTRA_HERE[module] | {"*"}):
                    lines.append(node.lineno)
            case ast.Import(names=names):
                if any(alias.name in _RUNS_A_FUNESTRA_HERE for alias in names):
                    lines.append(node.lineno)
    return lines


def test_no_part_of_the_app_runs_a_funestra_or_its_engine_in_the_apps_own_process():
    running = {str(path.relative_to(_APP)): lines for path in sorted(_APP.rglob("*.py"))
               if (lines := runs_a_funestra_here(path.read_text(encoding="utf-8")))}

    assert running == {}, (
        "a Funestra is a program of its own, which this app starts and reaches through its "
        "files; these reach for one in this app's own process")


@pytest.mark.parametrize("source", [
    "from funestra.mpv_engine import MpvEngine\n",
    "def f():\n    from funestra.mpv_engine import MpvEngine\n",
    "from funestra.funestra import Channels, Funestra\n",
    "import funestra.mpv_engine\n",
])
def test_the_measure_sees_each_way_of_reaching_for_one(source):
    assert runs_a_funestra_here(source)


@pytest.mark.parametrize("source", [
    "from funestra.funestra import Channels\n",
    "from funestra.mpv_engine import MpvStation\n",
    "from funestra.program.launch import launch_command\n",
])
def test_the_measure_leaves_alone_what_starts_or_feeds_one(source):
    assert runs_a_funestra_here(source) == []
