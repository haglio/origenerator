from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget
from shared_ui.asking import yes_or_no


def placed_at(point: QPoint, size: QSize, area: QRect) -> QPoint:
    left = point.x() - size.width() // 2
    top = point.y() - size.height() // 2
    left = max(area.left(), min(left, area.right() + 1 - size.width()))
    top = max(area.top(), min(top, area.bottom() + 1 - size.height()))
    return QPoint(left, top)


class _PlacedWhenShown(QObject):
    def __init__(self, box: QWidget, point: QPoint) -> None:
        super().__init__(box)
        self._point = point
        box.installEventFilter(self)

    def eventFilter(self, box, event) -> bool:
        if event.type() == QEvent.Type.ShowToParent:
            screen = QGuiApplication.screenAt(self._point) or box.screen()
            box.move(placed_at(self._point, box.frameGeometry().size(),
                               screen.availableGeometry()))
        return False


def asked_at(point: QPoint, over: QWidget, title: str, question: str) -> bool:
    box = yes_or_no(over, title, question)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    _PlacedWhenShown(box, point)
    return box.exec() == QMessageBox.StandardButton.Yes
