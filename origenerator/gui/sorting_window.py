"""The window for saying what each picture shows: one picture, one press, the
next. The picture fills the left and every action is a button in the grid down
the right, wearing the drawing :mod:`origenerator.picture_marks` found for it."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QKeySequence, QPainter, QPixmap, QShortcut
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
from shared_ui.spacing import GAP_MEDIUM, MARGIN_STANDARD

# Sized so every action fits down one side of this screen without scrolling.
_MARK = 96
_TILE_HEIGHT = _MARK + 62

STATUS_LINE = "sorting.status"
LAST_LINE = "sorting.last"
SKIP_BUTTON = "sorting.skip"
SAME_BUTTON = "sorting.same"
UNDO_BUTTON = "sorting.undo"


def state_button(state: str) -> str:
    return f"sorting.state.{state}"


def one_term_to_a_line(state: str) -> str:
    return "\n".join(term.strip() for term in state.split(","))


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


def on_a_white_square(source: QPixmap, side: int, scale: float) -> QPixmap:
    canvas = QPixmap(side, side)
    canvas.fill(Qt.GlobalColor.white)
    if source.isNull():
        return canvas
    drawn = source.scaled(max(1, round(source.width() * scale)),
                          max(1, round(source.height() * scale)),
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawPixmap((side - drawn.width()) // 2, (side - drawn.height()) // 2, drawn)
    painter.end()
    return canvas


class SortingWindow(QWidget):

    NOTHING_LEFT = "Nothing left to sort."
    MISSING = "(this one's file is missing)"

    def __init__(self, session, rows, marks: dict[str, str], parent=None):
        super().__init__(parent)
        self._session = session
        self._marks = dict(marks)
        self._tiles: dict[str, QToolButton] = {}
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
        layout.addWidget(self._build_states(rows))

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self._show_current()


    def _build_states(self, rows) -> QWidget:
        column = QVBoxLayout()
        column.setSpacing(GAP_MEDIUM)
        grid = QGridLayout()
        grid.setSpacing(GAP_MEDIUM)
        drawings = {state: QPixmap(str(self._marks[state]))
                    for row in rows for state in row if self._marks.get(state)}
        scale = one_scale_for_all(drawings.values(), _MARK)
        for down, row in enumerate(rows):
            for across, state in enumerate(row):
                grid.addWidget(self._state_tile(state, drawings.get(state), scale),
                               down, across)
        self._make_every_tile_one_size()
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

    def _make_every_tile_one_size(self) -> None:
        tiles = list(self._tiles.values())
        if not tiles:
            return
        widest = max(tile.sizeHint().width() for tile in tiles)
        tallest = max(_TILE_HEIGHT, *(tile.sizeHint().height() for tile in tiles))
        for tile in tiles:
            tile.setFixedSize(widest, tallest)

    def _state_tile(self, state: str, drawing: QPixmap | None,
                    scale: float) -> QToolButton:
        tile = QToolButton(objectName=state_button(state))
        tile.setText(one_term_to_a_line(state))
        tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tile.setIconSize(QSize(_MARK, _MARK))
        tile.setMinimumHeight(_TILE_HEIGHT)
        # Never the keyboard's: Space would otherwise re-fire whichever tile was
        # pressed last, and Escape has to go on closing the window.
        tile.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tile.clicked.connect(lambda _checked=False, state=state: self._on_state(state))
        self._tiles[state] = tile
        if drawing is not None and not drawing.isNull():
            tile.setIcon(QIcon(on_a_white_square(drawing, _MARK, scale)))
        return tile


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
