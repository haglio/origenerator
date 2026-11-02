from __future__ import annotations

import ast
from pathlib import Path

import pytest
from funestra.main_hud import ModeHud
from funestra.playlist import PlaylistItem
from funestra.testing import FakeEngine

from origenerator.gui.funestra_pane import FunestraPane, PaneChannel

_GUI = Path(__file__).resolve().parent.parent / "origenerator" / "gui"
_THE_ONE_MODULE_THAT_MAY = "funestra_pane.py"
_MODULES_THAT_OPEN_AN_ENGINE = ("funestra.mpv_engine",)


def _is_tainted(node, names: set[str], holders: set[str]) -> bool:
    match node:
        case ast.Name(id=name):
            return name in names
        case ast.Attribute(attr=attr) | ast.Call(func=ast.Name(id="getattr"),
                                                 args=[_, ast.Constant(value=attr), *_]):
            return attr in holders
        case ast.NamedExpr(value=value):
            parts = [value]
        case ast.IfExp(body=body, orelse=orelse):
            parts = [body, orelse]
        case ast.BoolOp(values=parts):
            pass
        case _:
            parts = []
    return any(_is_tainted(part, names, holders) for part in parts)


def _what_is_handed_to_the_pane_as_its_engine(tree) -> list:
    return [lamb.body for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg == "engine_for"
            for lamb in ast.walk(node.value) if isinstance(lamb, ast.Lambda)]


def _assignments(tree):
    for node in ast.walk(tree):
        match node:
            case ast.Assign(targets=targets, value=value):
                yield from ((target, value) for target in targets)
            case ast.AnnAssign(target=target, value=ast.AST() as value) | ast.NamedExpr(target=target, value=value):
                yield target, value


def _follow_the_aliases(tree, names: set[str], holders: set[str]) -> None:
    grew = True
    while grew:
        grew = False
        for target, value in _assignments(tree):
            if not _is_tainted(value, names, holders):
                continue
            if isinstance(target, ast.Name) and target.id not in names:
                names.add(target.id)
                grew = True
            elif isinstance(target, ast.Attribute) and target.attr not in holders:
                holders.add(target.attr)
                grew = True


def _opens_an_engine(node) -> bool:
    match node:
        case ast.ImportFrom(module=module):
            return module in _MODULES_THAT_OPEN_AN_ENGINE
        case ast.Import(names=names):
            return any(alias.name in _MODULES_THAT_OPEN_AN_ENGINE for alias in names)
    return False


def engine_reaches(source: str, measured_holders: set[str]) -> list[int]:
    tree = ast.parse(source)
    handed = _what_is_handed_to_the_pane_as_its_engine(tree)
    names = {body.id for body in handed if isinstance(body, ast.Name)}
    holders = set(measured_holders) | {body.attr for body in handed if isinstance(body, ast.Attribute)}
    _follow_the_aliases(tree, names, holders)
    reaches = []
    for node in ast.walk(tree):
        match node:
            case ast.Attribute(value=value, ctx=ast.Load()) if _is_tainted(value, names, holders):
                reaches.append(node.lineno)
            case ast.Attribute(attr=attr, ctx=ast.Load()) if attr in measured_holders:
                reaches.append(node.lineno)
            case ast.Call(func=ast.Name(id="getattr"), args=[value, *_]) if (
                    _is_tainted(value, names, holders) or _is_tainted(node, names, holders)):
                reaches.append(node.lineno)
        if _opens_an_engine(node):
            reaches.append(node.lineno)
    return sorted(set(reaches))


class _IdleUser:
    def apply_command(self, command: str) -> bool:
        return not command.split(" ", 1)[0].isupper()

    def tick(self) -> None:
        pass

    def status_fields(self) -> dict[str, str]:
        return {}

    def top_block(self) -> ModeHud:
        return ModeHud()

    def set_showing(self, showing: bool) -> None:
        pass

    def own_frame(self):
        return None

    def close(self) -> None:
        pass


@pytest.fixture
def measured_holders(qtbot, tmp_path) -> set[str]:
    engine = FakeEngine()
    pane = FunestraPane(channel=PaneChannel(), user=lambda playback: _IdleUser(), hud=lambda: None,
                        engine_for=lambda _window_id: engine)
    qtbot.addWidget(pane)
    pane.show()
    pane.channel.write_playlist([PlaylistItem(tmp_path / "scene one.png")])
    holders = {name for holder in (pane, pane._funestra, pane.playback)
               for name, value in vars(holder).items() if value is engine}
    pane.close_engine()
    assert holders, "a pane that shows a video holds its engine somewhere; the measure found nothing"
    return holders


def test_only_the_pane_reaches_a_funestras_engine(measured_holders):
    reaching = {path.name: lines for path in sorted(_GUI.glob("*.py"))
                if path.name != _THE_ONE_MODULE_THAT_MAY
                if (lines := engine_reaches(path.read_text(encoding="utf-8"), measured_holders))}

    assert reaching == {}


@pytest.mark.parametrize("source", [
    "def f(self):\n    self._pane._engine.seek_ms(1)\n",
    "def f(self):\n    held = self._pane._engine\n    held.seek_ms(1)\n",
    "def f(self):\n    held = self._pane._engine\n    other = held\n    other.seek_ms(1)\n",
    "def f(self):\n    self.kept = self._pane._engine\n\ndef g(self):\n    self.kept.seek_ms(1)\n",
    "def f(self):\n    if (held := self._pane._engine):\n        held.seek_ms(1)\n",
    "def f(self):\n    getattr(self._pane, '_engine').seek_ms(1)\n",
    "def f(self, player):\n    Pane(engine_for=lambda _id: player)\n    player.seek_ms(1)\n",
    "def f(self, wiring):\n    Pane(engine_for=lambda _id: wiring.player)\n    wiring.player.seek_ms(1)\n",
    "from funestra.mpv_engine import MpvEngine\n",
])
def test_the_measure_sees_each_way_of_reaching_it(source):
    assert engine_reaches(source, {"_engine"})


@pytest.mark.parametrize("source", [
    "def f(self, player):\n    Pane(engine_for=lambda _id: player)\n",
    "def f(self, wiring):\n    Pane(engine_for=lambda _id: wiring.player)\n    wiring.radio.play()\n",
    "from origenerator import motion_engine\n\ndef f(state):\n    return motion_engine.position(state)\n",
    "def f(self):\n    self._pane.close_engine()\n",
])
def test_the_measure_leaves_alone_what_does_not_reach_it(source):
    assert engine_reaches(source, {"_engine"}) == []
