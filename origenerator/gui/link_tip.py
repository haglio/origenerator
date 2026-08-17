"""A tooltip you can click into.

Qt's own tooltip is a picture of some text: its window is transparent to the
mouse and vanishes the moment the pointer moves toward it, so a link inside one
can be drawn but never followed. Where the useful thing to say about a control is
"it is happening over there", that is exactly the wrong tooltip — naming the
place is no help when the names are long and alike, and the answer the user wants
is to be taken there.

So this is a small popup that behaves like a tooltip and accepts a click: it
appears under the widget it watches after the usual pause, stays while the
pointer is over either of them, and emits :attr:`link_activated` with the href of
whatever link was clicked. It closes on the way out of both, on a click of the
watched widget, and whenever its text is taken away.

One tip per watched widget, set with :meth:`set_html` — empty html turns it off,
which is the state a control is in when it has nothing but ordinary text to say
(that stays with Qt's tooltip, which handles the ordinary case perfectly well).
"""

from PyQt6.QtCore import QEvent, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BG_SECONDARY, BLUE, BORDER_PANEL, TEXT_PRIMARY


def link(href: str, text: str) -> str:
    """One link for a tip's html, colored so it reads as one.

    Qt's default anchor color is the desktop's, which against this app's dark
    panels can come out all but unreadable — and a link nobody sees is the same
    as no link.
    """
    return f'<a href="{href}" style="color: {BLUE.name()};">{text}</a>'

# The pause before it appears, near enough Qt's own that the two don't feel like
# different mechanisms on neighboring buttons.
_APPEAR_MS = 500
# How long it survives the pointer leaving, so the pointer can cross the gap onto
# the tip to click its link. Qt's tooltip needs no such grace, being unclickable.
_LINGER_MS = 400
# The gap under the watched widget, wide enough that the pointer travelling down
# to the tip doesn't leave the widget before the tip is under it.
_GAP = 2


class LinkTip(QObject):
    """Watches one widget and shows a clickable tip beneath it."""

    link_activated = pyqtSignal(str)  # the href of the link that was clicked

    def __init__(self, widget, parent=None):
        super().__init__(parent or widget)
        self._widget = widget
        self._html = ""
        self._popup = _TipPopup()
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
        """What the tip says, as rich text — ``""`` to have no tip at all.

        Taking the text away closes an open one: the reason it was worth clicking
        into (a loop running elsewhere, say) has ended, and a stale offer to go
        somewhere is worse than none.
        """
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
                # The click has done whatever the tip was offering to explain, and
                # what it says next is decided by the click's own outcome.
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
    """The popup itself: a tooltip-shaped frame that reports its own hovering."""

    entered = pyqtSignal()
    left = pyqtSignal()

    def __init__(self):
        # The ToolTip window type keeps it frameless and focus-free, but unlike
        # QToolTip's own window it still receives the mouse — which is the whole
        # point of the thing.
        super().__init__(None, Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            f"QFrame {{ background-color: {BG_SECONDARY.name()};"
            f" border: 1px solid {BORDER_PANEL.name()}; border-radius: 4px; }}"
            f" QLabel {{ color: {TEXT_PRIMARY.name()}; border: none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        # Links only: selecting the text would swallow the click that follows one.
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.label.setOpenExternalLinks(False)  # the href is ours to act on
        layout.addWidget(self.label)

    def offset(self):
        from PyQt6.QtCore import QPoint
        return QPoint(0, _GAP)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.entered.emit()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.left.emit()
