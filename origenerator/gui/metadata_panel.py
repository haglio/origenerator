"""Render a generation's metadata as formatted sections instead of raw text.

Each section is a titled block; its items are either ``label: value`` rows
(details, parameters) or bare values shown as quoted blocks (prompts, files).
The section/item model lives in ``origenerator.generation_metadata``.
"""

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea,
)
from PyQt6.QtCore import Qt

from origenerator.generation_metadata import MetaItem, MetaSection, build_sections
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BORDER_SUBTLE,
)

_LABEL_WIDTH = 84
_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse


def _h(color) -> str:
    return color.name()


class MetadataPanel(QScrollArea):
    """Scrollable, formatted view of one generation's metadata.

    ``show_row`` rebuilds the panel from the section model; ``clear`` empties it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.clear()

    def show_row(self, row: dict):
        self._render(build_sections(row))

    def clear(self):
        self._render([])

    def _render(self, sections: list[MetaSection]):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for section in sections:
            layout.addWidget(_build_section(section))
        self.setWidget(container)  # replaces & deletes the previous container


def _build_section(section: MetaSection) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    title = QLabel(section.title)
    title.setStyleSheet(
        f"color: {_h(TEXT_PRIMARY)}; font-weight: 600;"
        f" border-bottom: 1px solid {_h(BORDER_SUBTLE)}; padding-bottom: 3px;"
    )
    layout.addWidget(title)

    for item in section.items:
        layout.addWidget(_build_item(item))
    return box


def _build_item(item: MetaItem) -> QWidget:
    """A row of ``[label?] value [copy?]``.

    A labeled item reads ``label: value``; a bare one (prompt, filename) shows
    the value alone as a quoted block. Either gains a copy-to-clipboard button
    when the item declares copyable text.
    """
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    if item.label:
        layout.addWidget(_label_widget(item.label))
    layout.addWidget(_value_widget(item), 1)
    if item.copy is not None:
        layout.addWidget(_copy_button(item.copy), 0, Qt.AlignmentFlag.AlignTop)
    return row


def _label_widget(text: str) -> QLabel:
    label = QLabel(text)
    label.setFixedWidth(_LABEL_WIDTH)
    label.setStyleSheet(f"color: {_h(TEXT_MUTED)};")
    label.setAlignment(Qt.AlignmentFlag.AlignTop)
    return label


def _value_widget(item: MetaItem) -> QLabel:
    value = QLabel(item.value)
    value.setWordWrap(True)
    value.setTextInteractionFlags(_SELECTABLE)
    style = f"color: {_h(TEXT_SECONDARY)};"
    if not item.label:  # a bare value reads as a quoted block, set off by a rule
        style += f" border-left: 2px solid {_h(BORDER_SUBTLE)}; padding: 1px 0 1px 8px;"
    value.setStyleSheet(style)
    return value


def _copy_button(text: str) -> QPushButton:
    button = QPushButton("Copy")
    button.setObjectName("copyButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip("Copy to clipboard")
    button.setStyleSheet("padding: 1px 8px;")
    button.clicked.connect(lambda: QApplication.clipboard().setText(text))
    return button
