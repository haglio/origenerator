"""Render a generation's metadata as formatted sections instead of raw text.

Each section is a titled block; its items are either ``label: value`` rows
(the file, parameters, details) or bare values shown as quoted blocks (the
prompts). The section/item model lives in ``origenerator.generation_metadata``.
"""

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea,
)
from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QFontMetrics

from origenerator.generation_metadata import MetaItem, MetaSection, build_sections
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, BORDER_SUBTLE,
)

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

    label_width = _label_column_width(section)
    for item in section.items:
        layout.addWidget(_build_item(item, label_width))
    return box


def _label_column_width(section: MetaSection) -> int:
    """Pixels wide enough for this section's longest key, so a Parameters block
    (``lora_strength_high``) gets the room a short Details block never wastes.
    Applied as a minimum, not a cap, so an under-measured label grows to fit
    rather than clipping."""
    labels = [item.label for item in section.items if item.label]
    if not labels:
        return 0
    metrics = QFontMetrics(QApplication.font())
    return max(metrics.horizontalAdvance(text) for text in labels) + 12


def _build_item(item: MetaItem, label_width: int) -> QWidget:
    """A row of ``[label?] value [copy?]``.

    A labeled item reads ``label: value``; a bare one (a prompt) shows the value
    alone as a quoted block. Either gains a copy-to-clipboard button when the
    item declares copyable text. ``label_width`` aligns keys within the section.
    """
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    if item.label:
        layout.addWidget(_label_widget(item.label, label_width))
    layout.addWidget(_value_widget(item), 1)
    if item.copy is not None:
        layout.addWidget(_copy_button(item.copy), 0, Qt.AlignmentFlag.AlignTop)
    return row


def _label_widget(text: str, width: int) -> QLabel:
    label = QLabel(text)
    label.setMinimumWidth(width)
    label.setStyleSheet(f"color: {_h(TEXT_MUTED)};")
    label.setAlignment(Qt.AlignmentFlag.AlignTop)
    return label


def _value_widget(item: MetaItem) -> QLabel:
    value = QLabel(_wrappable(item.value))
    value.setWordWrap(True)
    value.setTextInteractionFlags(_SELECTABLE)
    style = f"color: {_h(TEXT_SECONDARY)};"
    if not item.label:  # a bare value reads as a quoted block, set off by a rule
        style += f" border-left: 2px solid {_h(BORDER_SUBTLE)}; padding: 1px 0 1px 8px;"
    value.setStyleSheet(style)
    return value


# Characters after which a long, space-less value (a model path, an output
# filename) may break, so it wraps down the pane instead of forcing the whole
# panel to scroll sideways.
_BREAK_AFTER = "\\/_-."


def _wrappable(text: str) -> str:
    """Insert a zero-width space after each path/name separator, giving a
    word-wrapping label a place to break a long unbroken value. The spaces have
    no width so the visible text is unchanged, and copy buttons still carry the
    original value — only on-screen wrapping is affected."""
    return "".join(ch + "\u200b" if ch in _BREAK_AFTER else ch for ch in text)


def _copy_button(text: str) -> QPushButton:
    """A small copy-icon button. Empty ``text`` (a field that exists but holds
    nothing, e.g. a blank prompt) shows the button disabled rather than absent."""
    button = QPushButton()
    button.setObjectName("copyButton")
    button.setIcon(_copy_icon())
    button.setIconSize(QSize(14, 14))
    button.setToolTip("Copy to clipboard")
    button.setStyleSheet("padding: 2px 6px;")
    if text:
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: QApplication.clipboard().setText(text))
    else:
        button.setEnabled(False)
    return button


def _copy_icon() -> QIcon:
    """The familiar two-overlapping-sheets copy glyph.

    Carries its own disabled rendering — the same glyph in the muted colour —
    rather than leaning on Qt's automatic greying, which barely dimmed a light
    icon on a dark button. Qt swaps to it when the button is disabled.
    """
    icon = QIcon()
    icon.addPixmap(_draw_copy_sheets(TEXT_SECONDARY), QIcon.Mode.Normal)
    icon.addPixmap(_draw_copy_sheets(TEXT_MUTED), QIcon.Mode.Disabled)
    return icon


def _draw_copy_sheets(color) -> QPixmap:
    """Stroke the two sheets in ``color``. Both are outlines; a gap is cleared
    around the front sheet so it reads as sitting in front of the back one where
    they overlap."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    back = QRectF(24, 8, 28, 32)    # peeks out up and to the right
    front = QRectF(12, 24, 28, 32)  # sits in front, down and to the left
    radius = 6

    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(back, radius, radius)

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.black)
    painter.drawRoundedRect(front.adjusted(-4, -4, 4, 4), radius + 3, radius + 3)

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(front, radius, radius)
    painter.end()
    return pixmap
