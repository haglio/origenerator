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
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setFont(make_font(FONT_UI, NOTICE_TYPE_SIZE, bold=True))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        float_over_media(self)
        self.hide()

    def say(self, text: str, *, kind: str = INFO, mark: str = "") -> None:
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
