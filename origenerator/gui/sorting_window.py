"""The window for saying what each picture shows: one picture, one press, the
next. The picture fills the left and every action is a button in the grid down
the right, wearing the drawing :mod:`origenerator.picture_marks` found for it."""
from __future__ import annotations

import re

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
from shared_ui.spacing import GAP_MEDIUM, MARGIN_STANDARD

# The room nine rows of buttons have on the shortest screen he works on, and
# the drawing he asked for, which gives up pixels the rows cannot spare.
ROOM_FOR_THE_GRID = 1260
MARK = 96
NAME_LINES = 2

STATUS_LINE = "sorting.status"
LAST_LINE = "sorting.last"
SKIP_BUTTON = "sorting.skip"
SAME_BUTTON = "sorting.same"
UNDO_BUTTON = "sorting.undo"


def state_button(state: str) -> str:
    return f"sorting.state.{state}"


def one_term_to_a_line(state: str) -> str:
    lines = re.sub(r",\s*", "\n", state)
    lines = re.sub(r"\s*\+\s*", " +\n", lines)
    return re.sub(r"\s+\(", "\n(", lines).strip()


def a_name_for(state: str, room: int, width_of) -> str:
    if width_of(state) <= room:
        return state
    return wrapped_to_fit(one_term_to_a_line(state), room, width_of)


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


def _fitted(source: QPixmap, width: int, height: int) -> QPixmap:
    if source.isNull() or width < 1 or height < 1:
        return QPixmap()
    return source.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def one_scale_for_all(drawings, side: int) -> float:
    """The one factor fitting the largest drawing in a *side*-square, so each
    keeps its size against the others rather than filling the square itself."""
    largest = max((max(drawing.width(), drawing.height()) for drawing in drawings
                   if not drawing.isNull()), default=0)
    return side / largest if largest else 1.0


def on_a_white_square(source: QPixmap, side: int, scale: float,
                      above: int = 0) -> QPixmap:
    """The drawing on a white square, under *above* pixels of clear space."""
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


class SortingWindow(QWidget):

    NOTHING_LEFT = "Nothing left to sort."
    MISSING = "(this one's file is missing)"

    def __init__(self, session, tiles, marks: dict[str, str], parent=None):
        super().__init__(parent)
        self._session = session
        self._marks = dict(marks)
        self._tiles: dict[str, QToolButton] = {}
        self._faces: dict[str, QToolButton] = {}
        self._name_font = make_font(size=SIZE_SMALL)
        self._mark = MARK
        # The picture at its own size, kept so a resize re-scales from the
        # original rather than from an already-shrunk copy.
        self._shown = QPixmap()
        self.setWindowTitle("Origenerator — what does this picture show?")

        self._picture = QLabel()
        self._picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._picture.setMinimumSize(320, 320)
        self._status = QLabel(objectName=STATUS_LINE)
        self._last = QLabel(objectName=LAST_LINE)
        for line in (self._status, self._last):
            line.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stage = QVBoxLayout()
        stage.setContentsMargins(0, 0, 0, 0)
        stage.setSpacing(GAP_MEDIUM)
        stage.addWidget(self._picture, 1)
        stage.addWidget(self._status)
        stage.addWidget(self._last)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                  MARGIN_STANDARD, MARGIN_STANDARD)
        layout.setSpacing(GAP_MEDIUM)
        layout.addLayout(stage, 1)
        layout.addWidget(self._build_states(tiles))

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self._show_current()


    def _build_states(self, tiles) -> QWidget:
        column = QVBoxLayout()
        column.setSpacing(GAP_MEDIUM)
        grid = QGridLayout()
        grid.setSpacing(GAP_MEDIUM)
        drawings = {tile.state: QPixmap(str(self._marks[tile.state]))
                    for tile in tiles if self._marks.get(tile.state)}
        scale = one_scale_for_all(drawings.values(), MARK)
        room = self._room_for_a_name(tiles)
        wide = QFontMetrics(self._name_font).horizontalAdvance
        named = {tile.state: a_name_for(
            tile.state, room * tile.columns + GAP_MEDIUM * (tile.columns - 1), wide)
            for tile in tiles}
        for tile in tiles:
            grid.addWidget(
                self._state_tile(tile.state, drawings.get(tile.state), scale,
                                 named[tile.state], tile.rows),
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
             "Leave this one unsorted and come back to it at the end", self._on_skip),
            (SAME_BUTTON, "Same as last",
             "Sort this one the way the last one was sorted", self._on_same),
            (UNDO_BUTTON, "Undo",
             "Take the last answer back and put its picture up again", self._on_undo),
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
        panel = QScrollArea()
        panel.setWidget(inside)
        panel.setWidgetResizable(True)
        panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Fixed to what the column asks for, so the picture takes every other
        # pixel of the window.
        panel.setFixedWidth(inside.sizeHint().width() + 28)  # room for the scrollbar
        return panel

    def _make_every_tile_one_size(self, tiles, drawings, scale) -> None:
        faces = [self._face(state) for state in self._tiles]
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
            self._tiles[tile.state].setFixedSize(
                wide, tallest * tile.rows + GAP_MEDIUM * (tile.rows - 1))
            if tile.state in self._faces:
                self._faces[tile.state].setFixedSize(wide, tallest)

    def _room_for_a_name(self, tiles) -> int:
        metrics = QFontMetrics(self._name_font)
        named = [one_term_to_a_line(tile.state) for tile in tiles]
        widest = max(metrics.horizontalAdvance(word)
                     for name in named for word in name.replace("\n", " ").split())
        room = max(MARK, widest)
        while any(wrapped_to_fit(name, room, metrics.horizontalAdvance).count("\n")
                  >= NAME_LINES for name in named):
            room += 1
        return room

    def _state_tile(self, state: str, drawing: QPixmap | None, scale: float,
                    name: str, rows: int = 1) -> QToolButton:
        tile = QToolButton(objectName=state_button(state))
        # Never the keyboard's: Space would otherwise re-fire whichever tile was
        # pressed last, and Escape has to go on closing the window.
        tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile.clicked.connect(lambda _checked=False, state=state: self._on_state(state))
        self._tiles[state] = tile
        face = tile if rows == 1 else self._face_in_the_middle_row(state, tile)
        face.setText(name)
        face.setFont(self._name_font)
        face.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        face.setIconSize(QSize(MARK, MARK))
        if drawing is not None and not drawing.isNull():
            face.setIcon(QIcon(on_a_white_square(drawing, MARK, scale)))
        return tile

    def _face_in_the_middle_row(self, state: str, tile) -> QToolButton:
        face = QToolButton(tile)
        face.setAutoRaise(True)
        face.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        held = QVBoxLayout(tile)
        held.setContentsMargins(0, 0, 0, 0)
        held.addStretch(1)
        held.addWidget(face, 0, Qt.AlignmentFlag.AlignHCenter)
        held.addStretch(1)
        self._faces[state] = face
        return face

    def _face(self, state: str) -> QToolButton:
        return self._faces.get(state, self._tiles[state])

    def _draw_at(self, mark: int, drawings, scale: float, above: int = 0) -> None:
        for state in self._tiles:
            self._draw_one(self._face(state), drawings.get(state), mark, scale, above)

    def _draw_one(self, tile, drawing, mark: int, scale: float, above: int) -> None:
        tile.setIconSize(QSize(mark, mark + above))
        if drawing is not None and not drawing.isNull():
            tile.setIcon(QIcon(on_a_white_square(drawing, mark, scale * mark / MARK,
                                                 above)))

    def _center_the_block(self, tiles, tallest: int, drawings, scale: float) -> None:
        line = QFontMetrics(self._name_font).height()
        for tile in tiles:
            face = self._face(tile.state)
            spare = tallest - self._mark - line * (face.text().count("\n") + 1)
            if spare > 1:
                self._draw_one(face, drawings.get(tile.state), self._mark, scale,
                               spare // 2)


    def _on_state(self, state: str) -> None:
        if self._session.current is None:
            return
        self._session.sort_as(state)
        self._said(f"Last: {state}")

    def _on_same(self) -> None:
        state = self._session.last_state
        if self._session.current is None or state is None:
            self._said("Nothing sorted yet to go by")
            return
        self._session.same()
        self._said(f"Last: {state}")

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

    def _said(self, line: str) -> None:
        self._last.setText(line)
        self._show_current()


    def _show_current(self) -> None:
        picture = self._session.current
        if picture is None:
            self._shown = QPixmap()
            self._picture.clear()
            self._status.setText(self.NOTHING_LEFT)
            return
        self._status.setText(f"{self._session.remaining} left · {picture.get('name')}")
        path = picture.get("picture_path")
        self._shown = QPixmap(str(path)) if path else QPixmap()
        self._fill_with_the_picture()

    def _fill_with_the_picture(self) -> None:
        if self._shown.isNull():
            self._picture.setText(self.MISSING)
            return
        self._picture.setPixmap(_fitted(self._shown, self._picture.width(),
                                        self._picture.height()))

    def resizeEvent(self, event):  # noqa: N802 — Qt override
        super().resizeEvent(event)
        self._fill_with_the_picture()
