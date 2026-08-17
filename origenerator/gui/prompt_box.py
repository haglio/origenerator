"""A prompt field you can drag taller, at a height it keeps.

A prompt here runs to hundreds of words through a box a hundred pixels tall, so
most of what you wrote has scrolled away while you are still writing it. The
bottom edge of the box is a drag handle: grab it and the field grows, the way a
browser's textarea does.

The height belongs to the *param*, app-wide — every Positive Prompt is as tall
as the last one you dragged, in every tab and every workflow, and it comes back
that size next launch (:mod:`origenerator.gui.main_window` carries the sizes in
and out of ``ui_state.json``). A per-widget height would be lost on each of
those, and this form is rebuilt on every workflow switch and every new tab, so
it would mean dragging the same box open over and over. Each param keeps its own
number, so a tall Positive Prompt doesn't drag the short Negative one open with
it.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QPlainTextEdit

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE

# What an undragged prompt box has always been.
DEFAULT_HEIGHT = 100
# A drag stops here: a box taller than any monitor is a slip of the mouse rather
# than a request, and it would bury the rest of the form under itself.
MAX_HEIGHT = 1600
# The band along the bottom edge that grabs the box instead of placing the text
# cursor. Narrow, like a splitter handle — the rest of the field is for typing.
GRIP = 6
# How wide the pair of rules drawn on that band is.
_MARK_WIDTH = 24


class PromptHeights(QObject):
    """How tall each prompt param's box is: one number per param key, app-wide.

    ``changed`` is what lets the boxes already on screen follow a drag, so "the
    Positive Prompt box is this tall" holds across the open tabs rather than only
    for the ones built after it.
    """

    changed = pyqtSignal(str, int)      # (param key, height in px)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._heights: dict[str, int] = {}

    def height(self, key: str) -> int:
        """The height boxes for ``key`` open at — the default until one is dragged."""
        return self._heights.get(key, DEFAULT_HEIGHT)

    def set_height(self, key: str, height: int) -> None:
        """Remember a dragged height and tell the boxes showing that param."""
        height = min(int(height), MAX_HEIGHT)
        if height == self._heights.get(key):
            return
        self._heights[key] = height
        self.changed.emit(key, height)

    def snapshot(self) -> dict:
        """The remembered heights, for the session state."""
        return dict(self._heights)

    def restore(self, heights) -> None:
        """Take a saved snapshot as the whole set of remembered heights.

        Authoritative rather than merged, so restoring an empty snapshot puts
        every box back to the default. Anything that isn't a key-to-number map is
        ignored — a hand-edited or older ``ui_state.json`` opens at the defaults
        instead of failing the launch.
        """
        previous = self._heights
        self._heights = {}
        if isinstance(heights, dict):
            for key, height in heights.items():
                if isinstance(key, str) and _is_number(height):
                    self._heights[key] = min(int(height), MAX_HEIGHT)
        for key in set(previous) | set(self._heights):
            if previous.get(key) != self._heights.get(key):
                self.changed.emit(key, self.height(key))


def _is_number(value) -> bool:
    # bool is an int as far as isinstance is concerned, and a height of True is
    # a corrupt value, not a one-pixel box.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# App-wide, one per process — the same box size wherever a param is shown.
PROMPT_HEIGHTS = PromptHeights()


class PromptBox(QPlainTextEdit):
    """A multiline prompt field whose bottom edge drags to resize it.

    ``key`` is the param it edits, which is what its height is filed under in
    :data:`PROMPT_HEIGHTS`.
    """

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._drag: tuple[float, int] | None = None   # (grabbed at, height then)
        # Without tracking, the edge can only offer its resize cursor while a
        # button is already down — by which time you have clicked into the text.
        self.viewport().setMouseTracking(True)
        self._apply_height(PROMPT_HEIGHTS.height(key))
        PROMPT_HEIGHTS.changed.connect(self._on_shared_height_changed)

    # --- the height ----------------------------------------------------------

    def _on_shared_height_changed(self, key: str, height: int):
        """Follow a drag (or a restore) of this param's box elsewhere."""
        if key == self._key:
            self._apply_height(height)

    def _apply_height(self, height: int):
        self.setFixedHeight(max(self._min_height(), min(int(height), MAX_HEIGHT)))

    def _min_height(self) -> int:
        """One line of text plus the box's own furniture — where a drag upward
        stops. Measured rather than a constant: the form runs at the app's
        heading font and inside a stylesheet that pads the field, so a number
        that leaves a line visible in one place clips it in another."""
        # Frame and stylesheet padding both, whatever the style makes of them.
        chrome = max(self.height() - self.viewport().height(), 2 * self.frameWidth())
        return (self.fontMetrics().lineSpacing()
                + 2 * int(self.document().documentMargin()) + chrome)

    # --- dragging the edge ---------------------------------------------------

    def _in_grip(self, pos) -> bool:
        """Is this point on the bottom edge's drag band?

        Mouse events on a scroll area arrive in *viewport* coordinates, so the
        band is measured from the viewport's own bottom — which also means the
        scrollbar, a child with its own events, is never part of it.
        """
        return pos.y() >= self.viewport().height() - GRIP

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._in_grip(event.position()):
            # Deliberately not passed on: a press on the handle takes hold of the
            # edge, it doesn't drop the text cursor at the end of the last line.
            self._drag = (event.globalPosition().y(), self.height())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            grabbed_at, height = self._drag
            # Against the screen, not the widget: the box moves under the pointer
            # as it grows, so its own coordinates shift mid-drag.
            self._apply_height(int(height + event.globalPosition().y() - grabbed_at))
            event.accept()
            return
        self.viewport().setCursor(
            Qt.CursorShape.SizeVerCursor if self._in_grip(event.position())
            else Qt.CursorShape.IBeamCursor
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            # File the height it actually settled at — a drag past the floor stops
            # there — so the other boxes for this param land on the same size.
            PROMPT_HEIGHTS.set_height(self._key, self.height())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Two short rules on the handle. A drag target you can't see is one you
        # find only by dragging something at random to see what happens.
        painter = QPainter(self.viewport())
        painter.setPen(QPen(BORDER_SUBTLE, 1))
        middle = self.viewport().width() // 2
        bottom = self.viewport().height() - 2
        for y in (bottom, bottom - 3):
            painter.drawLine(middle - _MARK_WIDTH // 2, y, middle + _MARK_WIDTH // 2, y)
        painter.end()
