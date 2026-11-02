"""Qt passes a drop up to the first widget that takes drops and stops only where the drag was taken."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.generation_drag import generation_mime


def let_go_over(widget: QWidget, prompt_id: str) -> QDragEnterEvent:
    mime = generation_mime(prompt_id)
    at = QPointF(widget.rect().center())
    held = (Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
    enter = QDragEnterEvent(at.toPoint(), *held)
    QApplication.sendEvent(widget, enter)
    if enter.isAccepted():
        QApplication.sendEvent(widget, QDropEvent(at, *held))
    return enter
