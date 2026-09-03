"""The TOC pane's two halves: one folder tree per shape, each under a standing label.

The gallery's table of contents exists twice over, once per shape (see
:mod:`origenerator.gui.orientation`), and this is how the pane shows both at
once: a :class:`~origenerator.gui.folder_tree.FolderTree` per side, stacked
under a label that never scrolls away, on a splitter so either half can be
given the room.

Two halves rather than two rows in one tree.  Nesting a whole table of contents
under a top-level row costs every folder in it a level of indentation in the
narrowest column of the window, hides which side you are in the moment that row
scrolls off, and makes the two libraries share one scrollbar — so reaching a
settings folder deep in Landscape scrolls the whole of Portrait away first.
Each half scrolling on its own keeps both readable, and the labels are the
answer to "which one am I in" without looking up — each one led by a small
frame of its own shape, upright or lying down, which answers it a beat before
the word does.

The two are mutually exclusive: a row picked in one half clears the other's
selection, so "the folder on screen" is always one folder, and a set picked
across both — which is how a mixed-shape grouping would be composed — cannot
be expressed at all.  Everything above this widget goes on talking to one tree:
the signals a ``FolderTree`` emits are re-emitted here from whichever half
fired them, and the handful of methods the view calls resolve to the half that
owns the row.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)

from origenerator.gui import icons
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.orientation import ORIENTATION_LABELS, ORIENTATIONS

# Neither half is allowed to shrink to nothing: a half with no rows visible is
# a side of the library that looks like it isn't there.
_MIN_HALF_HEIGHT = 90


def _heading(orientation: str) -> QFrame:
    """One half's standing label: the shape's proportion mark, then its name.

    The mark is there because the two halves differ by a shape, and a shape is
    read faster as one — the eye lands on an upright frame or a lying-down one
    and is already in the right library before the word is spelled out.

    A frame carrying two labels rather than one label carrying a word, so the
    mark sits beside the name inside the rule the stylesheet draws under the
    whole heading. Only the frame gets the tooltip: Qt hands a tooltip event up
    from a child that has none of its own, so one description covers the
    heading wherever in it the cursor stops.
    """
    heading = QFrame()
    heading.setObjectName("treeSectionLabel")
    heading.setToolTip(
        f"Everything {orientation}-shaped — its own shelves, folders and "
        "library. A slideshow started here plays on the "
        f"{orientation} screen."
    )

    row = QHBoxLayout(heading)
    row.setContentsMargins(0, 0, 0, 0)  # the stylesheet's padding insets this
    row.setSpacing(6)

    mark = QLabel()
    mark.setObjectName("treeSectionMark")
    mark.setPixmap(icons.orientation_mark(orientation))
    row.addWidget(mark)

    name = QLabel(ORIENTATION_LABELS[orientation])
    name.setObjectName("treeSectionName")
    row.addWidget(name)
    row.addStretch(1)  # the pair reads as a heading, not as a centered caption
    return heading


class SplitFolderTree(QWidget):
    """Two folder trees, one per shape, each labelled and each scrolling alone.

    Presents the surface of the single ``FolderTree`` it replaced — the same
    signals, and the methods the gallery view calls on a tree — so its callers
    need not know which half a row is in.  The one deliberate difference is the
    context menu: a right-click arrives as :attr:`context_menu_requested` with
    the row and a screen position, since the pane's coordinates are no longer
    any one tree's.
    """

    currentItemChanged = pyqtSignal(object, object)
    itemSelectionChanged = pyqtSignal()
    itemDoubleClicked = pyqtSignal(object, int)
    itemChanged = pyqtSignal(object, int)
    star_clicked = pyqtSignal(object)      # folder key
    delete_clicked = pyqtSignal(object)    # folder key
    folders_dropped = pyqtSignal(str, list)  # collecting row's key, dropped tree keys
    context_menu_requested = pyqtSignal(object, object)  # row under the cursor (or None), global pos

    def __init__(self, group_role, parent=None):
        super().__init__(parent)
        self._halves: dict[str, FolderTree] = {}
        # Which half the current row is in. Only one ever holds a selection, so
        # this is what "the tree's selection" means to everything above.
        self._active = ORIENTATIONS[0]

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        for orientation in ORIENTATIONS:
            self._splitter.addWidget(self._build_half(group_role, orientation))
            self._splitter.setStretchFactor(len(self._halves) - 1, 1)
        # Equal halves to start, and equal shares of anything the pane gains or
        # loses. Neither library is the main one, and the sizes are the user's
        # to drag from there.
        self._splitter.setSizes([1] * len(ORIENTATIONS))

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._splitter)

    def _build_half(self, group_role, orientation: str) -> QWidget:
        """One side: its label, then its tree.

        The label is outside the tree rather than a row in it, which is the
        whole point — a row scrolls away, and then nothing on screen says which
        library you are reading.
        """
        half = QWidget()
        box = QVBoxLayout(half)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(_heading(orientation))

        tree = FolderTree(group_role)
        tree.setHeaderHidden(True)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.setMinimumHeight(_MIN_HALF_HEIGHT)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree: self._on_context_menu(t, pos))
        tree.currentItemChanged.connect(
            lambda current, previous, o=orientation: self._on_current(o, current, previous))
        tree.itemSelectionChanged.connect(self.itemSelectionChanged)
        # Re-emitted through lambdas rather than wired signal-to-signal: Qt's own
        # carry a QTreeWidgetItem*, and these carry it as a plain object so a
        # half's rows reach handlers that never learn which half they came from.
        tree.itemDoubleClicked.connect(
            lambda item, column: self.itemDoubleClicked.emit(item, column))
        tree.itemChanged.connect(
            lambda item, column: self.itemChanged.emit(item, column))
        tree.star_clicked.connect(self.star_clicked)
        tree.delete_clicked.connect(self.delete_clicked)
        tree.folders_dropped.connect(self.folders_dropped)
        box.addWidget(tree, 1)

        self._halves[orientation] = tree
        return half

    # --- the halves ---------------------------------------------------------

    def tree_for(self, orientation: str) -> FolderTree:
        """One side's tree widget."""
        return self._halves[orientation]

    def root_for(self, orientation: str):
        """Where one side's rows are hung — what the tree builder fills."""
        return self._halves[orientation].invisibleRootItem()

    def orientation_of_item(self, item) -> str | None:
        """Which side a row is in, by the tree holding it."""
        holder = item.treeWidget() if item is not None else None
        return next((side for side, tree in self._halves.items() if tree is holder), None)

    # --- one selection across the two ---------------------------------------

    def _on_current(self, orientation: str, current, previous) -> None:
        """A row became current: that half is now the selected one, and the
        other lets go — so what is picked is always one folder in one library."""
        if current is not None and orientation != self._active:
            self._active = orientation
            self._release_all_but(orientation)
        self.currentItemChanged.emit(current, previous)

    def _release_all_but(self, orientation: str) -> None:
        for side, tree in self._halves.items():
            if side != orientation:
                self._release(tree)

    def _release(self, tree) -> None:
        """Drop a half's selection without telling anyone: this is the other
        half's pick taking effect, not a selection change of its own."""
        blocked = tree.signalsBlocked()
        tree.blockSignals(True)
        try:
            tree.selectionModel().clearCurrentIndex()
            tree.clearSelection()
        finally:
            tree.blockSignals(blocked)

    def _on_context_menu(self, tree, pos) -> None:
        self.context_menu_requested.emit(tree.itemAt(pos), tree.viewport().mapToGlobal(pos))

    # --- the surface the gallery view calls on a tree ------------------------

    def currentItem(self):
        """The picked row — the active half's, else whichever half has one."""
        current = self._halves[self._active].currentItem()
        if current is not None:
            return current
        return next((tree.currentItem() for tree in self._halves.values()
                     if tree.currentItem() is not None), None)

    def is_current(self, item) -> bool:
        """Whether a row is already the current one of its own half — where
        setting it again fires no signal, so a caller who needs the pane drawn
        from it has to draw it itself.

        Asked of the row's half rather than of the pane: each half keeps its own
        current row, so a row can be its half's current one while the other half
        is the active one, and setting it then moves the selection across without
        the row itself changing.
        """
        orientation = self.orientation_of_item(item)
        return (orientation is not None
                and self._halves[orientation].currentItem() is item)

    def setCurrentItem(self, item, column=0, command=None) -> None:
        """Go to a row, wherever it lives, and let the other half go."""
        orientation = self.orientation_of_item(item)
        if orientation is None:
            return
        self._release_all_but(orientation)
        self._active = orientation
        self._halves[orientation].setCurrentItem(item, column, command)

    def selected_folder_keys(self) -> list[str]:
        """The tree keys of the picked rows. One half holds them all — the other
        was released the moment this one was picked in."""
        return [key for tree in self._halves.values() for key in tree.selected_folder_keys()]

    def selectedItems(self) -> list:
        return [item for tree in self._halves.values() for item in tree.selectedItems()]

    def clearSelection(self) -> None:
        for tree in self._halves.values():
            tree.clearSelection()

    def clear(self) -> None:
        for tree in self._halves.values():
            tree.clear()

    def editItem(self, item, column=0) -> None:
        orientation = self.orientation_of_item(item)
        if orientation is not None:
            self._halves[orientation].editItem(item, column)

    def blockSignals(self, block: bool) -> bool:
        """Silence the halves along with this widget — a rebuild clears and
        refills them, and it is their signals that would fire."""
        for tree in self._halves.values():
            tree.blockSignals(block)
        return super().blockSignals(block)

    def setEditTriggers(self, triggers) -> None:
        for tree in self._halves.values():
            tree.setEditTriggers(triggers)

    def setExpandsOnDoubleClick(self, expands: bool) -> None:
        for tree in self._halves.values():
            tree.setExpandsOnDoubleClick(expands)
