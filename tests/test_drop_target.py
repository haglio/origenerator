"""A pane that takes drags where another part of the app says they land, and
wears the drop zones' style while one is under way that it would take."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.browser_pane import BrowserScrollArea
from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.stylesheet import build_stylesheet
from tests.drop_style_seen import worn


def _pane(qtbot, landing=lambda _mime, _source: ("taken",)):
    """A scrolling pane of plain content, as the middle pane is, taking drops.
    A drag a test leaves held over it is let go of before the pane closes:
    Qt sends every later drag event to the last widget that took one, even
    once that widget is gone."""
    pane = BrowserScrollArea()
    pane.setWidgetResizable(True)
    pane.setWidget(QWidget())
    pane.setStyleSheet(build_stylesheet())
    DropTarget(pane, landing, lambda *_landing: None)
    qtbot.addWidget(pane, before_close_func=lambda held: QApplication.sendEvent(
        held.viewport(), QDragLeaveEvent()))
    pane.resize(300, 200)
    with qtbot.waitExposed(pane):
        pane.show()
    return pane


def _style_worn(pane):
    return worn(pane.grab().toImage(), pane.rect())


def test_a_pane_lights_while_a_drag_it_would_take_is_under_way(qtbot):
    pane = _pane(qtbot)
    assert _style_worn(pane) is None

    under_way.started.emit(generation_mime("p1"), None)

    assert _style_worn(pane) == LIT


def _hold_over(pane, mime):
    """Bring a drag of ``mime`` over the middle of ``pane`` and hold it there."""
    held = (pane.viewport().rect().center(), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    for event in (QDragEnterEvent(*held), QDragMoveEvent(*held)):
        QApplication.sendEvent(pane.viewport(), event)


def test_the_pane_under_the_drag_lights_one_step_lighter(qtbot):
    pane = _pane(qtbot)
    mime = generation_mime("p1")
    under_way.started.emit(mime, None)

    _hold_over(pane, mime)

    assert _style_worn(pane) == AIMED


def test_a_drag_leaving_the_pane_leaves_it_only_lit(qtbot):
    pane = _pane(qtbot)
    mime = generation_mime("p1")
    under_way.started.emit(mime, None)
    _hold_over(pane, mime)

    QApplication.sendEvent(pane.viewport(), QDragLeaveEvent())

    assert _style_worn(pane) == LIT


def test_a_drag_ending_over_the_pane_leaves_it_dark(qtbot):
    pane = _pane(qtbot)
    mime = generation_mime("p1")
    under_way.started.emit(mime, None)
    _hold_over(pane, mime)

    under_way.ended.emit()

    assert _style_worn(pane) is None


def test_a_pane_that_would_turn_the_drag_away_stays_as_it_is(qtbot):
    pane = _pane(qtbot, landing=lambda _mime, _source: None)
    mime = generation_mime("p1")

    under_way.started.emit(mime, None)
    _hold_over(pane, mime)

    assert _style_worn(pane) is None
