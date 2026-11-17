"""Qt passes a drop up to the first widget that takes drops and stops only where the drag was taken."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QWidget

from origenerator.gui.generation_drag import generation_mime

_SPOT = QPointF(5, 5)


def _held(mime) -> tuple:
    return (Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)


def let_go_over(widget: QWidget, prompt_id: str) -> QDragEnterEvent:
    mime = generation_mime(prompt_id)
    at = QPointF(widget.rect().center())
    enter = QDragEnterEvent(at, *_held(mime))
    QApplication.sendEvent(widget, enter)
    if enter.isAccepted():
        QApplication.sendEvent(widget, QDropEvent(at, *_held(mime)))
    return enter


def brought_over(widget: QWidget, mime) -> None:
    QApplication.sendEvent(widget, QDragEnterEvent(_SPOT, *_held(mime)))
    QApplication.sendEvent(widget, QDragMoveEvent(_SPOT, *_held(mime)))


def dropped_on(widget: QWidget, mime) -> None:
    brought_over(widget, mime)
    QApplication.sendEvent(widget, QDropEvent(_SPOT, *_held(mime)))
