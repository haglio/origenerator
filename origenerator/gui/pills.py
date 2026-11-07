from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QFrame, QToolButton, QWidget
from shared_ui.colors import (
    BG_BUTTON,
    BG_PRIMARY,
    BG_SECONDARY,
    BORDER_DEFAULT,
    BORDER_SUBTLE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    hovered,
)
from shared_ui.icons import qt_icon
from shared_ui.spacing import (
    BUTTON_ICON,
    BUTTON_ICON_INSET,
    BUTTON_PAD_H_TIGHT,
    BUTTON_PAD_V,
    GAP_SMALL,
    HAIRLINE,
    MARGIN_STANDARD,
)

from origenerator.gui.flow_layout import FlowLayout

_X = BUTTON_ICON
_X_INK = BUTTON_ICON - 2 * BUTTON_ICON_INSET
_NO_PADDING = "padding: 0px;"
_BARE = f"border: none; background: transparent; {_NO_PADDING}"


def _height(metrics) -> int:
    return max(metrics.height(), _X) + BUTTON_PAD_V


def _round(side: int) -> str:
    return (f"border: {HAIRLINE}px solid {BORDER_DEFAULT.name()}; border-radius: {side // 2}px;"
            f" {_NO_PADDING}")


class Pill(QWidget):
    removed = pyqtSignal(str)
    picked = pyqtSignal(str)

    def __init__(self, text: str, *, removable: bool = False, pickable: bool = False, parent=None):
        super().__init__(parent)
        self._text = text
        self._pickable = pickable
        self._hovered = False
        self._remove = None
        if removable:
            self._remove = QToolButton(self)
            self._remove.setIcon(qt_icon("cross", color=TEXT_SECONDARY))
            self._remove.setIconSize(QSize(_X_INK, _X_INK))
            self._remove.setFixedSize(_X, _X)
            self._remove.setStyleSheet(_BARE)
            self._remove.setCursor(Qt.CursorShape.PointingHandCursor)
            self._remove.setToolTip(f"Remove {text}")
            self._remove.clicked.connect(lambda: self.removed.emit(self._text))
        if pickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f"Add {text}")
        self.setSizePolicy(self.sizePolicy().Policy.Fixed, self.sizePolicy().Policy.Fixed)

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        after = GAP_SMALL + _X + GAP_SMALL if self._remove is not None else BUTTON_PAD_H_TIGHT
        return QSize(BUTTON_PAD_H_TIGHT + metrics.horizontalAdvance(self._text) + after, _height(metrics))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._remove is not None:
            self._remove.move(self.width() - GAP_SMALL - _X, (self.height() - _X) // 2)

    def enterEvent(self, event) -> None:
        self._hovered = self._pickable
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (self._pickable and event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.picked.emit(self._text)
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        enabled = self.isEnabled()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        edge = QRectF(self.rect()).adjusted(HAIRLINE / 2, HAIRLINE / 2, -HAIRLINE / 2, -HAIRLINE / 2)
        ground = BG_BUTTON if enabled else BG_SECONDARY
        painter.setPen(QPen(BORDER_SUBTLE, HAIRLINE))
        painter.setBrush(hovered(ground) if self._hovered else ground)
        painter.drawRoundedRect(edge, edge.height() / 2, edge.height() / 2)
        painter.setPen(TEXT_PRIMARY if enabled else TEXT_MUTED)
        words = QRectF(BUTTON_PAD_H_TIGHT, 0, self.fontMetrics().horizontalAdvance(self._text) + HAIRLINE,
                       self.height())
        painter.drawText(words, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        painter.end()


class _Offer(QFrame):
    def __init__(self, names: tuple[str, ...], width: int, picked, parent: QWidget):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("pillOffer")
        self.setStyleSheet(f"#pillOffer {{ background: {BG_PRIMARY.name()}; "
                           f"border: {HAIRLINE}px solid {BORDER_DEFAULT.name()}; }}")
        flow = FlowLayout(self, margin=MARGIN_STANDARD, spacing=GAP_SMALL)
        for name in names:
            pill = Pill(name, pickable=True)
            pill.picked.connect(lambda chosen: (self.close(), picked(chosen)))
            flow.addWidget(pill)
        self.setFixedSize(width, flow.heightForWidth(width))


class PillRow(QWidget):
    changed = pyqtSignal(tuple)

    def __init__(self, offered: tuple[str, ...], *, adder_name: str, parent=None):
        super().__init__(parent)
        self._offered = offered
        self._names: tuple[str, ...] = ()
        self._editable = True
        self._flow = FlowLayout(self, spacing=GAP_SMALL)
        self._adder = QToolButton(objectName=adder_name)
        self._adder.setIcon(qt_icon("plus", color=TEXT_SECONDARY))
        self._adder.setIconSize(QSize(_X_INK, _X_INK))
        side = _height(self.fontMetrics())
        self._adder.setFixedSize(side, side)
        self._adder.setStyleSheet(_round(side))
        self._adder.setCursor(Qt.CursorShape.PointingHandCursor)
        self._adder.setToolTip("Add an action")
        self._adder.clicked.connect(self._offer)
        self._flow.addWidget(self._adder)

    def names(self) -> tuple[str, ...]:
        return self._names

    def show_names(self, names: tuple[str, ...], *, editable: bool) -> None:
        self._names = names
        self._editable = editable
        while self._flow.count():
            held = self._flow.takeAt(0).widget()
            if held is not self._adder:
                held.setParent(None)
                held.deleteLater()
        for name in names:
            pill = Pill(name, removable=editable, parent=self)
            pill.removed.connect(self._remove)
            self._flow.addWidget(pill)
        self._flow.addWidget(self._adder)
        self._adder.setVisible(editable and bool(self._remaining()))
        self.updateGeometry()

    def _remaining(self) -> tuple[str, ...]:
        return tuple(name for name in self._offered if name not in self._names)

    def _remove(self, name: str) -> None:
        self._set(tuple(held for held in self._names if held != name))

    def _add(self, name: str) -> None:
        self._set((*self._names, name))

    def _set(self, names: tuple[str, ...]) -> None:
        self.show_names(names, editable=self._editable)
        self.changed.emit(names)

    def _offer(self) -> None:
        offer = _Offer(self._remaining(), max(self.width(), self._adder.width()), self._add, self)
        offer.move(self._adder.mapToGlobal(QPoint(0, self._adder.height())))
        offer.show()
