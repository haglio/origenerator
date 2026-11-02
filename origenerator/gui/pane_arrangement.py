from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QBoxLayout, QSplitter, QWidget

from origenerator.gui.panes import PaneSplitter

TOC_OPENING_WIDTH = 220


class PaneArrangement:
    def __init__(self, *, toc: QWidget, gallery_pane: QWidget, generate_column: QWidget,
                 generate_pane: QWidget, queue: QWidget):
        self._toc = toc
        self._generate_column = generate_column
        self._generate_pane = generate_pane
        self._queue = queue
        self.panes = PaneSplitter(Qt.Orientation.Horizontal, "panes")
        self.folder_panes = PaneSplitter(Qt.Orientation.Horizontal, "folder_panes")
        self.stack: QSplitter | None = None
        self.left_column: QSplitter | None = None
        toc.setMinimumWidth(120)
        gallery_pane.setMinimumWidth(210)
        self.folder_panes.addWidget(gallery_pane)

    def standalone(self) -> QSplitter:
        self.left_column = PaneSplitter(Qt.Orientation.Vertical, "left_column")
        self.folder_panes.insertWidget(0, self._toc)
        self.left_column.addWidget(self.folder_panes)
        self.left_column.addWidget(self._queue)
        self.panes.addWidget(self.left_column)
        self.panes.addWidget(self._generate_column)
        self.folder_panes.setStretchFactor(0, 0)
        self.folder_panes.setStretchFactor(1, 1)
        self.folder_panes.setSizes([max(TOC_OPENING_WIDTH, self._toc.sizeHint().width()), 560])
        self.left_column.setStretchFactor(0, 1)
        self.left_column.setStretchFactor(1, 0)
        self.left_column.setSizes([600, self._queue.minimumHeight()])
        self.panes.setStretchFactor(0, 3)
        self.panes.setStretchFactor(1, 2)
        self.panes.setSizes([780, 440])
        return self.panes

    def hosted(self) -> QSplitter:
        self.stack = PaneSplitter(Qt.Orientation.Vertical)
        self.panes.insertWidget(0, self._toc)
        self.panes.insertWidget(1, self.folder_panes)

        self.stack.addWidget(self._generate_column)
        self.stack.addWidget(self.panes)
        self.stack.addWidget(self._queue)
        self._generate_pane.setMinimumWidth(210)
        self._generate_column.setMinimumWidth(210)
        self.panes.setStretchFactor(0, 0)
        self.panes.setStretchFactor(1, 1)
        self.panes.setSizes([TOC_OPENING_WIDTH, 660])
        self.stack.setStretchFactor(0, 2)
        self.stack.setStretchFactor(1, 3)
        self.stack.setStretchFactor(2, 0)
        self.stack.setSizes([440, 640, self._queue.minimumHeight()])
        return self.stack

    def fold_into_the_session_column(self, layout: QBoxLayout) -> None:
        layout.removeWidget(self.panes)
        left_column, self.left_column = self.left_column, None
        left_column.setParent(None)
        layout.addWidget(self.hosted(), 1)
        left_column.deleteLater()

    def unfold_from_the_session_column(self, layout: QBoxLayout) -> None:
        layout.removeWidget(self.stack)
        stack, self.stack = self.stack, None
        self._generate_pane.setMinimumWidth(0)
        self._generate_column.setMinimumWidth(0)
        layout.addWidget(self.standalone(), 1)
        stack.setParent(None)
        stack.deleteLater()
