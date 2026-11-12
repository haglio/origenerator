from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
from shared_ui.colors import BG_SECONDARY, BLUE, BORDER_PANEL, TEXT_PRIMARY
from shared_ui.spacing import BUTTON_RADIUS, GAP_SMALL, MARGIN_STANDARD


def link(href: str, text: str) -> str:
    return f'<a href="{href}" style="color: {BLUE.name()};">{text}</a>'

_APPEAR_MS = 500
_LINGER_MS = 400
_GAP = GAP_SMALL


class LinkTip(QObject):
    link_activated = Signal(str)

    def __init__(self, widget, parent=None):
        super().__init__(parent or widget)
        self._widget = widget
        self._html = ""
        self._popup = _TipPopup()
        self.destroyed.connect(self._popup.deleteLater)
        self._popup.label.linkActivated.connect(self._on_link)
        self._popup.entered.connect(self._cancel_hide)
        self._popup.left.connect(self._start_hide)
        self._appear = QTimer(self)
        self._appear.setSingleShot(True)
        self._appear.setInterval(_APPEAR_MS)
        self._appear.timeout.connect(self._show)
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.setInterval(_LINGER_MS)
        self._hide.timeout.connect(self.hide)
        widget.installEventFilter(self)

    def set_html(self, html: str):
        self._html = html or ""
        if not self._html:
            self.hide()
        elif self._popup.isVisible():
            self._popup.label.setText(self._html)
            self._popup.adjustSize()

    def hide(self):
        self._appear.stop()
        self._hide.stop()
        self._popup.hide()

    def eventFilter(self, obj, event):
        if obj is self._widget:
            if event.type() == QEvent.Type.Enter:
                self._cancel_hide()
                if self._html and not self._popup.isVisible():
                    self._appear.start()
            elif event.type() == QEvent.Type.Leave:
                self._appear.stop()
                self._start_hide()
            elif event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
                self.hide()
        return False

    def _show(self):
        if not self._html:
            return
        self._popup.label.setText(self._html)
        self._popup.adjustSize()
        below = self._widget.rect().bottomLeft()
        self._popup.move(self._widget.mapToGlobal(below) + self._popup.offset())
        self._popup.show()

    def _start_hide(self):
        if self._popup.isVisible():
            self._hide.start()

    def _cancel_hide(self):
        self._hide.stop()

    def _on_link(self, href: str):
        self.hide()
        self.link_activated.emit(href)


class _TipPopup(QFrame):
    entered = Signal()
    left = Signal()

    def __init__(self):
        # Qt: the ToolTip window type is frameless and focus-free yet, unlike QToolTip's window, receives the mouse.
        super().__init__(None, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            f"QFrame {{ background-color: {BG_SECONDARY.name()};"
            f" border: 1px solid {BORDER_PANEL.name()}; border-radius: {BUTTON_RADIUS}px; }}"
            f" QLabel {{ color: {TEXT_PRIMARY.name()}; border: none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, GAP_SMALL, MARGIN_STANDARD, GAP_SMALL)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.label.setOpenExternalLinks(False)
        layout.addWidget(self.label)

    def offset(self):
        return QPoint(0, _GAP)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.entered.emit()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.left.emit()
