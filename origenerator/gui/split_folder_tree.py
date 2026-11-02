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
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.spacing import (
    BUTTON_FILLING_ICON,
    BUTTON_GAP,
    BUTTON_GROUP_GAP,
    BUTTON_ROW_GAP,
    GAP_MEDIUM,
    GAP_SMALL,
)

from origenerator.gallery.shapes import (
    BOTH,
    SEPARATE,
    SHAPE_LABELS,
    SHAPES_AND_BOTH,
    TOGETHER,
)
from origenerator.gui import icons
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.panes import PaneSplitter
from origenerator.gui.stylesheet import CHOSEN

_MIN_SECTION_HEIGHT = 90
_GAP_UNDER_THE_CHOICES = 2
_UNDER_A_WORDS_INK = 5  # clear rows under a heading's word in Windows' Segoe UI and the offscreen font
_HEADING_FOOT = GAP_MEDIUM - _UNDER_A_WORDS_INK

_SEPARATE_WORD = "Separate"
_TOGETHER_WORD = "Together"
_SEPARATE_TIP = ("A list for each shape — Portrait and Landscape apart, so a "
                 "slideshow started in one plays that shape alone")
_TOGETHER_TIP = ("One list of both shapes, for a slideshow that mixes portrait and "
                 "landscape items")


class _Choice(QFrame):
    def __init__(self, word: str, mark, tip: str):
        super().__init__()
        self.setToolTip(tip)
        self.button = fill_square_with_icon(QPushButton())
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


def _heading(shape: str) -> QFrame:
    heading = QFrame()
    heading.setObjectName("treeSectionLabel")
    heading.setToolTip(f"Everything {shape}-shaped — its own collections, folders and "
                       f"library. A slideshow started here plays {shape} items alone.")

    row = QHBoxLayout(heading)
    row.setContentsMargins(GAP_SMALL, GAP_SMALL, GAP_SMALL, _HEADING_FOOT)
    row.setSpacing(GAP_MEDIUM)

    mark = QLabel()
    mark.setObjectName("treeSectionMark")
    mark.setPixmap(icons.shape_mark(shape))
    row.addWidget(mark)

    name = QLabel(SHAPE_LABELS[shape])
    name.setObjectName("treeSectionName")
    row.addWidget(name)
    row.addStretch(1)
    return heading


def _rule() -> QFrame:
    rule = QFrame()
    rule.setObjectName("treeSectionRule")
    rule.setFixedHeight(1)
    return rule


class SplitFolderTree(QWidget):
    shapes_changed = pyqtSignal()
    currentItemChanged = pyqtSignal(object, object)
    itemSelectionChanged = pyqtSignal()
    favorite_clicked = pyqtSignal(object)
    delete_clicked = pyqtSignal(object)
    dropped = pyqtSignal(str, list, list)
    context_menu_requested = pyqtSignal(object, object, str)

    def __init__(self, group_role, takes_item=lambda _row_key, _prompt_id: False,
                 takes_folder=lambda _row_key, _folder_key: True, parent=None):
        super().__init__(parent)
        self._takes_item = takes_item
        self._takes_folder = takes_folder
        self._trees: dict[str, FolderTree] = {}
        self._sections: dict[str, QWidget] = {}
        self._shapes = SEPARATE
        self._chosen = SEPARATE
        self._offered = True
        self._active = SEPARATE[0]

        self._splitter = PaneSplitter(Qt.Orientation.Vertical, "side_sections")
        for shape in SHAPES_AND_BOTH:
            self._splitter.addWidget(self._build_section(group_role, shape))
            self._splitter.setStretchFactor(len(self._trees) - 1, 1)
        self._splitter.setSizes([1] * len(SHAPES_AND_BOTH))

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(_GAP_UNDER_THE_CHOICES)
        column.addWidget(self._build_radio())
        column.addWidget(self._splitter, 1)
        self._show_sections(SEPARATE)

    def _build_radio(self) -> QWidget:
        separate = _Choice(_SEPARATE_WORD, icons.separate_mark(BUTTON_FILLING_ICON), _SEPARATE_TIP)
        together = _Choice(_TOGETHER_WORD, icons.shape_mark(BOTH, BUTTON_FILLING_ICON), _TOGETHER_TIP)
        self.separate_button = separate.button
        self.together_button = together.button
        radio = QButtonGroup(self)
        radio.setExclusive(True)
        self._choices = QWidget()
        FlowLayout(self._choices, spacing=BUTTON_GROUP_GAP, row_spacing=BUTTON_ROW_GAP)
        for choice, shapes in ((separate, SEPARATE), (together, TOGETHER)):
            choice.button.clicked.connect(lambda _checked, s=shapes: self.choose_shapes(s))
            radio.addButton(choice.button)
            self._choices.layout().addWidget(choice)
        return self._choices

    @property
    def shapes(self) -> tuple[str, ...]:
        return self._shapes

    @property
    def chosen_sides(self) -> tuple[str, ...]:
        return self._chosen

    def choose_shapes(self, shapes) -> None:
        self._chosen = tuple(shapes)
        self._redraw()

    def offer_separate_and_together(self, offered: bool) -> None:
        self._offered = offered
        self._choices.setVisible(offered)
        self._redraw()

    def _redraw(self) -> None:
        shapes = self._chosen if self._offered else SEPARATE
        if shapes == self._shapes:
            return
        self._show_sections(shapes)
        self.shapes_changed.emit()

    def _show_sections(self, shapes) -> None:
        self._shapes = tuple(shapes)
        for shape, section in self._sections.items():
            section.setVisible(shape in self._shapes)
        if self._active not in self._shapes:
            self._active = self._shapes[0]
        self.separate_button.setChecked(self._shapes == SEPARATE)
        self.together_button.setChecked(self._shapes == TOGETHER)

    def _build_section(self, group_role, shape: str) -> QWidget:
        section = QWidget()
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        if shape in SEPARATE:
            column.addWidget(_heading(shape))
        else:
            column.addSpacing(GAP_MEDIUM - _GAP_UNDER_THE_CHOICES)
        column.addWidget(_rule())
        column.addSpacing(GAP_SMALL)

        tree = FolderTree(group_role, takes_item=self._takes_item,
                          takes_folder=self._takes_folder)
        tree.setHeaderHidden(True)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.setMinimumHeight(_MIN_SECTION_HEIGHT)
        tree.customContextMenuRequested.connect(
            lambda pos, t=tree, s=shape: self._on_context_menu(t, pos, s))
        tree.currentItemChanged.connect(
            lambda current, previous, s=shape: self._on_current(s, current, previous))
        tree.itemSelectionChanged.connect(self.itemSelectionChanged)
        tree.favorite_clicked.connect(self.favorite_clicked)
        tree.delete_clicked.connect(self.delete_clicked)
        tree.dropped.connect(self.dropped)
        column.addWidget(tree, 1)

        self._trees[shape] = tree
        self._sections[shape] = section
        return section

    def root_for(self, shape: str):
        return self._trees[shape].invisibleRootItem()

    def shape_of_item(self, item) -> str | None:
        holder = item.treeWidget() if item is not None else None
        return next((shape for shape, tree in self._trees.items() if tree is holder), None)

    def landing_on(self, item, mime, source):
        shape = self.shape_of_item(item)
        return self._trees[shape].landing_on(item, mime, source) if shape is not None else None

    def _on_current(self, shape: str, current, previous) -> None:
        if current is not None and shape != self._active:
            self._active = shape
            self._release_all_but(shape)
        self.currentItemChanged.emit(current, previous)

    def _release_all_but(self, shape: str) -> None:
        for other, tree in self._trees.items():
            if other != shape:
                self._release(tree)

    def _release(self, tree) -> None:
        blocked = tree.signalsBlocked()
        tree.blockSignals(True)
        try:
            tree.selectionModel().clearCurrentIndex()
            tree.clearSelection()
        finally:
            tree.blockSignals(blocked)

    def _on_context_menu(self, tree, pos, shape: str) -> None:
        self.context_menu_requested.emit(tree.itemAt(pos), tree.viewport().mapToGlobal(pos),
                                         shape)

    def currentItem(self):
        current = self._trees[self._active].currentItem()
        if current is not None:
            return current
        return next((tree.currentItem() for tree in self._trees.values()
                     if tree.currentItem() is not None), None)

    def is_current(self, item) -> bool:
        shape = self.shape_of_item(item)
        return shape is not None and self._trees[shape].currentItem() is item

    def setCurrentItem(self, item, column=0, command=None) -> None:
        shape = self.shape_of_item(item)
        if shape is None:
            return
        self._release_all_but(shape)
        self._active = shape
        self._trees[shape].setCurrentItem(item, column, command)

    def selected_folder_keys(self) -> list[str]:
        return [key for tree in self._trees.values() for key in tree.selected_folder_keys()]

    def offer_delete_on_picked_rows(self, offered: bool) -> None:
        for tree in self._trees.values():
            tree.offer_delete_on_picked_rows(offered)

    def selectedItems(self) -> list:
        return [item for tree in self._trees.values() for item in tree.selectedItems()]

    def clearSelection(self) -> None:
        for tree in self._trees.values():
            tree.clearSelection()

    def clear(self) -> None:
        for tree in self._trees.values():
            tree.clear()

    def blockSignals(self, block: bool) -> bool:
        for tree in self._trees.values():
            tree.blockSignals(block)
        return super().blockSignals(block)
