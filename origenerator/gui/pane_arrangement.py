"""Which splitter holds which pane, standalone and inside a Fun Time session.

The three panes live in splitters, so the divider between each doubles as a
drag handle: the TOC pane (folder tree), the Gallery pane (a folder's
contents), and the Generate pane (preview + metadata).

Nested rather than flat, because the Job Queue belongs to the first two and
not to the third: the tree and the Gallery pane sit side by side in ``folder_panes``,
the Job Queue goes under both of them in ``left_column``, and the Generate pane stands
beside that whole column at full height. Its tabs are where the user reads and
edits a generation, and the Job Queue cutting across their foot would take that
height for a queue they can already see next to it.

Hosted by Fun Time the rect is an upright column, so the panes fold into
``stack`` instead of sitting side by side: the Generate pane on top, the tree and
Gallery pane as one row under it, and the queue across the foot of all three:
hosted, the queue belongs to the window rather than to the folder column, so
there is no ``left_column`` at all on that side.
"""
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
        """The three panes side by side, as a window of its own opens them."""
        self.left_column = PaneSplitter(Qt.Orientation.Vertical, "left_column")
        self.folder_panes.insertWidget(0, self._toc)
        self.left_column.addWidget(self.folder_panes)
        self.left_column.addWidget(self._queue)
        self.panes.addWidget(self.left_column)
        self.panes.addWidget(self._generate_column)
        # The TOC pane holds its width; the Gallery pane and Generate pane both grow
        # with the window (the Gallery pane faster), so the Generate pane stays
        # comfortably wide instead of a thin sliver on a large screen. Long
        # metadata values wrap rather than scroll sideways, so these floors
        # only need to keep the panes readable — kept low enough that the
        # window can still tile into a monitor third or a portrait-monitor
        # half.
        # No floor of its own on the Generate pane: the Generate tab inside it
        # reports what its settings need (GenerateTab.minimumSizeHint),
        # and an explicit minimum here would replace that number rather than
        # join it — pinning the pane narrower than its contents and putting a
        # horizontal scroll bar back under the form.
        self.folder_panes.setStretchFactor(0, 0)  # the TOC pane holds its width
        self.folder_panes.setStretchFactor(1, 1)  # the Gallery pane takes the growth
        self.folder_panes.setSizes([max(TOC_OPENING_WIDTH, self._toc.sizeHint().width()), 560])
        # The Job Queue opens at its own height and stays there: all the growth
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
        self.stack = PaneSplitter(Qt.Orientation.Vertical)
        # Hosted, the Job Queue does not run under the folder column.  It spans the
        # whole foot of the rect (added to stack below), so the corner
        # under the tree is the queue rather than more tree — which is where
        # a standalone window's eye finds it, and the upright fold has no
        # reason to move it.  The folder panes go straight beside the tree.
        self.panes.insertWidget(0, self._toc)
        self.panes.insertWidget(1, self.folder_panes)

        # The upright arrangement, from the top down: the generate tabs (with
        # the find bar riding under them), then the Gallery pane beside the
        # tree, then the queue across the foot.  The generator
        # leads because it is what the user is doing — a tall rect that
        # opens on a folder listing puts the form they came to fill below
        # the fold.  The floors shrink with the column: each floor spans the
        # stack's whole width, so a side-by-side floor would only fight the
        # tree for room it no longer shares.
        self.stack.addWidget(self._generate_column)
        self.stack.addWidget(self.panes)
        self.stack.addWidget(self._queue)
        self._generate_pane.setMinimumWidth(210)
        self._generate_column.setMinimumWidth(210)
        self.panes.setStretchFactor(0, 0)
        self.panes.setStretchFactor(1, 1)
        self.panes.setSizes([TOC_OPENING_WIDTH, 660])
        # The Job Queue opens at its own height and stays there, as it does
        # standalone: a taller rect is more gallery and more form, not more
        # queue.  The two panes above it split the rest, the Gallery pane a
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
        self._generate_pane.setMinimumWidth(0)
        self._generate_column.setMinimumWidth(0)
        layout.addWidget(self.standalone(), 1)
        stack.setParent(None)
        stack.deleteLater()
