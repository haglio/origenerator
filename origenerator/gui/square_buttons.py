from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.spacing import BUTTON_SIZE

from origenerator import ui_scale

_IN_FUN_TIME = "drawnInFunTime"
_SQUARE = "squareAtTheHudsScale"


def drawn_in_fun_time() -> bool:
    application = QApplication.instance()
    return application is not None and bool(application.property(_IN_FUN_TIME))


def draw_in_fun_time(in_fun_time: bool) -> None:
    QApplication.instance().setProperty(_IN_FUN_TIME, in_fun_time)


def landing(length: int) -> int:
    return ui_scale.landing_at_the_huds_scale(length, hosted=drawn_in_fun_time())


def square(button: QAbstractButton) -> QAbstractButton:
    button.setProperty(_SQUARE, True)
    return fill_square_with_icon(button, size=landing(BUTTON_SIZE))


def draw_every_square_again(root: QWidget) -> None:
    for button in root.findChildren(QAbstractButton):
        if button.property(_SQUARE):
            fill_square_with_icon(button, size=landing(BUTTON_SIZE))
