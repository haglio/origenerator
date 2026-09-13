"""Which splitter holds which pane, standalone and inside a Fun Time session.

The three panes live in splitters, so the divider between each doubles as a
drag handle: the TOC pane (folder tree), the browser pane (a folder's
contents), and the info pane (preview + metadata).

Nested rather than flat, because the queue strip belongs to the first two and
not to the third: the tree and the browser sit side by side in ``folder_panes``,
the strip goes under both of them in ``left_column``, and the info pane stands
beside that whole column at full height. Its tabs are where the user reads and
edits a generation, and a strip cutting across their foot would take that
height for a queue they can already see next to it.

Hosted by Fun Time the rect is an upright column, so the panes fold into
``stack`` instead of sitting side by side: the info pane on top, the tree and
browser as one row under it, and the queue across the foot of all three:
hosted, the queue belongs to the window rather than to the folder column, so
there is no ``left_column`` at all on that side.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QBoxLayout, QSplitter, QWidget


def _splitter(orientation: Qt.Orientation) -> QSplitter:
    splitter = QSplitter(orientation)
    splitter.setChildrenCollapsible(False)  # a pane can't be dragged shut
    splitter.setHandleWidth(6)
    return splitter


class PaneArrangement:
    def __init__(self, *, toc: QWidget, browser: QWidget, info_pane: QWidget,
                 info_tabs: QWidget, queue: QWidget):
        self._toc = toc
        self._info_pane = info_pane
        self._info_tabs = info_tabs
        self._queue = queue
        self.panes = _splitter(Qt.Orientation.Horizontal)
        self.folder_panes = _splitter(Qt.Orientation.Horizontal)
        self.stack: QSplitter | None = None
        self.left_column: QSplitter | None = None
        toc.setMinimumWidth(120)
        browser.setMinimumWidth(210)
        self.folder_panes.addWidget(browser)

    def standalone(self) -> QSplitter:
        """The three panes side by side, as a window of its own opens them."""
        self.left_column = _splitter(Qt.Orientation.Vertical)
        self.folder_panes.insertWidget(0, self._toc)
        self.left_column.addWidget(self.folder_panes)
        self.left_column.addWidget(self._queue)
        self.panes.addWidget(self.left_column)
        self.panes.addWidget(self._info_pane)
        # The TOC pane holds its width; the browser and info panes both grow
        # with the window (the browser faster), so the info pane stays
        # comfortably wide instead of a thin strip on a large screen. Long
        # metadata values wrap rather than scroll sideways, so these floors
        # only need to keep the panes readable — kept low enough that the
        # window can still tile into a monitor third or a portrait-monitor
        # half.
        # No floor of its own on the info pane: the config tab inside it
        # reports what its settings need (GenerateConfigPanel.minimumSizeHint),
        # and an explicit minimum here would replace that number rather than
        # join it — pinning the pane narrower than its contents and putting a
        # horizontal scroll bar back under the form.
        self.folder_panes.setStretchFactor(0, 0)  # the TOC pane holds its width
        self.folder_panes.setStretchFactor(1, 1)  # the browser takes the growth
        self.folder_panes.setSizes([220, 560])
        # The strip opens at its own height and stays there: all the growth
        # goes to the folders above it, so a taller window is more gallery
        # rather than more queue.
        self.left_column.setStretchFactor(0, 1)
        self.left_column.setStretchFactor(1, 0)
        self.left_column.setSizes([600, self._queue.minimumHeight()])
        self.panes.setStretchFactor(0, 3)
        self.panes.setStretchFactor(1, 2)
        self.panes.setSizes([780, 440])
        return self.panes

    def hosted(self) -> QSplitter:
        """The upright arrangement a Fun Time session's rect asks for."""
        self.stack = _splitter(Qt.Orientation.Vertical)
        # Hosted, the queue is not the folder column's strip.  It spans the
        # whole foot of the rect (added to stack below), so the corner
        # under the tree is the queue rather than more tree — which is where
        # a standalone window's eye finds it, and the upright fold has no
        # reason to move it.  The folder panes go straight beside the tree.
        self.panes.insertWidget(0, self._toc)
        self.panes.insertWidget(1, self.folder_panes)

        # The upright arrangement, from the top down: the generate tabs (with
        # the find bar riding under them), then the browser beside a
        # collapsible tree, then the queue across the foot.  The generator
        # leads because it is what the user is doing — a tall rect that
        # opens on a folder listing puts the form they came to fill below
        # the fold.  The floors shrink with the column: each floor spans the
        # stack's whole width, so a side-by-side floor would only fight the
        # tree for room it no longer shares.
        self.stack.addWidget(self._info_pane)
        self.stack.addWidget(self.panes)
        self.stack.addWidget(self._queue)
        self.panes.setCollapsible(0, True)  # the tree may be dragged shut
        self._info_tabs.setMinimumWidth(210)
        self._info_pane.setMinimumWidth(210)
        self.panes.setStretchFactor(0, 0)
        self.panes.setStretchFactor(1, 1)
        self.panes.setSizes([180, 660])
        # The strip opens at its own height and stays there, as it does
        # standalone: a taller rect is more gallery and more form, not more
        # queue.  The two panes above it split the rest, the browser a
        # little ahead so the tree it sits beside has room to be read.
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
        self._info_tabs.setMinimumWidth(0)
        self._info_pane.setMinimumWidth(0)
        layout.addWidget(self.standalone(), 1)
        stack.setParent(None)
        stack.deleteLater()
