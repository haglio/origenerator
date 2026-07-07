"""Render a generation's read-only metadata as a compact block of sections.

Sits in the info-pane tab's footer, under the editable form, and shows only what
the form can't: the output file, when the run happened, its status and source,
and any parameter the workflow lays out no field for. The section/item model lives
in :mod:`origenerator.generation_metadata`; this does the Qt rendering.

Each section is a titled block of ``label: value`` rows; a row gains a
copy-to-clipboard button when its item declares copyable text (a filename).
"""

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
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


class MetadataBlock(QWidget):
    """A compact, read-only view of one generation's metadata sections.

    ``show_row`` rebuilds the block from the section model. It carries no scroll of
    its own — the pane it lives in scrolls — so it's kept to the few short rows the
    editable form doesn't already cover.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._container: QWidget | None = None

    def show_row(self, row: dict):
        self._render(build_sections(row))

    def _render(self, sections: list[MetaSection]):
        if self._container is not None:
            # setParent(None) drops it from this block's children at once (so a
            # rebuild's findChildren/layout sees only the new rows); deleteLater
            # then frees it on the next loop turn.
            self._container.setParent(None)
            self._container.deleteLater()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for section in sections:
            layout.addWidget(_build_section(section))
        self._container = container
        self._outer.addWidget(container)


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
    """A ``label: value`` row, gaining a copy-to-clipboard button when the item
    declares copyable text. ``label_width`` aligns keys within the section."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
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
    """The value cell — a plain selectable label. A long, space-less value (a
    path, a filename) may wrap rather than force a scrollbar."""
    value = QLabel(_wrappable(item.value))
    value.setTextInteractionFlags(_SELECTABLE)
    value.setWordWrap(True)
    value.setStyleSheet(f"color: {_h(TEXT_SECONDARY)};")
    return value


# Characters after which a long, space-less value (a model path, an output
# filename) may break, so it wraps down the pane instead of forcing the whole
# block to scroll sideways.
_BREAK_AFTER = "\\/_-."


def _wrappable(text: str) -> str:
    """Insert a zero-width space after each path/name separator, giving a
    word-wrapping label a place to break a long unbroken value. The spaces have
    no width so the visible text is unchanged, and copy buttons still carry the
    original value — only on-screen wrapping is affected."""
    return "".join(ch + "​" if ch in _BREAK_AFTER else ch for ch in text)


def _copy_button(text: str) -> QPushButton:
    """A small copy-icon button that puts ``text`` on the clipboard."""
    button = QPushButton()
    button.setObjectName("copyButton")
    button.setIcon(_copy_icon())
    button.setIconSize(QSize(14, 14))
    button.setToolTip("Copy to clipboard")
    button.setStyleSheet("padding: 2px 6px;")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda: QApplication.clipboard().setText(text))
    return button


def _copy_icon() -> QIcon:
    """The familiar two-overlapping-sheets copy glyph."""
    icon = QIcon()
    icon.addPixmap(_draw_copy_sheets(TEXT_SECONDARY), QIcon.Mode.Normal)
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
