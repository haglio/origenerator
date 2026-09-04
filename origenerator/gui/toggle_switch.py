"""A plain on/off switch: a pill with a knob that slides across.

Used where a setting is a standing state rather than a thing you tick as part
of filling in a form — the Enhance panel's auto-enhance, which is either running
or not. Reads at a glance from across the pane, which a checkbox in a column of
other fields does not.

Usually built bare, sitting at the corner of the panel it powers; the optional
label is for a switch that has to say what it is on its own.

Painted rather than styled, because a Qt stylesheet cannot move a checkbox's
indicator; the colors are the suite's shared toggle tokens, so it looks like the
switches Fun Time and the other apps draw.
"""

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (  # noqa: E402
    TEXT_SECONDARY,
    TOGGLE_KNOB,
    TOGGLE_OFF,
    TOGGLE_ON,
)

_TRACK = QSize(38, 20)   # the pill
_KNOB_INSET = 3          # gap between the knob and the track's edge
_GAP = 8                 # between the pill and its label
_DISABLED_OPACITY = 0.4  # how far a switch fades when it can't be thrown


class ToggleSwitch(QAbstractButton):
    """A checkable switch, optionally labeled to its right.

    Behaves like any checkable button — ``isChecked``, ``setChecked``,
    ``toggled`` — so it drops in wherever a checkbox was.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        width = _TRACK.width()
        if self.text():
            width += _GAP + self.fontMetrics().horizontalAdvance(self.text())
        return QSize(width, max(_TRACK.height(), self.fontMetrics().height()))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            # Painted rather than styled, so nothing else would have dimmed it:
            # a disabled switch drawn at full strength reads as a live one, and
            # the panel it powers goes dark around a switch that still looks on.
            painter.setOpacity(_DISABLED_OPACITY)
        top = (self.height() - _TRACK.height()) / 2
        track = QRectF(0, top, _TRACK.width(), _TRACK.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(TOGGLE_ON if self.isChecked() else TOGGLE_OFF)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        diameter = track.height() - 2 * _KNOB_INSET
        x = (track.right() - _KNOB_INSET - diameter if self.isChecked()
             else track.left() + _KNOB_INSET)
        painter.setBrush(TOGGLE_KNOB)
        painter.drawEllipse(QRectF(x, track.top() + _KNOB_INSET, diameter, diameter))

        if self.text():
            painter.setPen(QPen(TEXT_SECONDARY))
            painter.drawText(
                QRectF(track.right() + _GAP, 0,
                       self.width() - track.right() - _GAP, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self.text(),
            )
        painter.end()
