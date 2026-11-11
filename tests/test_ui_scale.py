from __future__ import annotations

import ast
import inspect
import os

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QWidget
from shared_ui.spacing import BUTTON_SIZE, BUTTON_SIZE_HUD

from origenerator import app as app_module
from origenerator import ui_scale
from origenerator.fun_time_mode import parse_app_args
from tests.hosted_launch import hosted_launch


@pytest.fixture(autouse=True)
def clean_env():
    os.environ.pop("QT_SCALE_FACTOR", None)
    yield
    os.environ.pop("QT_SCALE_FACTOR", None)


def test_the_hosted_scale_makes_this_apps_buttons_the_huds_buttons():
    assert round(BUTTON_SIZE * ui_scale.HOSTED_SCALE) == BUTTON_SIZE_HUD, (
        "hosted, this app sits inches from the session's Satellite HUDs, which draw at the "
        "family's smaller size")


def test_applying_the_scale_sets_what_qt_reads(monkeypatch):
    assert ui_scale.active_scale() == 1.0
    applied = ui_scale.apply_room_scale(in_a_headset=False)
    assert applied == ui_scale.HOSTED_SCALE
    assert float(os.environ["QT_SCALE_FACTOR"]) == ui_scale.HOSTED_SCALE
    assert ui_scale.active_scale() == ui_scale.HOSTED_SCALE


def test_a_headset_launch_is_not_shrunk_at_all():
    assert ui_scale.apply_room_scale(in_a_headset=True) == 1.0
    assert "QT_SCALE_FACTOR" not in os.environ


def test_a_scale_already_in_the_environment_wins(monkeypatch):
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.5")
    assert ui_scale.apply_room_scale(in_a_headset=False) == 1.5, (
        "someone who set it meant it, and this app is not the only reason a process might be scaled")
    assert ui_scale.active_scale() == 1.5


def test_an_unreadable_scale_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("QT_SCALE_FACTOR", "not-a-number")
    assert ui_scale.apply_room_scale(in_a_headset=False) == ui_scale.HOSTED_SCALE


def test_the_scale_is_applied_before_pyqt_is_imported():
    main = ast.parse(inspect.getsource(app_module.main))
    applied = min(node.lineno for node in ast.walk(main)
                  if isinstance(node, ast.Call)
                  and ast.unparse(node.func).endswith("apply_room_scale"))
    imported = min(node.lineno for node in ast.walk(main)
                   if isinstance(node, ast.ImportFrom)
                   and (node.module or "").startswith(("PyQt6", "origenerator.gui", "shared_ui")))
    assert applied < imported


def test_a_running_app_is_redrawn_at_a_new_scale_and_back(qapp):
    window = QWidget()
    window.show()

    ui_scale.draw_at(ui_scale.HOSTED_SCALE)
    window.hide()
    window.show()
    qapp.processEvents()
    shrunk = window.devicePixelRatio()
    ui_scale.draw_at(1.0)
    window.hide()
    window.show()
    qapp.processEvents()

    assert shrunk == pytest.approx(ui_scale.HOSTED_SCALE)
    assert window.devicePixelRatio() == 1.0
    assert ui_scale.active_scale() == 1.0
    window.close()


def test_icons_drawn_after_the_scale_comes_back_down_are_drawn_unscaled(qapp):
    try:
        ui_scale.draw_at(1.25)
        assert _an_icon_drawn_at(QSize(20, 20)).size() == QSize(25, 25)
        ui_scale.draw_at(1.0)

        assert _an_icon_drawn_at(QSize(20, 20)).size() == QSize(20, 20)
    finally:
        ui_scale.draw_at(1.0)


def _an_icon_drawn_at(size: QSize) -> QPixmap:
    canvas = QPixmap(64, 64)
    canvas.fill(Qt.GlobalColor.red)
    return QIcon(canvas).pixmap(size)


def test_a_qt_that_cannot_be_rescaled_leaves_the_app_at_its_size(monkeypatch):
    class QtWithoutTheSetter:
        pass

    monkeypatch.setattr(ui_scale.ctypes, "WinDLL", lambda _name: QtWithoutTheSetter())

    ui_scale.draw_at(ui_scale.HOSTED_SCALE)

    assert ui_scale.active_scale() == 1.0


def test_only_a_hosted_launch_turns_the_scale_on():
    assert parse_app_args([]).fun_time is None
    assert parse_app_args(hosted_launch()).fun_time is not None
