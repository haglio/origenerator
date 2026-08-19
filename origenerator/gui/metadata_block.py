"""Render a generation's read-only metadata as a compact block of sections.

Sits in the info-pane tab's footer, under the editable form, and shows only what
the form can't: the output file, when the run happened, its status and source,
and any parameter the workflow lays out no field for. The section/item model lives
in :mod:`origenerator.generation_metadata`; this does the Qt rendering.

Each section is a titled block of ``label: value`` rows; a row gains a
copy-to-clipboard button when its item declares copyable text (a filename).
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics

from origenerator.generation_metadata import MetaItem, MetaSection, build_sections
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.eliding import ElidingButton
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.reveal import show_in_explorer

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

    def show_row(self, row: dict) -> bool:
        """Render this row's sections, reporting whether it had any.

        An image usually has none — every file it holds is a version, listed
        with the enhancement level that made it — and a caller shows this block
        only when there is something in it, rather than leaving a bare gap above
        the form."""
        sections = build_sections(row)
        self._render(sections)
        return bool(sections)

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
    """One titled block, folding like every other section in the pane.

    It sits among the form's own sections, so it folds by the same header rather
    than being the one heading in the column that doesn't.
    """
    box = CollapsibleSection(section.title)
    rows = QWidget()
    layout = QVBoxLayout(rows)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    label_width = label_column_width(section.items)
    for item in section.items:
        layout.addWidget(meta_row(item, label_width))
    box.content_form().addRow(rows)
    return box


def label_column_width(items: list[MetaItem]) -> int:
    """Pixels wide enough for this group's longest key, so a Parameters block
    (``lora_strength_high``) gets the room a short Details block never wastes.
    Applied as a minimum, not a cap, so an under-measured label grows to fit
    rather than clipping."""
    labels = [item.label for item in items if item.label]
    if not labels:
        return 0
    metrics = QFontMetrics(QApplication.font())
    return max(metrics.horizontalAdvance(text) for text in labels) + 12


def meta_cells(item: MetaItem, label_width: int = 0) -> tuple:
    """One item's four cells — ``(label, value, copy, reveal)`` — the last two
    ``None`` unless the item declares copyable text or a path to reveal.

    Public as cells rather than only as a finished row because the version list
    lays these into a grid of its own: a level's File line carries the same
    copy and Show-in-Explorer buttons as one in a metadata block because it is
    built from the same widgets, and a grid puts nothing between them and the
    row, which is one thing to click.
    """
    return (
        _label_widget(item.label, label_width),
        _value_widget(item),
        CopyButton(item.copy) if item.copy is not None else None,
        _reveal_button(item.reveal) if item.reveal is not None else None,
    )


def meta_row(item: MetaItem, label_width: int = 0) -> QWidget:
    """A ``label: value`` row, gaining a copy-to-clipboard button when the item
    declares copyable text. ``label_width`` aligns keys within the section."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    label, value, copy, reveal = meta_cells(item, label_width)
    layout.addWidget(label)
    layout.addWidget(value, 1)
    for button in (copy, reveal):
        if button is not None:
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
    return row


def _reveal_button(target: str) -> QPushButton:
    """A "Show in Explorer" button revealing the output file selected in the OS
    file manager. Greyed out (with a hint) when the file is no longer on disk —
    trashed or moved — so it never opens the wrong place.

    The longest label on any file row, so it is the one that decides how narrow a
    pane holding file rows can be squeezed: it elides rather than hold that width
    (see :mod:`origenerator.gui.eliding`)."""
    btn = ElidingButton("Show in Explorer")
    btn.setObjectName("revealButton")
    btn.setStyleSheet("padding: 2px 6px;")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    exists = Path(target).exists()
    btn.setEnabled(exists)
    btn.setToolTip("Show this file in Explorer" if exists else "File not found on disk")
    btn.clicked.connect(lambda _checked=False: show_in_explorer(Path(target)))
    return btn


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
