from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget
from shared_ui.colors import RED
from shared_ui.icons import icon_pixmap
from shared_ui.spacing import GAP_SMALL
from shared_ui.tick_control import TickControl

from origenerator.fix_switches import CHOICES, LEFT_OUT, OFF, ON, FixSwitch

PICKED = "picked"
FOUND_NOTHING = "This fix found nothing to redraw in this image"
_NOT_PICKED, _NOT_OFFERED = 0.45, 0.15
_SAID_OF_THE_ONE_PICKED = {
    ON: "This fix is on the image",
    OFF: "This fix is off the image",
    LEFT_OUT: "Re-enhance will leave this fix out. The image shows it until then.",
}
_SAID_OF_ONE_TO_PICK = {
    ON: "Put this fix on the image, and keep it when you press Re-enhance",
    OFF: "Take this fix off the image",
    LEFT_OUT: "Leave this fix out when you press Re-enhance. The image shows it until then.",
}


def _named(parts) -> str:
    *earlier, last = (part.capitalize() for part in parts)
    return f"{', '.join(earlier)} and {last}" if earlier else last


def tooltip_of(switch: FixSwitch, choice: str) -> str:
    if not switch.redrew_something:
        return FOUND_NOTHING
    if switch.choice == choice:
        return _SAID_OF_THE_ONE_PICKED[choice]
    if switch.can_be(choice):
        return _SAID_OF_ONE_TO_PICK[choice]
    held_by = _named(switch.held_by)
    if switch.on:
        were = "was" if len(switch.held_by) == 1 else "were"
        return f"{held_by} {were} drawn over part of this fix. Turn off {held_by} first."
    return f"This fix was drawn over part of {held_by}. Turn on {held_by} first."


class _TickThatStays(TickControl):
    def nextCheckState(self):
        return


class _Cross(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setPixmap(icon_pixmap("cross", TickControl().sizeHint().height(), RED))

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


def _mark_of(choice: str) -> QWidget:
    if choice == LEFT_OUT:
        return _Cross()
    tick = _TickThatStays()
    tick.setChecked(choice == ON)
    return tick


class FixChoices(QWidget):
    chosen = Signal(str)

    def __init__(self, switch: FixSwitch, parent=None):
        super().__init__(parent)
        self.setObjectName("fixChoices")
        self.setStyleSheet("#fixChoices { background: transparent; }")
        marks = QHBoxLayout(self)
        marks.setContentsMargins(0, 0, 0, 0)
        marks.setSpacing(GAP_SMALL)
        for choice in CHOICES:
            mark = _mark_of(choice)
            mark.setObjectName(f"fix {choice}")
            mark.setToolTip(tooltip_of(switch, choice))
            picked = switch.choice == choice
            mark.setProperty(PICKED, picked)
            if picked:
                mark.setEnabled(switch.redrew_something)
            elif switch.can_be(choice):
                self._dim(mark, _NOT_PICKED)
                mark.setCursor(Qt.CursorShape.PointingHandCursor)
                mark.clicked.connect(lambda _checked=False, choice=choice: self.chosen.emit(choice))
            else:
                self._dim(mark, _NOT_OFFERED)
                mark.setEnabled(False)
            marks.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)

    def _dim(self, mark: QWidget, opacity: float) -> None:
        effect = QGraphicsOpacityEffect(mark)
        effect.setOpacity(opacity)
        mark.setGraphicsEffect(effect)
