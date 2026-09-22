"""Render a generation's read-only metadata as one compact titled block.

Sits at the top of the info-pane tab's scroll, above the editable form, and
shows only what the form and the version list can't: a file no version claims,
when the run happened, and which workflow version made it. The model lives in
:mod:`origenerator.generation_metadata`; this does the Qt rendering.

The block is a titled set of ``label: value`` rows, led by the generation's "Go
to folder" — the one act here that is the row's rather than one file's.
"""
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

from origenerator.generation_metadata import (
    BASIC_TITLE,
    MetaItem,
    MetaSection,
    basic_section,
)
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.eliding import ElidingButton, ElidingLabel
from origenerator.reveal import show_in_explorer

_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse


def _h(color) -> str:
    return color.name()


class MetadataBlock(QWidget):
    """A compact, read-only view of one generation's metadata sections.

    ``show_row`` rebuilds the block from the section model. It carries no scroll of
    its own — the pane it lives in scrolls — so it's kept to the few short rows the
    editable form doesn't already cover.
    """

    def __init__(self, parent=None, *, go_to_folder: QAction | None = None):
        super().__init__(parent)
        self._go_to_folder = go_to_folder
        self._section: MetaSection | None = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._container: QWidget | None = None

    def show_row(self, row: dict, upscale=None) -> bool:
        """Render this row's section, reporting whether it has anything in it.

        An image's files are all versions, listed with the level that made each
        — and so are a video's once Evolver has upscaled it — so what is left
        here can be as little as the way to the folder, or nothing at all."""
        self._section = basic_section(row, upscale)
        self._render(self._section)
        return self.has_content()

    def has_content(self) -> bool:
        """Whether there is anything in this block to show — asked again
        whenever the way to the folder comes or goes."""
        return self._section is not None or (
            self._go_to_folder is not None and self._go_to_folder.isVisible())

    def _render(self, section: MetaSection | None):
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
        if section is not None or self._go_to_folder is not None:
            layout.addWidget(_build_section(section, self._go_to_folder))
        self._container = container
        self._outer.addWidget(container)


def _build_section(section: MetaSection | None,
                   go_to_folder: QAction | None = None) -> QWidget:
    """One titled block, folding like every other section in the pane.

    It sits among the form's own sections, so it folds by the same header rather
    than being the one heading in the column that doesn't.
    """
    items = section.items if section is not None else []
    block = CollapsibleSection(section.title if section is not None else BASIC_TITLE)
    rows = QWidget()
    layout = QVBoxLayout(rows)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    if go_to_folder is not None:
        layout.addWidget(_folder_button(go_to_folder), 0, Qt.AlignmentFlag.AlignLeft)
    label_width = label_column_width(items)
    for item in items:
        layout.addWidget(meta_row(item, label_width))
    block.content_form().addRow(rows)
    return block


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
    label, value, *buttons = meta_cells(item, label_width)
    layout.addWidget(label)
    layout.addWidget(value, 1)
    for button in buttons:
        if button is not None:
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
    return row


def _dressed(btn: QPushButton, name: str) -> QPushButton:
    btn.setObjectName(name)
    btn.setStyleSheet("padding: 2px 6px;")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _reveal_button(target: str) -> QPushButton:
    """A "Show in Explorer" button revealing the output file selected in the OS
    file manager. Grayed out (with a hint) when the file is no longer on disk —
    trashed or moved — so it never opens the wrong place.

    The longest label on any file row, so it is the one that decides how narrow a
    pane holding file rows can be squeezed: it elides rather than hold that width
    (see :mod:`origenerator.gui.eliding`)."""
    btn = _dressed(ElidingButton("Show in Explorer"), "revealButton")
    exists = Path(target).exists()
    btn.setEnabled(exists)
    btn.setToolTip("Show this file in Explorer" if exists else "File not found on disk")
    btn.clicked.connect(lambda _checked=False: show_in_explorer(Path(target)))
    return btn


class _ActionButton(ElidingButton):
    """A button standing for ``action``: it is there, live and worded as the
    action says, and pressing it triggers the action."""

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
    # ``width`` lines this key up with the others in its group by asking for that
    # much, not by demanding it: squeezed, the key gives way and elides, so a file
    # row can be read in a narrow pane instead of setting its floor. See
    # :class:`~origenerator.gui.eliding.ElidingLabel`.
    label = ElidingLabel(text, preferred_width=width)
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
    return "".join(ch + "\u200b" if ch in _BREAK_AFTER else ch for ch in text)
