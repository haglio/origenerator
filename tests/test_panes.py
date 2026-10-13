"""The splitters that part the gallery's panes."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PyQt6.QtGui import QHoverEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.panes import FootSplitter, PaneSplitter
from origenerator.gui.stylesheet import build_stylesheet


class _Wanting(QWidget):
    """A pane that asks for a height a test can change."""

    def __init__(self, height):
        super().__init__()
        self.wanted = height

    def sizeHint(self):
        return QSize(100, self.wanted)

    def minimumSizeHint(self):
        return QSize(10, 10)


def _settle():
    for _ in range(4):  # a resize posts the layout pass that fits the foot
        QApplication.processEvents()


def _laid_out(qtbot, height=600):
    splitter = FootSplitter()
    qtbot.addWidget(splitter)
    foot = _Wanting(180)
    splitter.addWidget(_Wanting(100))
    splitter.addWidget(foot)
    splitter.resize(300, height)
    splitter.show()
    _settle()
    return splitter, foot


def test_the_foot_opens_at_its_own_height(qtbot):
    _splitter, foot = _laid_out(qtbot)

    assert foot.height() == 180


def test_the_foot_follows_its_own_height_as_it_changes(qtbot):
    _splitter, foot = _laid_out(qtbot)

    foot.wanted = 260
    foot.updateGeometry()
    _settle()

    assert foot.height() == 260


def _two_panes(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Vertical)
    qtbot.addWidget(splitter)
    splitter.addWidget(_Wanting(100))
    splitter.addWidget(_Wanting(100))
    splitter.resize(300, 600)
    splitter.show()
    _settle()
    return splitter


def _drag(handle, down_by):
    grabbed = handle.rect().center()
    dropped = grabbed + QPoint(0, down_by)
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=grabbed)
    QTest.mouseMove(handle, dropped)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=dropped)
    _settle()


def test_a_handle_let_go_is_dragged_again(qtbot):
    splitter = _two_panes(qtbot)
    first, _ = splitter.sizes()

    splitter.hold_still(True)
    splitter.hold_still(False)
    _drag(splitter.handle(1), 120)

    assert splitter.sizes()[0] == first + 120


def test_a_held_splitter_is_not_moved_by_dragging_its_handle(qtbot):
    """Where its panes are held, a thick border neither moves nor offers to: a
    disabled handle takes no drag, and Qt shows no resize pointer over a
    disabled widget nor lights it under the pointer."""
    splitter = _two_panes(qtbot)
    before = splitter.sizes()

    splitter.hold_still(True)
    _drag(splitter.handle(1), 120)

    assert splitter.sizes() == before
    assert not splitter.handle(1).isEnabled()


def _under_the_pointer(handle):
    def middle():
        image = handle.grab().toImage()
        return image.pixelColor(image.width() // 2, image.height() // 2)

    resting = middle()
    here = QPointF(handle.rect().center())
    QApplication.sendEvent(handle, QHoverEvent(QEvent.Type.HoverEnter, here, here, QPointF(-1, -1)))
    return resting, middle()


def test_only_a_handle_that_moves_lights_up_under_the_pointer(qtbot):
    """Lit blue under the pointer, a border says it can be dragged, and a held
    one cannot."""
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        free, held = _two_panes(qtbot), _two_panes(qtbot)
        held.hold_still(True)

        resting, lit = _under_the_pointer(free.handle(1))
        assert lit != resting
        resting, lit = _under_the_pointer(held.handle(1))
        assert lit == resting
    finally:
        app.setStyleSheet(prior)


def test_a_dragged_handle_leaves_the_foot_where_it_was_dragged(qtbot):
    splitter, foot = _laid_out(qtbot)

    splitter.moveSplitter(splitter.height() - splitter.handleWidth() - 120, 1)
    _settle()
    foot.wanted = 260
    foot.updateGeometry()
    _settle()

    assert foot.height() == 120
