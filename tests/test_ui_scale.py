"""The hosted app draws at the session's HUD scale, and rects survive it."""

from __future__ import annotations

import os

import pytest
from shared_ui.spacing import BUTTON_SIZE, BUTTON_SIZE_HUD

from origenerator import ui_scale


@pytest.fixture(autouse=True)
def clean_env():
    """QT_SCALE_FACTOR is process-global, and apply_hosted_scale writes it
    straight into os.environ — so it is cleared on the way OUT as well as in.
    Left set, it scales every Qt widget built by every later test in the run."""
    os.environ.pop("QT_SCALE_FACTOR", None)
    yield
    os.environ.pop("QT_SCALE_FACTOR", None)


def test_the_hosted_scale_makes_this_apps_buttons_the_huds_buttons():
    # The whole point of the number: a BUTTON_SIZE square drawn at this factor
    # lands on the screen the size of a BUTTON_SIZE_HUD one.
    assert round(BUTTON_SIZE * ui_scale.HOSTED_SCALE) == BUTTON_SIZE_HUD


def test_applying_the_scale_sets_what_qt_reads(monkeypatch):
    assert ui_scale.active_scale() == 1.0  # nothing has scaled us
    applied = ui_scale.apply_hosted_scale()
    assert applied == ui_scale.HOSTED_SCALE
    assert float(os.environ["QT_SCALE_FACTOR"]) == ui_scale.HOSTED_SCALE
    assert ui_scale.active_scale() == ui_scale.HOSTED_SCALE


def test_a_scale_already_in_the_environment_wins(monkeypatch):
    monkeypatch.setenv("QT_SCALE_FACTOR", "1.5")
    assert ui_scale.apply_hosted_scale() == 1.5
    assert ui_scale.active_scale() == 1.5


def test_an_unreadable_scale_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("QT_SCALE_FACTOR", "not-a-number")
    assert ui_scale.apply_hosted_scale() == ui_scale.HOSTED_SCALE


def test_unscaled_lengths_pass_through_untouched():
    assert ui_scale.to_logical_size(1280) == 1280
    assert ui_scale.to_logical_size(0) == 0


def test_an_unscaled_rect_passes_through_untouched():
    assert ui_scale.to_logical_rect(2560, 3, 1440, 3440) == (2560, 3, 1440, 3440)


def test_a_length_scales_back_to_the_device_pixels_it_named():
    ui_scale.apply_hosted_scale()
    scale = ui_scale.HOSTED_SCALE
    for edge in (0, 720, 1280, 1281, 1440, 2560):
        assert abs(ui_scale.to_logical_size(edge) * scale - edge) <= 1


def test_a_rect_converts_against_its_own_screens_origin(monkeypatch):
    """The bug this function exists for.  Qt leaves each scaled screen's ORIGIN
    at its device position and scales only its size, so dividing a whole-desktop
    x by the scale lands deep inside the second monitor rather than at its left
    edge — which put the portrait show in the right third of its region, hanging
    off the monitor."""
    ui_scale.apply_hosted_scale()
    scale = ui_scale.HOSTED_SCALE
    # The real pair off this machine: a 2560-wide primary, a portrait beside it.
    monkeypatch.setattr(ui_scale, "_screen_origin", lambda x, y: (2560, 3))
    x, y, width, height = ui_scale.to_logical_rect(2560, 3, 1440, 3440)

    assert (x, y) == (2560, 3)  # the screen's own left edge, not 2560/scale
    # And Qt renders it back onto the device rect the session measured.
    assert abs(2560 + (x - 2560) * scale - 2560) <= 1
    assert abs(width * scale - 1440) <= 1
    assert abs(height * scale - 3440) <= 1


def test_a_rect_inside_a_screen_keeps_its_offset_from_that_screens_edge(monkeypatch):
    ui_scale.apply_hosted_scale()
    scale = ui_scale.HOSTED_SCALE
    monkeypatch.setattr(ui_scale, "_screen_origin", lambda x, y: (2560, 3))
    x, _y, _w, _h = ui_scale.to_logical_rect(2560 + 400, 3, 200, 200)

    # 400 device px in from the screen edge, and it renders back to 400.
    assert abs((x - 2560) * scale - 400) <= 1


def test_the_hud_bitmap_is_pinned_to_device_pixels(qapp):
    """An 18px HUD button is already the size it should be on screen, so the
    core window's scale must not shrink it: the pixmap's ratio cancels it."""
    from PyQt6.QtGui import QPixmap

    ui_scale.apply_hosted_scale()
    pixmap = ui_scale.unscaled_pixmap(QPixmap(280, 140))

    assert pixmap.devicePixelRatio() == ui_scale.HOSTED_SCALE
    # Widget size (logical) times the scale is the bitmap's own pixel size.
    logical = pixmap.deviceIndependentSize()
    assert abs(logical.width() * ui_scale.HOSTED_SCALE - 280) <= 1
    assert abs(logical.height() * ui_scale.HOSTED_SCALE - 140) <= 1


def test_a_press_on_that_bitmap_indexes_it_in_its_own_pixels():
    ui_scale.apply_hosted_scale()
    # A click at the far corner of the widget is the far corner of the bitmap.
    assert ui_scale.to_bitmap_pos(0, 0) == (0, 0)
    x, y = ui_scale.to_bitmap_pos(280 / ui_scale.HOSTED_SCALE, 140 / ui_scale.HOSTED_SCALE)
    assert abs(x - 280) <= 1 and abs(y - 140) <= 1


def test_presses_are_untouched_when_nothing_scaled_the_app():
    assert ui_scale.to_bitmap_pos(37, 21) == (37, 21)


def test_the_scale_is_applied_before_pyqt_is_imported():
    """Qt reads QT_SCALE_FACTOR as the platform plugin starts, so a call that
    lands after the first PyQt6 import sets a variable nothing will read again.
    The ordering inside main() is the whole contract, so it is asserted here --
    off the syntax tree, so a reformat of either line leaves it standing."""
    import ast
    import inspect

    from origenerator import app as app_module

    main = ast.parse(inspect.getsource(app_module.main))
    applied = min(node.lineno for node in ast.walk(main)
                  if isinstance(node, ast.Call)
                  and ast.unparse(node.func).endswith("apply_hosted_scale"))
    imported = min(node.lineno for node in ast.walk(main)
                   if isinstance(node, ast.ImportFrom)
                   and (node.module or "").startswith("PyQt6"))
    assert applied < imported


def test_only_a_hosted_launch_turns_the_scale_on():
    from origenerator.fun_time_mode import parse_app_args

    assert parse_app_args([]).fun_time is None          # standalone: unscaled
    assert parse_app_args(["--fun-time"]).fun_time is not None
