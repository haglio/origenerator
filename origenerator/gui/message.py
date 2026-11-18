from __future__ import annotations

from PySide6.QtWidgets import QWidget
from shared_ui.message_label import MessageLabel
from shared_ui.message_shape import INFO, MESSAGE_TOP_MARGIN

from origenerator.gui.media_overlay import float_over_media, raise_over_media


class Message(MessageLabel):
    def __init__(self, host: QWidget):
        super().__init__(host)
        float_over_media(self)
        self.hide()

    def say(self, text: str, *, kind: str = INFO, mark: str = "") -> None:
        super().say(text, kind=kind, mark=mark)
        self.show()
        self.reposition()

    def reposition(self) -> None:
        host = self.parentWidget()
        self.fit_into(host.width() - 2 * MESSAGE_TOP_MARGIN)
        x = (host.width() - self.width()) // 2
        self.move(max(0, x), MESSAGE_TOP_MARGIN)
        raise_over_media(self)
