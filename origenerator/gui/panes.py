from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QFrame, QLayout, QSplitter, QVBoxLayout, QWidget
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD

BORDER_WIDTH = 6
BORDER_NAME = "paneBorder"
BORDERED_SET = "borderedSet"


def pane() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    column = QVBoxLayout(widget)
    column.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                              MARGIN_STANDARD, MARGIN_STANDARD)
    return widget, column


def border_as_a_set(frame: QFrame, layout: QLayout) -> None:
    frame.setObjectName(BORDERED_SET)
    layout.setContentsMargins(MARGIN_STANDARD, GAP_SMALL, MARGIN_STANDARD, MARGIN_STANDARD)


def pane_border() -> QFrame:
    border = QFrame()
    border.setObjectName(BORDER_NAME)
    border.setFixedHeight(BORDER_WIDTH)
    return border


class PaneSplitter(QSplitter):
    """Panes parted by the thick handle that is dragged to resize them, none of
    which can be dragged shut."""

    def __init__(self, orientation: Qt.Orientation, remembered_as: str = ""):
        super().__init__(orientation)
        self.remembered_as = remembered_as
        self.setObjectName(remembered_as)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(BORDER_WIDTH)
        self._dragged = False
        self.splitterMoved.connect(self._on_dragged)

    def _on_dragged(self, _position: int, _index: int) -> None:
        self._dragged = True

    def dragged_sizes(self) -> list[int] | None:
        return self.sizes() if self._dragged else None

    def take_dragged_sizes(self, sizes) -> None:
        if (isinstance(sizes, list) and len(sizes) == self.count()
                and all(type(size) is int and size >= 0 for size in sizes)):
            self.setSizes(sizes)
            self._dragged = True

    def hold_still(self, held: bool) -> None:
        for index in range(self.count()):
            self.handle(index).setEnabled(not held)


def hold_the_borders_still(within: QWidget, held: bool) -> None:
    for splitter in within.findChildren(PaneSplitter):
        splitter.hold_still(held)


class RememberedBorders:
    """Where each remembered border of a window was last dragged, kept while the
    window's panes stand in a shape that is not theirs."""

    def __init__(self, window: QWidget):
        self._window = window
        self._sizes: dict[str, list[int]] = {}

    def sizes(self) -> dict[str, list[int]]:
        return dict(self._sizes)

    def keep_where_they_are(self) -> None:
        self._sizes.update({splitter.remembered_as: sizes for splitter in self._borders()
                            if (sizes := splitter.dragged_sizes()) is not None})

    def take(self, saved) -> None:
        if isinstance(saved, dict):
            self._sizes = {name: sizes for name, sizes in saved.items()
                           if isinstance(name, str) and isinstance(sizes, list)}

    def put_back(self) -> None:
        for splitter in self._borders():
            splitter.take_dragged_sizes(self._sizes.get(splitter.remembered_as))

    def _borders(self) -> list[PaneSplitter]:
        return [splitter for splitter in self._window.findChildren(PaneSplitter)
                if splitter.remembered_as]


class FootSplitter(PaneSplitter):
    """Panes stacked over a foot that opens at the foot's own height and follows
    it as that changes, until its handle is dragged."""

    def __init__(self, remembered_as: str = ""):
        super().__init__(Qt.Orientation.Vertical, remembered_as)

    def event(self, event):
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            self._fit_the_foot()
        return handled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_the_foot()

    def _fit_the_foot(self) -> None:
        if self._dragged or self.count() < 2:
            return
        wanted = self.widget(self.count() - 1).sizeHint().height()
        self.setSizes([self.height() - self.handleWidth() - wanted, wanted])
