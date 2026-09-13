"""The splitters that part the gallery's panes."""
from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.panes import FootSplitter


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


def test_a_dragged_handle_leaves_the_foot_where_it_was_dragged(qtbot):
    splitter, foot = _laid_out(qtbot)

    splitter.moveSplitter(splitter.height() - splitter.handleWidth() - 120, 1)
    _settle()
    foot.wanted = 260
    foot.updateGeometry()
    _settle()

    assert foot.height() == 120
