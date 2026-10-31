"""What a slideshow has to say, in the message Fun Time says it in.

Fun Time flashes its messages — "Clip saved", "No other seeds", "Next seed" — at
the top center of the Funestra they are about, in one shape everywhere: the
secondary gray, a hairline of the text's own color, a bold heading face, rounded corners
(Fun Time's own message, in its ``notice_overlay``). This is that message, worn by
Origenerator's own: the request being spoken, and what a press or a
spoken word just did. A plate of its own down at the foot of the slideshow would be
a second dialect for the same job, said in the same room, on a surface that
already wears the Funestras' own HUD.

Matched through the tokens rather than by eye: the color, the face and the
shape come out of :mod:`shared_ui` (its ``notice_shape``), which is where Fun
Time takes them from too, so a change moves both at once.

A child of the surface rather than a window of its own — Fun Time's is a
top-level because it flashes over a *foreign* Funestra's window, and here the
surface it belongs to is ours.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget
from shared_ui.colors import BG_SECONDARY, GREEN, RED, TEXT_PRIMARY, YELLOW
from shared_ui.fonts import FONT_UI, make_font
from shared_ui.icons import icon_then_text
from shared_ui.notice_shape import (
    NOTICE_PAD_H,
    NOTICE_PAD_V,
    NOTICE_RADIUS,
    NOTICE_TOP_MARGIN,
    NOTICE_TYPE_SIZE,
)

from origenerator.gui.media_overlay import float_over_media, raise_over_media

INFO = "info"
WARNING = "warning"
ERROR = "error"
FAVORITE = "favorite"
_INK = {INFO: TEXT_PRIMARY, WARNING: YELLOW, ERROR: RED, FAVORITE: GREEN}

HEARD_MARK = "mic"


def set_marked_text(label: QLabel, text: str, *, mark: str, color) -> None:
    if not mark:
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(text)
        return
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setText(icon_then_text(mark, text, color=color, size=label.fontMetrics().height()))


class Message(QLabel):
    """One line, centered across the top of the surface it belongs to."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setFont(make_font(FONT_UI, NOTICE_TYPE_SIZE, bold=True))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        float_over_media(self)
        self.hide()

    def say(self, text: str, *, kind: str = INFO, mark: str = "") -> None:
        """Put *text* up, and keep it up until something says otherwise."""
        ink = _INK[kind].name()
        self.setStyleSheet(
            f"background-color: {BG_SECONDARY.name()};"
            f" color: {ink}; border: 1px solid {ink};"
            f" padding: {NOTICE_PAD_V}px {NOTICE_PAD_H}px; border-radius: {NOTICE_RADIUS}px;"
        )
        set_marked_text(self, text, mark=mark, color=_INK[kind])
        self.show()
        self.reposition()

    def reposition(self) -> None:
        host = self.parentWidget()
        self.adjustSize()
        x = (host.width() - self.width()) // 2
        self.move(max(0, x), NOTICE_TOP_MARGIN)
        raise_over_media(self)
