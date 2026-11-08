from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
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
    METADATA_TITLE,
    MetadataFacts,
    MetadataItem,
    metadata_facts,
)
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.eliding import ElidingButton, ElidingLabel
from origenerator.gui.label_cells import LabelForm
from origenerator.reveal import show_in_explorer

_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse
_DIRECT = Qt.FindChildOption.FindDirectChildrenOnly


def _h(color) -> str:
    return color.name()


class MetadataSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._shown: tuple[dict, Path | None, str] | None = None
        self._section: MetadataFacts | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._block = CollapsibleSection(METADATA_TITLE)
        outer.addWidget(self._block)
        self._facts = QWidget()
        self._facts_column = QVBoxLayout(self._facts)
        self._facts_column.setContentsMargins(0, 0, 0, 0)
        self._facts_column.setSpacing(GAP_SMALL)
        self.form().addRow(self._facts)

    def form(self) -> LabelForm:
        return self._block.content_form()

    def show_row(self, row: dict, upscale=None, name: str = "") -> bool:
        self._shown = (row, upscale, name)
        self._section = metadata_facts(row, upscale, name=name)
        self._show_facts(self._section.items if self._section is not None else [])
        return self.has_content()

    def show_name(self, name: str) -> bool:
        if self._shown is not None and self._shown[2] != name:
            row, upscale, _old = self._shown
            self.show_row(row, upscale, name)
        return self.has_content()

    def has_content(self) -> bool:
        form = self.form()
        return any(form.isRowVisible(row) for row in range(form.rowCount()))

    def _show_facts(self, items: list[MetadataItem]) -> None:
        for old in self._facts.findChildren(QWidget, options=_DIRECT):
            # Qt: deleteLater alone leaves it among the children until the next loop turn.
            old.setParent(None)
            old.deleteLater()
        label_width = label_column_width(items)
        for item in items:
            self._facts_column.addWidget(metadata_row(item, label_width))
        self.form().setRowVisible(self._facts, bool(items))

    def is_folded(self) -> bool:
        return self._block.is_collapsed()

    def set_folded(self, folded: bool) -> None:
        self._block.set_collapsed(folded)


def label_column_width(items: list[MetadataItem]) -> int:
    metrics = QFontMetrics(QApplication.font())
    return max((metrics.horizontalAdvance(item.label) for item in items if item.label), default=0)


def metadata_cells(item: MetadataItem, label_width: int = 0) -> tuple:
    return (
        _label_widget(item.label, label_width),
        _value_widget(item),
        CopyButton(item.copy) if item.copy is not None else None,
        _reveal_button(item.reveal) if item.reveal is not None else None,
    )


def metadata_row(item: MetadataItem, label_width: int = 0) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(GAP_MEDIUM)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    label, value, *buttons = metadata_cells(item, label_width)
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


def _label_widget(text: str, width: int) -> QLabel:
    label = ElidingLabel(text, preferred_width=width)
    label.setStyleSheet(f"color: {_h(TEXT_MUTED)};")
    label.setAlignment(Qt.AlignmentFlag.AlignTop)
    return label


def _value_widget(item: MetadataItem) -> QLabel:
    value = QLabel(wrappable(item.value))
    value.setTextInteractionFlags(_SELECTABLE)
    value.setWordWrap(True)
    value.setStyleSheet(f"QLabel {{ color: {_h(TEXT_SECONDARY)}; }}")
    return value


_BREAK_AFTER = "\\/_-."


def wrappable(text: str) -> str:
    return "".join(ch + "\u200b" if ch in _BREAK_AFTER else ch for ch in text)
