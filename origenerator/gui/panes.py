from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QSplitter, QVBoxLayout, QWidget
from shared_ui.spacing import MARGIN_STANDARD


def pane() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    column = QVBoxLayout(widget)
    column.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                              MARGIN_STANDARD, MARGIN_STANDARD)
    return widget, column


class PaneSplitter(QSplitter):
    """Panes parted by the thick handle that is dragged to resize them, none of
    which can be dragged shut."""

    def __init__(self, orientation: Qt.Orientation):
        super().__init__(orientation)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(6)

    def hold_still(self, held: bool) -> None:
        for index in range(self.count()):
            self.handle(index).setEnabled(not held)


def hold_the_borders_still(within: QWidget, held: bool) -> None:
    for splitter in within.findChildren(PaneSplitter):
        splitter.hold_still(held)


class FootSplitter(PaneSplitter):
    """Panes stacked over a foot that opens at the foot's own height and follows
    it as that changes, until its handle is dragged."""

    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self._dragged = False
        self.splitterMoved.connect(self._on_dragged)

    def event(self, event):
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            self._fit_the_foot()
        return handled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_the_foot()

    def _on_dragged(self, _position: int, _index: int) -> None:
        self._dragged = True

    def _fit_the_foot(self) -> None:
        if self._dragged or self.count() < 2:
            return
        wanted = self.widget(self.count() - 1).sizeHint().height()
        self.setSizes([self.height() - self.handleWidth() - wanted, wanted])
