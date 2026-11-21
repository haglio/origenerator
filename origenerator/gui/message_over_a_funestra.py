from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, Qt, QTimer
from shared_ui.message_label import MessageLabel
from shared_ui.message_shape import INFO, MESSAGE_TOP_MARGIN

from origenerator.win32 import stack_just_above

FOLLOW_EVERY_MS = 150


class MessageOverAFunestra(MessageLabel):
    def __init__(self, *, stack: Callable[[int, int], bool] = stack_just_above) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._stack = stack
        self._slideshow_window: int | None = None
        self._follow = QTimer(self)
        self._follow.setInterval(FOLLOW_EVERY_MS)
        self._follow.timeout.connect(self._sit_on_the_slideshow)

    def stay_above(self, slideshow_window: int) -> None:
        self._slideshow_window = slideshow_window

    def say_over(self, funestra: QRect, text: str, *, kind: str = INFO, mark: str = "") -> None:
        self.say(text, kind=kind, mark=mark)
        self.reposition_over(funestra)
        self.show()
        self._sit_on_the_slideshow()
        self._follow.start()

    def _sit_on_the_slideshow(self) -> None:
        if not self.isVisible():
            self._follow.stop()
        elif self._slideshow_window is not None:
            self._stack(int(self.winId()), self._slideshow_window)

    def reposition_over(self, funestra: QRect) -> None:
        self.fit_into(funestra.width() - 2 * MESSAGE_TOP_MARGIN)
        self.move(funestra.x() + max(0, (funestra.width() - self.width()) // 2),
                  funestra.y() + MESSAGE_TOP_MARGIN)

    def shutdown(self) -> None:
        self._follow.stop()
        self.hide()
        self.deleteLater()
