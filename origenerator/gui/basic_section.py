from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import TEXT_MUTED, TEXT_SECONDARY
from shared_ui.spacing import BUTTON_PAD_H_TIGHT, BUTTON_PAD_V, GAP_MEDIUM, GAP_SMALL

from origenerator.generation_metadata import (
    BASIC_TITLE,
    BasicFacts,
    BasicItem,
    basic_facts,
)
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.eliding import ElidingButton, ElidingLabel
from origenerator.reveal import show_in_explorer

_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse


def _h(color) -> str:
    return color.name()


class BasicSection(QWidget):
    def __init__(self, parent=None, *, go_to_folder: QAction | None = None):
        super().__init__(parent)
        self._go_to_folder = go_to_folder
        self._shown: tuple[dict, Path | None, str] | None = None
        self._section: BasicFacts | None = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._block: CollapsibleSection | None = None
        self._folded = False

    def show_row(self, row: dict, upscale=None, name: str = "") -> bool:
        self._shown = (row, upscale, name)
        self._section = basic_facts(row, upscale, name=name)
        self._render(self._section)
        return self.has_content()

    def show_name(self, name: str) -> bool:
        if self._shown is not None and self._shown[2] != name:
            row, upscale, _old = self._shown
            self.show_row(row, upscale, name)
        return self.has_content()

    def has_content(self) -> bool:
        return self._section is not None or (
            self._go_to_folder is not None and self._go_to_folder.isVisible())

    def _render(self, section: BasicFacts | None):
        if self._block is not None:
            # Qt: deleteLater alone leaves it among the children until the next loop turn.
            self._block.setParent(None)
            self._block.deleteLater()
            self._block = None
        if section is not None or self._go_to_folder is not None:
            self._block = _build_section(section, self._go_to_folder, collapsed=self._folded)
            self._block.toggled.connect(self._keep_the_fold)
            self._outer.addWidget(self._block)

    def _keep_the_fold(self) -> None:
        self._folded = self._block.is_collapsed()

    def is_folded(self) -> bool:
        return self._folded

    def set_folded(self, folded: bool) -> None:
        self._folded = folded
        if self._block is not None:
            self._block.set_collapsed(folded)


def _build_section(section: BasicFacts | None, go_to_folder: QAction | None = None,
                   *, collapsed: bool = False) -> CollapsibleSection:
    items = section.items if section is not None else []
    block = CollapsibleSection(section.title if section is not None else BASIC_TITLE,
                               collapsed=collapsed)
    rows = QWidget()
    layout = QVBoxLayout(rows)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(GAP_SMALL)
    if go_to_folder is not None:
        layout.addWidget(_folder_button(go_to_folder), 0, Qt.AlignmentFlag.AlignLeft)
    label_width = label_column_width(items)
    for item in items:
        layout.addWidget(basic_row(item, label_width))
    block.content_form().addRow(rows)
    return block


def label_column_width(items: list[BasicItem]) -> int:
    metrics = QFontMetrics(QApplication.font())
    return max((metrics.horizontalAdvance(item.label) for item in items if item.label), default=0)


def basic_cells(item: BasicItem, label_width: int = 0) -> tuple:
    return (
        _label_widget(item.label, label_width),
        _value_widget(item),
        CopyButton(item.copy) if item.copy is not None else None,
        _reveal_button(item.reveal) if item.reveal is not None else None,
    )


def basic_row(item: BasicItem, label_width: int = 0) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(GAP_MEDIUM)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    label, value, *buttons = basic_cells(item, label_width)
    layout.addWidget(label)
    layout.addWidget(value, 1)
    for button in buttons:
        if button is not None:
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
    return row


def _dressed(btn: QPushButton, name: str) -> QPushButton:
    btn.setObjectName(name)
    btn.setStyleSheet(f"padding: {BUTTON_PAD_V}px {BUTTON_PAD_H_TIGHT}px;")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def reveal_button() -> QPushButton:
    return _dressed(ElidingButton("Show in Explorer"), "revealButton")


def _reveal_button(target: str) -> QPushButton:
    btn = reveal_button()
    exists = Path(target).exists()
    btn.setEnabled(exists)
    btn.setToolTip("Show this file in Explorer" if exists else "File not found on disk")
    btn.clicked.connect(lambda _checked=False: show_in_explorer(Path(target)))
    return btn


class _ActionButton(ElidingButton):
    def __init__(self, action: QAction):
        super().__init__(action.text())
        self._action = action
        self.clicked.connect(lambda _checked=False: action.trigger())
        action.changed.connect(self._follow)
        self._follow()

    def _follow(self) -> None:
        self.setVisible(self._action.isVisible())
        self.setEnabled(self._action.isEnabled())
        self.setToolTip(self._action.toolTip())


def _folder_button(action: QAction) -> QPushButton:
    return _dressed(_ActionButton(action), "goToFolderButton")


def _label_widget(text: str, width: int) -> QLabel:
    label = ElidingLabel(text, preferred_width=width)
    label.setStyleSheet(f"color: {_h(TEXT_MUTED)};")
    label.setAlignment(Qt.AlignmentFlag.AlignTop)
    return label


def _value_widget(item: BasicItem) -> QLabel:
    value = QLabel(wrappable(item.value))
    value.setTextInteractionFlags(_SELECTABLE)
    value.setWordWrap(True)
    value.setStyleSheet(f"color: {_h(TEXT_SECONDARY)};")
    return value


_BREAK_AFTER = "\\/_-."


def wrappable(text: str) -> str:
    return "".join(ch + "\u200b" if ch in _BREAK_AFTER else ch for ch in text)
