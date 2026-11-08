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
from shared_ui.colors import TEXT_MUTED
from shared_ui.spacing import BUTTON_PAD_H_TIGHT, BUTTON_PAD_V, GAP_MEDIUM

from origenerator.generation_metadata import (
    METADATA_TITLE,
    MetadataFacts,
    MetadataItem,
    metadata_facts,
)
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.eliding import ElidingButton, ElidingLabel
from origenerator.gui.label_cells import LabelCell, LabelForm
from origenerator.gui.warning_mark import WarningMark
from origenerator.reveal import show_in_explorer

_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse


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
        self._fact_rows = 0

    def form(self) -> LabelForm:
        return self._block.content_form()

    def add_line(self, label: str, field: QWidget) -> None:
        form = self.form()
        form.addRow(LabelCell(WarningMark(), ElidingLabel(label), form.label_column), field)
        form.setRowVisible(field, False)

    def add_note(self, note: QWidget) -> None:
        self.form().addRow(note)
        self.form().setRowVisible(note, False)

    def show_line(self, field: QWidget, shown: bool) -> None:
        self.form().setRowVisible(field, shown)

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

    def clear_facts(self) -> None:
        self._shown = None
        self._section = None
        self._show_facts([])

    def has_content(self) -> bool:
        form = self.form()
        return any(form.isRowVisible(row) for row in range(form.rowCount()))

    def _show_facts(self, items: list[MetadataItem]) -> None:
        form = self.form()
        for _ in range(self._fact_rows):
            form.removeRow(0)
        for line, item in enumerate(items):
            _label, value, *buttons = metadata_cells(item)
            form.insertRow(line, LabelCell(WarningMark(), ElidingLabel(item.label),
                                           form.label_column),
                           _value_with(value, buttons))
        self._fact_rows = len(items)

    def is_folded(self) -> bool:
        return self._block.is_collapsed()

    def set_folded(self, folded: bool) -> None:
        self._block.set_collapsed(folded)


def _value_with(value: QWidget, buttons: list) -> QWidget:
    cell = QWidget()
    row = QHBoxLayout(cell)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(GAP_MEDIUM)
    row.addWidget(value, 1)
    for button in buttons:
        if button is not None:
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
    return cell


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
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    return label


def _value_widget(item: MetadataItem) -> QLabel:
    value = QLabel(wrappable(item.value))
    value.setTextInteractionFlags(_SELECTABLE)
    value.setWordWrap(True)
    value.setStyleSheet(f"QLabel {{ color: {_h(TEXT_MUTED)}; }}")
    return value


_BREAK_AFTER = "\\/_-."


def wrappable(text: str) -> str:
    return "".join(ch + "\u200b" if ch in _BREAK_AFTER else ch for ch in text)
