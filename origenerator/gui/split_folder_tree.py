"""The folder list's sections: one tree per side, each under a standing label.

The marks over them are the radio: Portrait and Landscape apart, or one list of
both shapes (:mod:`origenerator.orientation` says what a side is). Sections
rather than rows in one tree, so each scrolls alone and its label never scrolls
away; one selection across them all, so the folder on screen is one folder.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.mark_button import fill_square_with_mark
from shared_ui.spacing import (
    BUTTON_GAP,
    BUTTON_GROUP_GAP,
    BUTTON_MARK,
    BUTTON_ROW_GAP,
)

from origenerator.gallery.sides import BOTH, ORIENTATIONS, SIDE_LABELS, SIDES
from origenerator.gui import icons
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.panes import PaneSplitter
from origenerator.gui.stylesheet import CHOSEN

_MIN_SECTION_HEIGHT = 90

_TIPS = {
    side: (f"Everything {side}-shaped — its own shelves, folders and library. "
           f"A slideshow started here plays {side} pictures alone.")
    for side in ORIENTATIONS
} | {
    BOTH: ("Everything, both shapes together — its own shelves, folders and "
           "library. A slideshow started here mixes portrait and landscape "
           "pictures in the one show."),
}
_SEPARATE = "Separate"
_TOGETHER = "Together"
_EACH_SHAPE_TIP = ("A list for each shape — Portrait and Landscape apart, so a "
                   "slideshow started in one plays that shape alone")
_BOTH_TIP = ("One list of both shapes, for a slideshow that mixes portrait and "
             "landscape pictures")


class _Choice(QFrame):
    """One of the radio's two choices: a square mark, then the word for it."""

    def __init__(self, word: str, mark, tip: str):
        super().__init__()
        self.setToolTip(tip)
        self.button = fill_square_with_mark(QPushButton())
        self.button.setObjectName("sidesChoice")
        self.button.setProperty(CHOSEN, True)
        self.button.setIcon(QIcon(mark))
        self.button.setCheckable(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(BUTTON_GAP)
        row.addWidget(self.button)
        row.addWidget(QLabel(word))

    def mousePressEvent(self, _event) -> None:
        self.button.click()


def _heading(side: str) -> QFrame:
    """One section's standing label: its shape's mark, then its name."""
    heading = QFrame()
    heading.setObjectName("treeSectionLabel")
    heading.setToolTip(_TIPS[side])

    row = QHBoxLayout(heading)
    row.setContentsMargins(0, 0, 0, 0)  # the stylesheet's padding insets this
    row.setSpacing(6)

    mark = QLabel()
    mark.setObjectName("treeSectionMark")
    mark.setPixmap(icons.side_mark(side))
    row.addWidget(mark)

    name = QLabel(SIDE_LABELS[side])
    name.setObjectName("treeSectionName")
    row.addWidget(name)
    row.addStretch(1)
    return heading


class SplitFolderTree(QWidget):
    """A folder tree per side, under the radio that says which sides there are.

    Presents the surface of the single ``FolderTree`` it replaced — the same
    signals, and the methods the gallery view calls on a tree — so its callers
    need not know which section a row is in.  The one deliberate difference is
    the context menu: a right-click arrives as :attr:`context_menu_requested`
    with the row, a screen position and the section it landed in, since the
    pane's coordinates are no longer any one tree's and empty space has no row
    to ask.
    """

    sides_changed = pyqtSignal()
    currentItemChanged = pyqtSignal(object, object)
    itemSelectionChanged = pyqtSignal()
    favorite_clicked = pyqtSignal(object)      # folder key
    delete_clicked = pyqtSignal(object)    # folder key
    folders_dropped = pyqtSignal(str, list)  # collecting row's key, dropped tree keys
    context_menu_requested = pyqtSignal(object, object, str)

    def __init__(self, group_role, parent=None):
        super().__init__(parent)
        self._trees: dict[str, FolderTree] = {}
        self._sections: dict[str, QWidget] = {}   # each tree under its heading
        self._sides = ORIENTATIONS
        self._active = ORIENTATIONS[0]

        self._splitter = PaneSplitter(Qt.Orientation.Vertical)
        for side in SIDES:
            self._splitter.addWidget(self._build_section(group_role, side))
            self._splitter.setStretchFactor(len(self._trees) - 1, 1)
        # Equal sections, and equal shares of anything the pane gains or loses:
        # no side is the main one, and the sizes are the user's to drag.
        self._splitter.setSizes([1] * len(SIDES))

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(self._build_radio())
        column.addWidget(self._splitter, 1)
        self.set_sides(ORIENTATIONS)

    def _build_radio(self) -> QWidget:
        """The two choices over the sections: a list per shape, or one of both."""
        each_shape = _Choice(_SEPARATE, icons.each_shape_mark(BUTTON_MARK),
                             _EACH_SHAPE_TIP)
        self._both_choice = _Choice(_TOGETHER, icons.side_mark(BOTH, BUTTON_MARK),
                                    _BOTH_TIP)
        self.each_shape_button = each_shape.button
        self.both_button = self._both_choice.button
        self._radio = QButtonGroup(self)
        self._radio.setExclusive(True)
        choices = QWidget()
        FlowLayout(choices, spacing=BUTTON_GROUP_GAP, row_spacing=BUTTON_ROW_GAP)
        for choice, sides in ((each_shape, ORIENTATIONS),
                              (self._both_choice, (BOTH,))):
            choice.button.clicked.connect(lambda _checked, s=sides: self._pick_sides(s))
            self._radio.addButton(choice.button)
            choices.layout().addWidget(choice)
        self.each_shape_button.setChecked(True)
        return choices

    # --- which sides the pane draws -----------------------------------------

    @property
    def sides(self) -> tuple[str, ...]:
        return self._sides

    def set_sides(self, sides) -> None:
        """Draw a section for each of *sides* and hide the rest."""
        self._sides = tuple(sides)
        for side, section in self._sections.items():
            section.setVisible(side in self._sides)
        if self._active not in self._sides:
            self._active = self._sides[0]
        self.each_shape_button.setChecked(self._sides != (BOTH,))
        self.both_button.setChecked(self._sides == (BOTH,))

    def offer_both(self, offered: bool) -> None:
        """Whether one list of both shapes is on offer at all.

        Hosted by a Fun Time session it is not: the room plays a shape on each
        of its two screens, so a mixed show would have nowhere to land.
        """
        self._both_choice.setVisible(offered)
        if not offered:
            self._pick_sides(ORIENTATIONS)

    def _pick_sides(self, sides) -> None:
        if tuple(sides) == self._sides:
            return
        self.set_sides(sides)
        self.sides_changed.emit()

    def _build_section(self, group_role, side: str) -> QWidget:
        section = QWidget()
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(_heading(side))

        tree = FolderTree(group_role)
        tree.setHeaderHidden(True)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.setMinimumHeight(_MIN_SECTION_HEIGHT)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree, s=side: self._on_context_menu(t, pos, s))
        tree.currentItemChanged.connect(
            lambda current, previous, s=side: self._on_current(s, current, previous))
        tree.itemSelectionChanged.connect(self.itemSelectionChanged)
        tree.favorite_clicked.connect(self.favorite_clicked)
        tree.delete_clicked.connect(self.delete_clicked)
        tree.folders_dropped.connect(self.folders_dropped)
        column.addWidget(tree, 1)

        self._trees[side] = tree
        self._sections[side] = section
        return section

    # --- the sections -------------------------------------------------------

    def root_for(self, side: str):
        """Where one side's rows attach — what the tree builder fills."""
        return self._trees[side].invisibleRootItem()

    def side_of_item(self, item) -> str | None:
        holder = item.treeWidget() if item is not None else None
        return next((side for side, tree in self._trees.items() if tree is holder), None)

    # --- one selection across them all --------------------------------------

    def _on_current(self, side: str, current, previous) -> None:
        if current is not None and side != self._active:
            self._active = side
            self._release_all_but(side)
        self.currentItemChanged.emit(current, previous)

    def _release_all_but(self, side: str) -> None:
        for other, tree in self._trees.items():
            if other != side:
                self._release(tree)

    def _release(self, tree) -> None:
        """Drop a section's selection without telling anyone: this is another
        section's pick taking effect, not a selection change of its own."""
        blocked = tree.signalsBlocked()
        tree.blockSignals(True)
        try:
            tree.selectionModel().clearCurrentIndex()
            tree.clearSelection()
        finally:
            tree.blockSignals(blocked)

    def _on_context_menu(self, tree, pos, side: str) -> None:
        self.context_menu_requested.emit(tree.itemAt(pos), tree.viewport().mapToGlobal(pos),
                                         side)

    # --- the surface the gallery view calls on a tree ------------------------

    def currentItem(self):
        """The picked row — the active section's, else whichever has one."""
        current = self._trees[self._active].currentItem()
        if current is not None:
            return current
        return next((tree.currentItem() for tree in self._trees.values()
                     if tree.currentItem() is not None), None)

    def is_current(self, item) -> bool:
        """Whether a row is already the current one of its own section — where
        setting it again fires no signal, so a caller who needs the pane drawn
        from it has to draw it itself."""
        side = self.side_of_item(item)
        return side is not None and self._trees[side].currentItem() is item

    def setCurrentItem(self, item, column=0, command=None) -> None:
        side = self.side_of_item(item)
        if side is None:
            return
        self._release_all_but(side)
        self._active = side
        self._trees[side].setCurrentItem(item, column, command)

    def selected_folder_keys(self) -> list[str]:
        return [key for tree in self._trees.values() for key in tree.selected_folder_keys()]

    def selectedItems(self) -> list:
        return [item for tree in self._trees.values() for item in tree.selectedItems()]

    def clearSelection(self) -> None:
        for tree in self._trees.values():
            tree.clearSelection()

    def clear(self) -> None:
        for tree in self._trees.values():
            tree.clear()

    def blockSignals(self, block: bool) -> bool:
        """Silence the sections along with this widget — a rebuild clears and
        refills them, and it is their signals that would fire."""
        for tree in self._trees.values():
            tree.blockSignals(block)
        return super().blockSignals(block)
