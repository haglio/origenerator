"""The pane a Slideshow's Funestra draws into: the pass it is handed, the panel
it wears, the pointer it is handed, and the engine it opens on its window."""
from __future__ import annotations

import logging
import os
import time

from player_core.console import ModeHud
from player_core.funestra import User
from player_core.hud_overlay import HUD_OVERLAY_ID
from player_core.playlist import PlaylistItem
from player_core.pointer import OMNIPAUSE_TOGGLE
from player_core.satellite_hud import HudModel
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from origenerator.gui import funestra_pane
from origenerator.gui.funestra_pane import FunestraPane
from tests.funestra_fakes import FakePlayer


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


def _pane(qtbot, *, panel=lambda: None, player=None, **kw):
    player = player if player is not None else FakePlayer()
    running: list[_Running] = []

    def make(playback):
        running.append(_Running(playback))
        return running[-1]

    pane = FunestraPane(user=make, panel=panel, player_for=lambda wid: player, **kw)
    qtbot.addWidget(pane)
    return pane, player, running


def _items(tmp_path, *names):
    return [PlaylistItem(tmp_path / f"{name}.png") for name in names]


def test_what_runs_on_the_funestra_is_what_a_funestra_asks_of_it():
    assert isinstance(_Running(None), User)


def test_the_funestra_opens_on_the_pass_it_is_handed(qtbot, tmp_path):
    pane, player, running = _pane(qtbot)
    items = _items(tmp_path, "one", "two")

    pane.hand_over(items)

    assert player.opened == [items[0].path]
    assert running[0].playback is pane.playback


def test_the_pass_opens_standing_on_the_item_it_is_told_to(qtbot, tmp_path):
    pane, player, _running = _pane(qtbot)
    items = _items(tmp_path, "one", "two")

    pane.hand_over(items, land=items[1].path)

    assert pane.playback.current_video == items[1].path


def test_a_second_pass_keeps_the_item_on_screen_where_it_survived(qtbot, tmp_path):
    pane, _player, _running = _pane(qtbot)
    one, two = _items(tmp_path, "one", "two")
    pane.hand_over([one, two])

    pane.hand_over([two, one])

    assert pane.playback.current_video == one.path
    assert pane.playback.playlist == [two.path, one.path]


def test_a_second_pass_lands_where_it_is_told(qtbot, tmp_path):
    pane, _player, _running = _pane(qtbot)
    one, two = _items(tmp_path, "one", "two")
    pane.hand_over([one, two])

    pane.hand_over([two, one], land=two.path)

    assert pane.playback.current_video == two.path


def test_a_pass_with_nothing_in_it_opens_nothing(qtbot):
    pane, _player, _running = _pane(qtbot)

    pane.hand_over([])

    assert pane.playback is None


def test_a_line_stands_where_the_picture_would_until_there_is_one(qtbot, tmp_path):
    pane, _player, _running = _pane(qtbot)

    pane.show_message("Generating…")
    assert pane.message() == "Generating…"

    pane.hand_over(_items(tmp_path, "one"))
    assert pane.message() == ""


def test_the_panel_the_show_hands_over_is_drawn_over_the_picture(qtbot, tmp_path):
    pane, player, _running = _pane(qtbot, panel=lambda: HudModel(player="portrait"))
    pane.hand_over(_items(tmp_path, "one"))

    pane.tick()

    assert HUD_OVERLAY_ID in player.overlays


def test_each_tick_gives_the_show_a_pass_of_its_own(qtbot, tmp_path):
    pane, _player, running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))

    pane.tick()

    assert running[0].ticks == 1


def test_a_press_on_the_picture_reaches_the_show(qtbot, tmp_path):
    pane, _player, running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    pane.tick()

    pane.press(QPointF(300, 300))

    assert running[0].commands == [OMNIPAUSE_TOGGLE]


def test_the_pointer_reaches_the_funestra_in_the_windows_own_pixels(qtbot, tmp_path, monkeypatch):
    pane, _player, _running = _pane(qtbot)
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
    pane, _player, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    turned = []
    monkeypatch.setattr(pane, "wheel", lambda position, steps: turned.append(steps))

    for delta in (-240, 120, 40):
        pane._window.wheelEvent(QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False))

    assert turned == [-2, 1, 1]


def test_a_double_click_reaches_the_show(qtbot):
    twice = []
    pane, _player, _running = _pane(qtbot, on_double_click=lambda: twice.append(1))

    pane.double_clicked()

    assert twice == [1]


def test_a_pass_handed_over_before_there_is_a_window_waits_for_one(qtbot, tmp_path):
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None)
    qtbot.addWidget(pane)
    items = _items(tmp_path, "one")
    pane.hand_over(items)
    assert pane.playback is None

    player = FakePlayer()
    pane._player_for = lambda wid: player
    pane._open_if_ready()

    assert player.opened == [items[0].path]


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
    monkeypatch.setattr("player_core.mpv_player.MpvPlayer",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("no engine")))

    pane.hand_over(_items(tmp_path, "one"))

    assert pane.playback is None
    assert "could not open" in caplog.text


def test_the_sound_set_before_the_funestra_opens_is_what_it_opens_with(qtbot, tmp_path):
    pane, player, _running = _pane(qtbot)
    pane.set_audio_muted(True)

    pane.hand_over(_items(tmp_path, "one"))

    assert player.muted is True


def test_the_sound_can_be_set_once_it_is_open(qtbot, tmp_path):
    pane, player, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))
    assert player.muted is False

    pane.set_audio_muted(True)

    assert player.muted is True


def test_the_drive_is_told_where_the_clip_has_got_to(qtbot, tmp_path):
    pane, player, _running = _pane(qtbot)
    assert pane.position() == 0
    pane.hand_over(_items(tmp_path, "one"))

    player.position_ms = 12345.6

    assert pane.position() == 12345


def test_closing_the_pane_closes_the_funestra_and_what_runs_on_it(qtbot, tmp_path):
    pane, player, running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))

    pane.close_engine()

    assert player.closed is True
    assert running[0].closed is True


def test_the_picture_keeps_moving_while_the_window_is_busy(qtbot, tmp_path):
    pane, player, _running = _pane(qtbot)
    pane.hand_over(_items(tmp_path, "one"))

    time.sleep(0.3)
    moved_while_busy = player.pushes
    pane.close_engine()

    assert moved_while_busy >= 5


def test_a_picture_that_stops_moving_says_why_in_the_log(qtbot, tmp_path, caplog):
    player = FakePlayer()

    def the_engine_gives_out():
        raise RuntimeError("made-up engine failure")

    player.push_still = the_engine_gives_out
    pane, _player, _running = _pane(qtbot, player=player)
    with caplog.at_level(logging.ERROR, logger="origenerator.gui.funestra_pane"):
        pane.hand_over(_items(tmp_path, "one"))
        giving_up_at = time.monotonic() + 2
        while "made-up engine failure" not in caplog.text and time.monotonic() < giving_up_at:
            time.sleep(0.02)
    pane.close_engine()

    assert "stopped moving" in caplog.text


def test_the_engine_copy_beside_the_checkouts_goes_in_front(monkeypatch, tmp_path):
    """The engine is one file, fetched once for the machine, with a copy beside
    the checkouts. The machine-wide folder has answered nothing at all to this
    app while answering every other process, so the copy beside goes first."""
    beside = tmp_path / "player_core" / "vendor"
    beside.mkdir(parents=True)
    (beside / "libmpv-2.dll").write_bytes(b"")
    monkeypatch.setattr(funestra_pane, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setenv("PATH", r"C:\somewhere\else")

    funestra_pane.offer_the_copy_beside_the_checkouts()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(beside)


def test_no_copy_beside_the_checkouts_leaves_the_path_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(funestra_pane, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setenv("PATH", r"C:\somewhere\else")

    funestra_pane.offer_the_copy_beside_the_checkouts()

    assert os.environ["PATH"] == r"C:\somewhere\else"


def test_a_pass_handed_over_before_the_pane_is_shown_opens_the_moment_it_is(qtbot, tmp_path):
    player = FakePlayer()
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None,
                        player_for=lambda wid: player if pane._window.isVisible() else None)
    qtbot.addWidget(pane)
    items = _items(tmp_path, "one")
    pane.hand_over(items)
    assert pane.playback is None

    pane.show()

    assert player.opened == [items[0].path]


def test_a_line_said_once_a_pass_is_owed_does_not_stand_in_front_of_the_picture(qtbot, tmp_path):
    player = FakePlayer()
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None,
                        player_for=lambda wid: player if pane._window.isVisible() else None)
    qtbot.addWidget(pane)
    items = _items(tmp_path, "one")
    pane.hand_over(items)
    pane.show_message("Generating…")

    pane.show()

    assert player.opened == [items[0].path]
    assert pane.message() == ""


def test_the_show_is_told_the_moment_its_funestra_opens(qtbot, tmp_path):
    told = []
    player = FakePlayer()
    pane = FunestraPane(user=lambda playback: _Running(playback), panel=lambda: None,
                        player_for=lambda wid: player if pane._window.isVisible() else None,
                        on_open=lambda: told.append(pane.playback))
    qtbot.addWidget(pane)
    pane.hand_over(_items(tmp_path, "one"))
    assert told == []

    pane.show()

    assert told == [pane.playback]
    assert pane.playback is not None
