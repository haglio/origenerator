from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

_OWN_TEXT_COLOR = "ownTextColor"


def color_text(widget: QWidget, color: QColor) -> None:
    widget.setProperty(_OWN_TEXT_COLOR, True)
    widget.setStyleSheet(f'*[{_OWN_TEXT_COLOR}="true"] {{ color: {color.name()}; }}')
