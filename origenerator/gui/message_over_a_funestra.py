from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from shared_ui.message_label import MessageLabel
from shared_ui.message_shape import INFO, MESSAGE_TOP_MARGIN


class MessageOverAFunestra(MessageLabel):
    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def say_over(self, funestra: QRect, text: str, *, kind: str = INFO, mark: str = "") -> None:
        self.say(text, kind=kind, mark=mark)
        self.reposition_over(funestra)
        self.show()
        self.raise_()

    def reposition_over(self, funestra: QRect) -> None:
        self.fit_into(funestra.width() - 2 * MESSAGE_TOP_MARGIN)
        self.move(funestra.x() + max(0, (funestra.width() - self.width()) // 2),
                  funestra.y() + MESSAGE_TOP_MARGIN)

    def shutdown(self) -> None:
        self.hide()
        self.deleteLater()
