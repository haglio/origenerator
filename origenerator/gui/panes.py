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


def _as_panes(splitter: QSplitter) -> QSplitter:
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(6)
    return splitter


def pane_splitter(orientation: Qt.Orientation) -> QSplitter:
    """Panes parted by the thick handle that is dragged to resize them, none of
    which can be dragged shut."""
    return _as_panes(QSplitter(orientation))


class FootSplitter(QSplitter):
    """Panes stacked over a foot that opens at the foot's own height and follows
    it as that changes, until its handle is dragged."""

    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        _as_panes(self)
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
