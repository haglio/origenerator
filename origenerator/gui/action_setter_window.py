from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import (
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.colors import WHITE
from shared_ui.fonts import SIZE_SMALL, make_font
from shared_ui.icons import qt_icon
from shared_ui.palette import BLUE, as_hex
from shared_ui.spacing import BUTTON_RADIUS, GAP_MEDIUM, MARGIN_STANDARD
from shared_ui.tick_control import TickControl

from origenerator.action_labels import Labels
from origenerator.media import MediaType

ROOM_FOR_THE_GRID = 1260
MARK = 96
NAME_LINES = 2

STATUS_LINE = "setter.status"
LAST_LINE = "setter.last"
SKIP_BUTTON = "setter.skip"
SAME_BUTTON = "setter.same"
UNDO_BUTTON = "setter.undo"
TITLES = {MediaType.IMAGE: "Origenerator — image action setter tool",
          MediaType.VIDEO: "Origenerator — video action setter tool"}

_LIT = f"QToolButton:checked {{ background-color: {as_hex(BLUE)}; border-radius: {BUTTON_RADIUS}px; }}"


def action_button(name: str) -> str:
    return f"setter.action.{name}"


def checkbox(name: str) -> str:
    return f"setter.checkbox.{name}"


def lock(name: str) -> str:
    return f"setter.lock.{name}"


def one_term_to_a_line(name: str) -> str:
    lines = re.sub(r",\s*", "\n", name)
    lines = re.sub(r"\s*\+\s*", " +\n", lines)
    return re.sub(r"\s+\(", "\n(", lines).strip()


def a_name_for(name: str, room: int, width_of) -> str:
    if width_of(name) <= room:
        return name
    return wrapped_to_fit(one_term_to_a_line(name), room, width_of)


def wrapped_to_fit(text: str, room: int, width_of) -> str:
    lines = []
    for line in text.split("\n"):
        standing = ""
        for word in line.split(" "):
            tried = f"{standing} {word}".strip()
            if standing and width_of(tried) > room:
                lines.append(standing)
                standing = word
            else:
                standing = tried
        lines.append(standing)
    return "\n".join(lines)


def one_scale_for_all(drawings, side: int) -> float:
    largest = max((max(drawing.width(), drawing.height()) for drawing in drawings
                   if not drawing.isNull()), default=0)
    return side / largest if largest else 1.0


def on_a_white_square(source: QPixmap, side: int, scale: float,
                      above: int = 0) -> QPixmap:
    canvas = QPixmap(side, side + above)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.fillRect(0, above, side, side, WHITE)
    if not source.isNull():
        drawn = source.scaled(max(1, round(source.width() * scale)),
                              max(1, round(source.height() * scale)),
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((side - drawn.width()) // 2,
                           above + (side - drawn.height()) // 2, drawn)
    painter.end()
    return canvas


class ActionSetterWindow(QWidget):

    NOTHING_LEFT = "Nothing left to set."
    MISSING = "(this one's file is missing)"

    def __init__(self, session, vocabulary, drawings: dict[str, str], locks, *,
                 stage=None, parent=None):
        super().__init__(parent)
        self._session = session
        self._vocabulary = vocabulary
        self._drawings = dict(drawings)
        self._locks = locks
        self._tiles: dict[str, QToolButton] = {}
        self._faces: dict[str, QToolButton] = {}
        self._boxes: dict[str, TickControl] = {}
        self._name_font = make_font(size=SIZE_SMALL)
        self._mark = MARK
        self.setWindowTitle(TITLES[session.side])

        self._stage = stage if stage is not None else _a_viewport()
        self._stage.setMinimumSize(320, 320)
        self._status = QLabel(objectName=STATUS_LINE)
        self._last = QLabel(objectName=LAST_LINE)
        for line in (self._status, self._last):
            line.setAlignment(Qt.AlignmentFlag.AlignCenter)

        shown = QVBoxLayout()
        shown.setContentsMargins(0, 0, 0, 0)
        shown.setSpacing(GAP_MEDIUM)
        shown.addWidget(self._stage, 1)
        shown.addWidget(self._status)
        shown.addWidget(self._last)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                  MARGIN_STANDARD, MARGIN_STANDARD)
        layout.setSpacing(GAP_MEDIUM)
        layout.addLayout(shown, 1)
        layout.addWidget(self._build_buttons(vocabulary.tiles))

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self._show_current()

    def _build_buttons(self, tiles) -> QWidget:
        column = QVBoxLayout()
        column.setSpacing(GAP_MEDIUM)
        boxes = QHBoxLayout()
        boxes.setSpacing(GAP_MEDIUM)
        for name in self._vocabulary.checkboxes:
            self._add_checkbox(boxes, name)
        boxes.addStretch(1)
        column.addLayout(boxes)
        grid = QGridLayout()
        grid.setSpacing(GAP_MEDIUM)
        drawings = {tile.name: QPixmap(str(self._drawings[tile.name]))
                    for tile in tiles if self._drawings.get(tile.name)}
        scale = one_scale_for_all(drawings.values(), MARK)
        room = self._room_for_a_name(tiles)
        wide = QFontMetrics(self._name_font).horizontalAdvance
        named = {tile.name: a_name_for(
            tile.name, room * tile.columns + GAP_MEDIUM * (tile.columns - 1), wide)
            for tile in tiles}
        for tile in tiles:
            grid.addWidget(
                self._action_tile(tile.name, drawings.get(tile.name), scale,
                                  named[tile.name], tile.rows),
                tile.row, tile.column, tile.rows, tile.columns,
                Qt.AlignmentFlag.AlignCenter)
        self._make_every_tile_one_size(tiles, drawings, scale)
        column.addLayout(grid)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        column.addWidget(divider)

        controls = QHBoxLayout()
        controls.setSpacing(GAP_MEDIUM)
        for name, caption, tip, press in (
            (SKIP_BUTTON, "Skip",
             "Leave this one as it is and come back to it at the end", self._on_skip),
            (SAME_BUTTON, "Same as last",
             "Give this one the actions the last one got", self._on_same),
            (UNDO_BUTTON, "Undo",
             "Take the last answer back and put its item up again", self._on_undo),
        ):
            button = QPushButton(caption, objectName=name)
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(press)
            controls.addWidget(button)
        column.addLayout(controls)
        column.addStretch(1)

        inside = QWidget()
        inside.setLayout(column)
        scroll = QScrollArea()
        scroll.setWidget(inside)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(inside.sizeHint().width() + 28)
        return scroll

    def _add_checkbox(self, row: QHBoxLayout, name: str) -> None:
        box = TickControl(name)
        box.setObjectName(checkbox(name))
        box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        held = QToolButton(objectName=lock(name))
        held.setCheckable(True)
        held.setIcon(qt_icon("lock"))
        held.setStyleSheet(_LIT)
        held.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        held.setChecked(name in self._locks.held(self._session.side))
        held.setToolTip(_lock_tip(held.isChecked()))
        held.toggled.connect(lambda locked, name=name: self._on_lock(name, locked))
        box.toggled.connect(lambda checked, name=name: self._on_box(name, checked))
        self._boxes[name] = box
        row.addWidget(box)
        row.addWidget(held)

    def _make_every_tile_one_size(self, tiles, drawings, scale) -> None:
        faces = [self._face(name) for name in self._tiles]
        if not faces:
            return
        rows = max((tile.row + tile.rows for tile in tiles), default=1)
        allowed = (ROOM_FOR_THE_GRID - GAP_MEDIUM * (rows - 1)) // rows
        tall = max(face.sizeHint().height() for face in faces)
        self._mark = MARK if tall <= allowed else MARK - (tall - allowed)
        self._draw_at(self._mark, drawings, scale)
        widest = max(face.sizeHint().width() for face in faces)
        tallest = max(face.sizeHint().height() for face in faces)
        self._center_the_block(tiles, tallest, drawings, scale)
        for tile in tiles:
            wide = widest * tile.columns + GAP_MEDIUM * (tile.columns - 1)
            self._tiles[tile.name].setFixedSize(
                wide, tallest * tile.rows + GAP_MEDIUM * (tile.rows - 1))
            if tile.name in self._faces:
                self._faces[tile.name].setFixedSize(wide, tallest)

    def _room_for_a_name(self, tiles) -> int:
        metrics = QFontMetrics(self._name_font)
        named = [one_term_to_a_line(tile.name) for tile in tiles]
        widest = max((metrics.horizontalAdvance(word)
                      for name in named for word in name.replace("\n", " ").split()), default=0)
        room = max(MARK, widest)
        while any(wrapped_to_fit(name, room, metrics.horizontalAdvance).count("\n")
                  >= NAME_LINES for name in named):
            room += 1
        return room

    def _action_tile(self, name: str, drawing: QPixmap | None, scale: float,
                     shown: str, rows: int = 1) -> QToolButton:
        tile = QToolButton(objectName=action_button(name))
        tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile.clicked.connect(lambda _checked=False, name=name: self._on_action(name))
        self._tiles[name] = tile
        face = tile if rows == 1 else self._face_in_the_middle_row(name, tile)
        face.setText(shown)
        face.setFont(self._name_font)
        face.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        face.setIconSize(QSize(MARK, MARK))
        if drawing is not None and not drawing.isNull():
            face.setIcon(QIcon(on_a_white_square(drawing, MARK, scale)))
        return tile

    def _face_in_the_middle_row(self, name: str, tile) -> QToolButton:
        face = QToolButton(tile)
        face.setAutoRaise(True)
        face.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        held = QVBoxLayout(tile)
        held.setContentsMargins(0, 0, 0, 0)
        held.addStretch(1)
        held.addWidget(face, 0, Qt.AlignmentFlag.AlignHCenter)
        held.addStretch(1)
        self._faces[name] = face
        return face

    def _face(self, name: str) -> QToolButton:
        return self._faces.get(name, self._tiles[name])

    def _draw_at(self, mark: int, drawings, scale: float, above: int = 0) -> None:
        for name in self._tiles:
            self._draw_one(self._face(name), drawings.get(name), mark, scale, above)

    def _draw_one(self, tile, drawing, mark: int, scale: float, above: int) -> None:
        tile.setIconSize(QSize(mark, mark + above))
        if drawing is not None and not drawing.isNull():
            tile.setIcon(QIcon(on_a_white_square(drawing, mark, scale * mark / MARK,
                                                 above)))

    def _center_the_block(self, tiles, tallest: int, drawings, scale: float) -> None:
        line = QFontMetrics(self._name_font).height()
        for tile in tiles:
            face = self._face(tile.name)
            spare = tallest - self._mark - line * (face.text().count("\n") + 1)
            if spare > 1:
                self._draw_one(face, drawings.get(tile.name), self._mark, scale,
                               spare // 2)


    def _checked(self) -> tuple[str, ...]:
        return tuple(name for name, box in self._boxes.items() if box.isChecked())

    def _on_action(self, name: str) -> None:
        if self._session.current is None:
            return
        self._session.set_as(name, Labels(self._vocabulary.buttons[name], self._checked()))
        self._said(f"Last: {name}")

    def _on_same(self) -> None:
        last = self._session.last
        if self._session.current is None or last is None:
            self._said("Nothing set yet to go by")
            return
        said, labels = last
        self._session.set_as(said, Labels(labels.actions, self._checked()))
        self._said(f"Last: {said}")

    def _on_skip(self) -> None:
        if self._session.current is None:
            return
        self._session.skip()
        self._said("Last: skipped")

    def _on_undo(self) -> None:
        if not self._session.can_undo:
            self._said("Nothing to undo")
            return
        self._session.undo()
        self._said("Last: undone")

    def _on_lock(self, name: str, locked: bool) -> None:
        self.findChild(QToolButton, lock(name)).setToolTip(_lock_tip(locked))
        if locked:
            self._locks.hold(self._session.side, name, self._box(name).isChecked())
        else:
            self._locks.let_go(self._session.side, name)

    def _box(self, name: str) -> TickControl:
        return self._boxes[name]

    def _on_box(self, name: str, checked: bool) -> None:
        if name in self._locks.held(self._session.side):
            self._locks.hold(self._session.side, name, checked)

    def _said(self, line: str) -> None:
        self._last.setText(line)
        self._show_current()

    def _show_current(self) -> None:
        item = self._session.current
        if item is None:
            self._stage.show_message("")
            self._status.setText(self.NOTHING_LEFT)
            return
        self._status.setText(f"{self._session.remaining} left · {item.get('name')}")
        self._set_the_boxes_for(item)
        path = item.get("path")
        if path and Path(path).is_file():
            self._stage.show_media(path, self._session.side)
        else:
            self._stage.show_message(self.MISSING)

    def _set_the_boxes_for(self, item: dict) -> None:
        held = self._locks.held(self._session.side)
        _set(self._boxes, held, (item.get("labels") or Labels()).checked)

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        self._stage.clear()
        super().closeEvent(event)


def _set(boxes: dict[str, TickControl], held: dict[str, bool], its_own: tuple[str, ...]) -> None:
    for name, box in boxes.items():
        box.blockSignals(True)
        box.setChecked(held.get(name, name in its_own))
        box.blockSignals(False)


def _lock_tip(locked: bool) -> str:
    return ("Kept for every item until you unlock it" if locked
            else "Lock to keep this box as it is for every item")


def _a_viewport():
    from origenerator.gui.viewport import Viewport  # noqa: PLC0415 -- tests hand the window a stage

    return Viewport()
