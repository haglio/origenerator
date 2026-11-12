from __future__ import annotations

import json
from typing import NamedTuple

from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import BG_PRIMARY, TEXT_PRIMARY, YELLOW
from shared_ui.icons import icon_pixmap
from shared_ui.spacing import BUTTON_RADIUS, GAP_MEDIUM, GAP_SMALL

from origenerator.generation_metadata import UNDATED, Dating, MetadataItem, created_item, file_item
from origenerator.gui import icons, palette
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import IconButton
from origenerator.gui.drag_thumbnail import DragOut, fit_thumbnail
from origenerator.gui.generation_job import JobState
from origenerator.gui.metadata_section import label_column_width, metadata_cells
from origenerator.gui.param_fields import NOT_KNOWN
from origenerator.gui.picking import Picking
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box

ENHANCE_VERSION_MIME = "application/x-origenerator-enhance-version"

_PLUS = THUMBNAIL_BOX.width() * 2 // 3
_PENDING_BORDER = f"2px solid {palette.IN_FLIGHT_BORDER}"
_MATCH_BORDER = f"2px solid {palette.MATCH_BORDER}"
_VALUE_COLUMN = 1
_FACT_KEYS = ("Enhancement", "File", "Created")
# The app's global QWidget background paints every label opaque over the row's fill.
_ROW_CSS = "#versionRow QLabel { background-color: transparent; }"
_SELECTED_ROW_CSS = (
    f"#versionRow {{ background-color: {palette.SELECTED_FILL}; border-radius: {BUTTON_RADIUS}px; }}"
    + _ROW_CSS
)
_PICKED_FACT_CSS = f"color: {TEXT_PRIMARY.name()};"
_ADD_TILE_CSS = f"background-color: {YELLOW.name()}; border-radius: {BUTTON_RADIUS}px;"
_ARROW_STEPS = {Qt.Key.Key_Up: -1, Qt.Key.Key_Left: -1,
                Qt.Key.Key_Down: 1, Qt.Key.Key_Right: 1}
_ENHANCE_ROW = -1


def enhance_version_mime(params: dict) -> QMimeData:
    mime = QMimeData()
    mime.setData(ENHANCE_VERSION_MIME,
                 QByteArray(json.dumps(params).encode("utf-8")))
    return mime


def params_from_mime(mime) -> dict | None:
    if not mime.hasFormat(ENHANCE_VERSION_MIME):
        return None
    try:
        params = json.loads(bytes(mime.data(ENHANCE_VERSION_MIME)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return params if isinstance(params, dict) else None


def _pass_mouse_through(widget) -> None:
    # Qt gives selectable text its own Copy / Select All menu, which would sit over the row's Delete.
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)


class RunningEnhancement(NamedTuple):
    status: str
    frame: bytes | None
    settings: str = ""


class EnhanceOffer(NamedTuple):
    settings: str
    duplicate_of: object = None


class _Row(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("versionRow")
        # A stylesheet background on a plain QWidget paints nothing without this.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_ROW_CSS)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(GAP_SMALL, GAP_SMALL, GAP_SMALL, GAP_SMALL)
        self._column.setSpacing(GAP_MEDIUM)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_MEDIUM)
        self._column.addLayout(row)
        self._beside = row
        self._wrapped = False
        self._thumbnail = QLabel()
        self._thumbnail.setFixedSize(THUMBNAIL_BOX)
        self._thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumbnail.setWordWrap(True)
        _pass_mouse_through(self._thumbnail)
        row.addWidget(self._thumbnail, 0, Qt.AlignmentFlag.AlignTop)
        # Straight into the grid: Qt's hit test skips a transparent container along with the buttons inside it.
        facts = QGridLayout()
        facts.setContentsMargins(0, 0, 0, 0)
        facts.setHorizontalSpacing(GAP_MEDIUM)
        facts.setVerticalSpacing(GAP_SMALL)
        facts.setColumnStretch(_VALUE_COLUMN, 1)
        self._title = QLabel(title)
        self._title.setStyleSheet("font-weight: bold; background: transparent;")
        _pass_mouse_through(self._title)
        facts.addWidget(self._title, 0, 0, 1, -1)
        self._facts = facts
        self._fact_cells: list[QWidget] = []
        self._resting_ink: dict[QLabel, str] = {}
        self._selected = False
        row.addLayout(facts, 1)

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.setStyleSheet(_SELECTED_ROW_CSS if selected else _ROW_CSS)
        for label, resting in self._resting_ink.items():
            label.setStyleSheet(_PICKED_FACT_CSS if selected else resting)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        margins = self._column.contentsMargins()
        widest = max(self._thumbnail.minimumSizeHint().width(),
                     self._facts.minimumSize().width())
        hint.setWidth(widest + margins.left() + margins.right())
        return hint

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def _reflow(self, width: int) -> None:
        margins = self._column.contentsMargins()
        beside = (self._thumbnail.sizeHint().width() + self._beside.spacing()
                  + self._facts.minimumSize().width()
                  + margins.left() + margins.right())
        wrapped = width < beside
        if wrapped == self._wrapped:
            return
        if wrapped:
            self._beside.removeItem(self._facts)
            self._column.addItem(self._facts)
        else:
            self._column.removeItem(self._facts)
            self._beside.addLayout(self._facts, 1)
        self._wrapped = wrapped
        self.updateGeometry()

    def _show_facts(self, items: list[MetadataItem],
                    beside_copy: QWidget | None = None) -> None:
        for widget in self._fact_cells:
            self._facts.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._fact_cells = []
        self._resting_ink = {}
        key_width = label_column_width([MetadataItem(key, "") for key in _FACT_KEYS])
        for line, item in enumerate(items, start=1):
            label, value, copy, reveal = metadata_cells(item, key_width)
            beside = (beside_copy,) if beside_copy is not None and copy is not None else ()
            for column, widget in enumerate((label, value, copy, *beside, reveal)):
                if widget is None:
                    continue
                if isinstance(widget, QLabel):
                    _pass_mouse_through(widget)
                if column == _VALUE_COLUMN:
                    self._facts.addWidget(widget, line, column)
                else:
                    self._facts.addWidget(widget, line, column,
                                          Qt.AlignmentFlag.AlignTop)
                self._fact_cells.append(widget)
                if isinstance(widget, QLabel):
                    self._resting_ink[widget] = widget.styleSheet()

    def _show_thumbnail(self, pixmap: QPixmap) -> None:
        self._thumbnail.setPixmap(fitted_in_the_box(pixmap))


class _VersionRow(_Row):
    clicked = Signal(int, Qt.KeyboardModifier)
    context_requested = Signal(int, QPoint)
    delete_pressed = Signal(int)

    def __init__(self, version, position: int, image_path, dating: Dating = UNDATED,
                 deletable: bool = False):
        super().__init__(version.label)
        self._position = position
        self._params = dict(version.params)
        self.drag_out = DragOut()
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        self._drag_thumbnail = fit_thumbnail(pixmap)
        if not pixmap.isNull():
            self._show_thumbnail(pixmap)
        else:
            self._thumbnail.setText(NOT_KNOWN)
            self._thumbnail.setToolTip("This version's file is no longer on disk")
        items = []
        if version.settings:
            items.append(MetadataItem("Enhancement", version.settings))
        items.append(file_item(version.file, held_days=dating.held_days))
        items.append(created_item(version.file, dating.created_fallback))
        trash = None
        if deletable:
            trash = IconButton(icons.delete_icon(), "Delete this version", "deleteButton")
            trash.clicked.connect(
                lambda _checked=False: self.delete_pressed.emit(self._position))
        self._show_facts(items, beside_copy=trash)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(
                self._position, self.mapToGlobal(pos))
        )
        self.setToolTip(
            f"{version.settings}\nDrag onto Enhance to reuse these settings"
            if version.params else version.label
        )

    def position(self) -> int:
        return self._position

    def set_highlighted(self, on: bool) -> None:
        self._thumbnail.setStyleSheet(
            f"border: {_MATCH_BORDER}; border-radius: {BUTTON_RADIUS}px;" if on else ""
        )

    def mousePressEvent(self, event):
        self.drag_out.note_press(event)

    def mouseMoveEvent(self, event):
        if not self._params or not self.drag_out.should_start(event):
            return
        self.drag_out.start(enhance_version_mime(self._params), self._drag_thumbnail)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_out.pressed:
            self.drag_out.forget()
            self.clicked.emit(self._position, event.modifiers())


class _PendingRow(_Row):
    def __init__(self, parent=None):
        super().__init__("Enhancing", parent)
        self._thumbnail.setStyleSheet(
            f"background-color: transparent; border: {_PENDING_BORDER};"
            f" border-radius: {BUTTON_RADIUS}px;"
        )
        self._settings = ""
        self.setToolTip("An enhancement of this image is being generated")

    def update_pending(self, pending: RunningEnhancement):
        pixmap = QPixmap()
        if pending.frame and pixmap.loadFromData(pending.frame) and not pixmap.isNull():
            self._show_thumbnail(pixmap)
        else:
            self._thumbnail.setText(
                "Generating…" if pending.status == JobState.RUNNING else "Queued…"
            )
        if pending.settings != self._settings:
            self._settings = pending.settings
            self._show_facts([MetadataItem("Enhancement", pending.settings)] if pending.settings else [])
        self.setToolTip(
            f"An enhancement of this image is being generated at {pending.settings}"
            if pending.settings else "An enhancement of this image is being generated"
        )


class _AddRow(_Row):
    clicked = Signal()
    hovered = Signal(bool)

    def __init__(self, settings: str, duplicate_of: int | None, parent=None):
        super().__init__("Enhance", parent)
        self._enabled = duplicate_of is None
        self._thumbnail.setStyleSheet(_ADD_TILE_CSS)
        self._thumbnail.setPixmap(icon_pixmap("plus", _PLUS, BG_PRIMARY))
        if settings:
            self._show_facts([MetadataItem("Enhancement", settings)])
        # Opacity rather than setEnabled: Qt delivers no mouse events to a disabled widget, and the hover is the point.
        if not self._enabled:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.4)
            self.setGraphicsEffect(effect)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._enabled
                       else Qt.CursorShape.ForbiddenCursor)
        self.setToolTip(
            f"Enhance this image at {settings}" if self._enabled
            else "This image already has a version at exactly these settings"
        )

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)

    def press(self) -> None:
        if self._enabled:
            self.clicked.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press()


class EnhanceVersions(QWidget):
    version_selected = Signal(int)
    enhance_requested = Signal()
    delete_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        self._section = CollapsibleSection("Enhancements")
        column.addWidget(self._section)
        self._host = QWidget()
        QVBoxLayout(self._host)
        self._section.content_form().addRow(self._host)
        self._pending: _PendingRow | None = None
        self._enhance_row: _AddRow | None = None
        self._rows: list[_VersionRow] = []
        self._picking = Picking()
        self._arrows_from: int | None = None
        self._deletable = True
        self._versions_listed = 0
        self._originals: set[int] = set()
        self.hide()

    def is_collapsed(self) -> bool:
        return self._section.is_collapsed()

    def set_collapsed(self, collapsed: bool) -> None:
        self._section.set_collapsed(collapsed)

    def show_versions(self, items: list[tuple], pending: RunningEnhancement | None = None,
                    add: EnhanceOffer | None = None, dating: Dating = UNDATED, deletable: bool = True):
        form = self._section.content_form()
        form.removeRow(self._host)
        self._host = QWidget()
        column = QVBoxLayout(self._host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_MEDIUM)
        self._pending = None
        self._enhance_row = None
        self._rows = []
        self._picking = Picking()
        self._arrows_from = None
        self._deletable = deletable
        self._versions_listed = len(items)
        self._originals = {position for position, (version, _path) in enumerate(items)
                           if version.is_original}
        if pending is not None:
            self._pending = _PendingRow()
            self._pending.update_pending(pending)
            column.addWidget(self._pending)
        elif add is not None:
            self._enhance_row = _AddRow(add.settings, add.duplicate_of)
            self._enhance_row.clicked.connect(self.enhance_requested)
            self._enhance_row.hovered.connect(
                lambda on, at=add.duplicate_of: self._highlight_version(at, on))
            column.addWidget(self._enhance_row)
        for position, (version, image_path) in enumerate(items):
            row = _VersionRow(version, position, image_path, dating,
                            deletable=bool(self._deleted_by([position])))
            row.clicked.connect(self._on_row_clicked)
            row.context_requested.connect(self._on_row_menu)
            row.delete_pressed.connect(lambda at: self.delete_requested.emit([at]))
            self._rows.append(row)
            self._picking.note_shown(position)
            column.addWidget(row)
        form.addRow(self._host)
        self.setVisible(bool(items) or pending is not None or add is not None)

    def selected_positions(self) -> list[int]:
        return self._picking.in_shown_order()

    def _on_row_clicked(self, position: int, modifiers):
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        self._arrows_from = position
        self._picking.apply(position, ctrl=ctrl, shift=shift)
        self._show_picks()
        if not (ctrl or shift):
            self.version_selected.emit(position)

    def _show_picks(self) -> None:
        if self._enhance_row is not None:
            self._enhance_row.set_selected(False)
        for row in self._rows:
            row.set_selected(self._picking.holds(row.position()))

    def _pick_only(self, position: int) -> None:
        if position == _ENHANCE_ROW:
            self._picking.clear()
            self._show_picks()
            self._enhance_row.set_selected(True)
            return
        self._picking.apply(position)
        self._show_picks()

    def _pick_and_show(self, position: int) -> None:
        self._pick_only(position)
        self.version_selected.emit(position)

    def _step_to(self, position: int) -> None:
        top = _ENHANCE_ROW if self._enhance_row is not None else 0
        position = max(top, min(position, len(self._rows) - 1))
        if position == self._arrows_from:
            return
        self._arrows_from = position
        if position == _ENHANCE_ROW:
            self._pick_only(position)
        else:
            self._pick_and_show(position)

    def _on_row_menu(self, position: int, global_pos: QPoint):
        if position in self._originals:
            return
        if position not in self.selected_positions():
            self._pick_only(position)
        doomed = self._deleted_by(self.selected_positions())
        menu = QMenu(self)
        action = menu.addAction(
            f"Delete {len(doomed)} version{'s' if len(doomed) != 1 else ''}"
        )
        if not doomed:
            action.setEnabled(False)
            action.setText("Delete (this is the image's only version)" if self._deletable
                           else "Delete (a video's versions can't be deleted here)")
        if menu.exec(global_pos) is action and doomed:
            self.delete_requested.emit(doomed)

    def _deleted_by(self, positions: list[int]) -> list[int]:
        doomed = [position for position in positions if position not in self._originals]
        if not self._deletable or not doomed or len(doomed) >= self._versions_listed:
            return []
        return doomed

    def keyPressEvent(self, event):
        step = _ARROW_STEPS.get(event.key())
        if step is not None and self._arrows_from is not None:
            self._step_to(self._arrows_from + step)
            return
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and self._arrows_from == _ENHANCE_ROW):
            self._enhance_row.press()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            doomed = self._deleted_by(self.selected_positions())
            if doomed:
                self.delete_requested.emit(doomed)
                return
        super().keyPressEvent(event)

    def _highlight_version(self, position: int | None, on: bool) -> None:
        if position is None or not 0 <= position < len(self._rows):
            return
        self._rows[position].set_highlighted(on)

    def update_pending(self, pending: RunningEnhancement | None) -> bool:
        if (self._pending is None) != (pending is None):
            return False
        if pending is not None:
            self._pending.update_pending(pending)
        return True
