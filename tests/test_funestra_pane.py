"""The pane a Slideshow's Funestra draws into: the pass it is handed, the panel
it wears, the pointer it is handed, and the engine it opens on its window."""
from __future__ import annotations

import logging
import time

from funestra.console import ModeHud
from funestra.funestra import User
from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.playlist import PlaylistItem
from funestra.pointer import OMNIPAUSE_TOGGLE
from funestra.satellite_hud import HudModel
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui.funestra_pane import FunestraPane
from tests import gestures
from tests.funestra_fakes import FakeEngine


class _Running:
    """What runs on the Funestra, as the Funestra sees it."""

    def __init__(self, playback) -> None:
        self.playback = playback
        self.commands: list[str] = []
        self.ticks = 0
        self.closed = False

    def apply_command(self, command: str) -> bool:
        self.commands.append(command)
        return True

    def tick(self) -> None:
        self.ticks += 1

    def status_fields(self) -> dict[str, str]:
        return {}

    def top_block(self) -> ModeHud:
        return ModeHud()

    def set_showing(self, showing: bool) -> None:
        pass

    def picture(self):
        return None

    def close(self) -> None:
        self.closed = True


def _pane(qtbot, *, panel=lambda: None, engine=None, **kw):
    engine = engine if engine is not None else FakeEngine()
    running: list[_Running] = []

    def make(playback):
        running.append(_Running(playback))
        return running[-1]

    pane = FunestraPane(user=make, panel=panel, engine_for=lambda wid: engine, **kw)
    qtbot.addWidget(pane)
    return pane, engine, running


def _items(tmp_path, *names):
    return [PlaylistItem(tmp_path / f"{name}.png") for name in names]


def test_what_runs_on_the_funestra_is_what_a_funestra_asks_of_it():
    assert isinstance(_Running(None), User)


def test_the_funestra_opens_on_the_pass_it_is_handed(qtbot, tmp_path):
    pane, engine, running = _pane(qtbot)
    items = _items(tmp_path, "one", "two")

    pane.hand_over(items)

    assert engine.opened == [items[0].path]
    assert running[0].playback is pane.playback


def test_the_pass_opens_standing_on_the_item_it_is_told_to(qtbot, tmp_path):
    pane, engine, _running = _pane(qtbot)
    items = _items(tmp_path, "one", "two")

    pane.hand_over(items, land=items[1].path)

    assert pane.playback.current_video == items[1].path


def test_a_second_pass_keeps_the_item_on_screen_where_it_survived(qtbot, tmp_path):
    pane, _engine, _running = _pane(qtbot)
    one, two = _items(tmp_path, "one", "two")
    pane.hand_over([one, two])

    pane.hand_over([two, one])

    assert pane.playback.current_video == one.path
    assert pane.playback.playlist == [two.path, one.path]


def test_a_second_pass_lands_where_it_is_told(qtbot, tmp_path):
    pane, _engine, _running = _pane(qtbot)
    one, two = _items(tmp_path, "one", "two")
    pane.hand_over([one, two])

    pane.hand_over([two, one], land=two.path)

    assert pane.playback.current_video == two.path


def test_a_pass_with_nothing_in_it_opens_nothing(qtbot):
    pane, _engine, _running = _pane(qtbot)

    pane.hand_over([])

    assert pane.playback is None


def test_a_line_stands_where_the_picture_would_until_there_is_one(qtbot, tmp_path):
    pane, _engine, _running = _pane(qtbot)

    pane.show_message("Generating…")
    assert pane.message() == "Generating…"

    pane.hand_over(_items(tmp_path, "one"))
    assert pane.message() == ""


def test_the_panel_the_slideshow_hands_over_is_drawn_over_the_picture(qtbot, tmp_path):
    pane, engine, _running = _pane(qtbot, panel=lambda: HudModel(funestra="portrait"))
    pane.hand_over(_items(tmp_path, "one"))

    pane.tick()

    assert HUD_OVERLAY_ID in engine.overlays


def test_each_tick_gives_the_slideshow_a_pass_of_its_own(qtbot, tmp_path):
    pane, _engine, running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))

    pane.tick()

    assert running[0].ticks == 1


def test_a_press_on_the_picture_reaches_the_slideshow(qtbot, tmp_path):
    pane, _engine, running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    pane.tick()

    pane.press(QPointF(300, 300))

    assert running[0].commands == [OMNIPAUSE_TOGGLE]


def test_the_pointer_reaches_the_funestra_in_the_windows_own_pixels(qtbot, tmp_path, monkeypatch):
    pane, _engine, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    monkeypatch.setattr(type(pane._window), "devicePixelRatioF", lambda self: 2.0)
    reached = []
    monkeypatch.setattr(pane._funestra, "press", lambda x, y, *, window: reached.append((x, y)))
    monkeypatch.setattr(pane._funestra, "motion",
                        lambda x, y, *, held, window: reached.append((x, y, held)))
    monkeypatch.setattr(pane._funestra, "wheel",
                        lambda x, y, steps, *, window: reached.append((x, y, steps)))

    pane.press(QPointF(10, 20))
    pane.motion(QPointF(11, 21), held=True)
    pane.wheel(QPointF(12, 22), -3)

    assert reached == [(20, 40), (22, 42, True), (24, 44, -3)]


def test_the_wheel_is_counted_in_notches(qtbot, tmp_path, monkeypatch):
    pane, _engine, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    turned = []
    monkeypatch.setattr(pane, "wheel", lambda position, steps: turned.append(steps))

    for delta in (-240, 120, 40):
        pane._window.wheelEvent(QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False))

    assert turned == [-2, 1, 1]


def test_a_double_click_is_two_presses_and_the_second_says_it_came_again(qtbot, tmp_path):
    pane, _engine, running = _pane(qtbot)
    pane.resize(600, 400)
    pane.show()
    qtbot.waitExposed(pane)
    pane.hand_over(_items(tmp_path, "one"))
    pane.tick()
    again = []
    answer = running[0].apply_command
    running[0].apply_command = lambda command: again.append(pane.pressing_again) or answer(command)

    gestures.double_click(pane._window, QPoint(450, 300))

    assert running[0].commands == [OMNIPAUSE_TOGGLE, OMNIPAUSE_TOGGLE]
    assert again == [False, True]
    assert not pane.pressing_again


def test_a_pass_handed_over_before_there_is_a_window_waits_for_one(qtbot, tmp_path):
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None)
    qtbot.addWidget(pane)
    items = _items(tmp_path, "one")
    pane.hand_over(items)
    assert pane.playback is None

    engine = FakeEngine()
    pane._engine_for = lambda wid: engine
    pane._open_if_ready()

    assert engine.opened == [items[0].path]


def test_a_pane_with_no_window_to_draw_into_opens_no_engine(qtbot, tmp_path):
    """The suite draws on a platform with no windows in it, and an engine
    handed one of those has nothing to paint."""
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None)
    qtbot.addWidget(pane)

    pane.show()
    pane.hand_over(_items(tmp_path, "one"))

    assert pane.playback is None


def test_an_engine_that_will_not_open_leaves_the_pane_without_one(qtbot, tmp_path, monkeypatch, caplog):
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None)
    qtbot.addWidget(pane)
    pane.show()
    monkeypatch.setattr(QApplication.instance(), "platformName", lambda: "windows")
    monkeypatch.setattr(type(pane._window), "isVisible", lambda self: True)
    monkeypatch.setattr("funestra.mpv_engine.MpvEngine",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("no engine")))

    pane.hand_over(_items(tmp_path, "one"))

    assert pane.playback is None
    assert "could not open" in caplog.text


def test_the_sound_set_before_the_funestra_opens_is_what_it_opens_with(qtbot, tmp_path):
    pane, engine, _running = _pane(qtbot)
    pane.set_audio_muted(True)

    pane.hand_over(_items(tmp_path, "one"))

    assert engine.muted is True


def test_the_sound_can_be_set_once_it_is_open(qtbot, tmp_path):
    pane, engine, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    assert engine.muted is False

    pane.set_audio_muted(True)

    assert engine.muted is True


def test_the_drive_is_told_where_the_clip_has_got_to(qtbot, tmp_path):
    pane, engine, _running = _pane(qtbot)
    assert pane.position() == 0
    pane.hand_over(_items(tmp_path, "one"))

    engine.position_ms = 12345.6

    assert pane.position() == 12345


def test_closing_the_pane_closes_the_funestra_and_what_runs_on_it(qtbot, tmp_path):
    pane, engine, running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))

    pane.close_engine()

    assert engine.closed is True
    assert running[0].closed is True


def test_the_picture_keeps_moving_while_the_window_is_busy(qtbot, tmp_path):
    pane, engine, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))

    time.sleep(0.3)
    moved_while_busy = engine.pushes
    pane.close_engine()

    assert moved_while_busy >= 5


def test_a_picture_that_stops_moving_says_why_in_the_log(qtbot, tmp_path, caplog):
    engine = FakeEngine()

    def the_engine_gives_out():
        raise RuntimeError("made-up engine failure")

    engine.push_still = the_engine_gives_out
    pane, _engine, _running = _pane(qtbot, engine=engine)
    with caplog.at_level(logging.ERROR, logger="origenerator.gui.funestra_pane"):
        pane.hand_over(_items(tmp_path, "one"))
        giving_up_at = time.monotonic() + 2
        while "made-up engine failure" not in caplog.text and time.monotonic() < giving_up_at:
            time.sleep(0.02)
    pane.close_engine()

    assert "stopped moving" in caplog.text


def test_a_pass_handed_over_before_the_pane_is_shown_opens_the_moment_it_is(qtbot, tmp_path):
    engine = FakeEngine()
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None,
                        engine_for=lambda wid: engine if pane._window.isVisible() else None)
    qtbot.addWidget(pane)
    items = _items(tmp_path, "one")
    pane.hand_over(items)
    assert pane.playback is None

    pane.show()

    assert engine.opened == [items[0].path]


def test_a_line_said_once_a_pass_is_owed_does_not_stand_in_front_of_the_picture(qtbot, tmp_path):
    engine = FakeEngine()
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None,
                        engine_for=lambda wid: engine if pane._window.isVisible() else None)
    qtbot.addWidget(pane)
    items = _items(tmp_path, "one")
    pane.hand_over(items)
    pane.show_message("Generating…")

    pane.show()

    assert engine.opened == [items[0].path]
    assert pane.message() == ""


def test_the_slideshow_is_told_the_moment_its_funestra_opens(qtbot, tmp_path):
    told = []
    engine = FakeEngine()
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None,
                        engine_for=lambda wid: engine if pane._window.isVisible() else None,
                        on_open=lambda: told.append(pane.playback))
    qtbot.addWidget(pane)
    pane.hand_over(_items(tmp_path, "one"))
    assert told == []

    pane.show()

    assert told == [pane.playback]
    assert pane.playback is not None
