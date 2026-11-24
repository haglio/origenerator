from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedLayout, QVBoxLayout, QWidget
from shared_ui.colors import BG_PRIMARY, RED, TEXT_MUTED
from shared_ui.icons import icon_pixmap
from shared_ui.spacing import BUTTON_RADIUS, GAP_MEDIUM, GAP_SMALL
from shared_ui.tick_control import TickControl

from origenerator.fix_switches import BAD, ON, FixSwitch
from origenerator.gui.text_color import color_text

FOUND_NOTHING = "This fix found nothing to redraw in this image"
ASKS_WHETHER_BAD = "Bad?"
_MARK_AS_BAD = ("Mark this fix as bad, so that Re-enhance leaves it out. "
                "The image shows it until then.")
_MARKED_AS_BAD = ("This fix is marked as bad, so Re-enhance will leave it out. "
                  "Click to take the mark off.")
_CSS = f"#fixList {{ background-color: {BG_PRIMARY.name()}; border-radius: {BUTTON_RADIUS}px; }}"
_SEE_THROUGH = "background: transparent;"


class ListedFix(NamedTuple):
    part: str
    detail: str
    switch: FixSwitch | None = None
    tooltip: str = ""


def _named(parts) -> str:
    *earlier, last = (part.capitalize() for part in parts)
    return f"{', '.join(earlier)} and {last}" if earlier else last


def switch_tooltip(switch: FixSwitch) -> str:
    if not switch.redrew_something:
        return FOUND_NOTHING
    held_by = _named(switch.held_by) if switch.held_by else ""
    if held_by and switch.on:
        were = "was" if len(switch.held_by) == 1 else "were"
        return f"{held_by} {were} drawn over part of this fix. Turn off {held_by} first."
    if held_by:
        return f"This fix was drawn over part of {held_by}. Turn on {held_by} first."
    return ("Uncheck to take this fix off the image" if switch.on
            else "Check to put this fix back on the image")


def _box_edge() -> int:
    return TickControl().sizeHint().height()


def _kept_room_while_hidden(widget: QWidget) -> QWidget:
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)
    return widget


def _said(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_SEE_THROUGH)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return label


class _EmptyBox(TickControl):
    def nextCheckState(self):
        return


class _RedX(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPixmap(icon_pixmap("cross", _box_edge() - 4, RED))
        self.setStyleSheet(_SEE_THROUGH)

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class _BadMark(QWidget):
    asked = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("fixBadMark")
        self.setStyleSheet(f"#fixBadMark {{ {_SEE_THROUGH} }}")
        across = QHBoxLayout(self)
        across.setContentsMargins(0, 0, 0, 0)
        across.setSpacing(GAP_SMALL)
        self._asks = _kept_room_while_hidden(_said(ASKS_WHETHER_BAD))
        self._asks.setObjectName("fix bad asked")
        color_text(self._asks, TEXT_MUTED)
        across.addWidget(self._asks, 0, Qt.AlignmentFlag.AlignVCenter)
        self._marks = _kept_room_while_hidden(QWidget())
        self._marks.setFixedSize(_box_edge(), _box_edge())
        self._marks.setStyleSheet(_SEE_THROUGH)
        self._either = QStackedLayout(self._marks)
        self._box, self._x = _EmptyBox(), _RedX()
        self._box.setObjectName("fix bad box")
        self._x.setObjectName("fix bad x")
        self._box.setToolTip(_MARK_AS_BAD)
        self._x.setToolTip(_MARKED_AS_BAD)
        for mark, bad in ((self._box, True), (self._x, False)):
            mark.setCursor(Qt.CursorShape.PointingHandCursor)
            mark.clicked.connect(lambda _checked=False, bad=bad: self.asked.emit(bad))
            self._either.addWidget(mark)
        across.addWidget(self._marks, 0, Qt.AlignmentFlag.AlignVCenter)
        self._bad = self._offered = self._pointed_at = False
        self._show()

    def show_as(self, *, bad: bool, offered: bool) -> None:
        self._bad, self._offered = bad, offered
        self._show()

    def pointed_at(self, pointed_at: bool) -> None:
        self._pointed_at = pointed_at
        self._show()

    def _show(self) -> None:
        asking = self._offered and self._pointed_at and not self._bad
        self._either.setCurrentWidget(self._x if self._bad else self._box)
        self._asks.setVisible(asking)
        self._marks.setVisible(self._bad or asking)


class _FixLine(QWidget):
    changed = Signal(str, str, bool)

    def __init__(self, fix: ListedFix, name_width: int):
        super().__init__()
        self.setObjectName("fixLine")
        self.setStyleSheet(f"#fixLine {{ {_SEE_THROUGH} }}")
        self.part = fix.part
        across = QHBoxLayout(self)
        across.setContentsMargins(0, 0, 0, 0)
        across.setSpacing(GAP_MEDIUM)
        self._bad = self._switch = None
        if fix.switch is not None:
            self._bad = _BadMark()
            self._bad.asked.connect(lambda bad: self.changed.emit(self.part, BAD, bad))
            across.addWidget(self._bad, 0, Qt.AlignmentFlag.AlignVCenter)
            self._switch = TickControl(fix.part.capitalize())
            self._switch.setObjectName("fix on")
            self._switch.clicked.connect(lambda on: self.changed.emit(self.part, ON, on))
            named = self._switch
        else:
            named = _said(fix.part.capitalize())
        named.setFixedWidth(name_width)
        across.addWidget(named, 0, Qt.AlignmentFlag.AlignVCenter)
        self.named = named
        self.detail = _said(fix.detail)
        color_text(self.detail, TEXT_MUTED)
        self.setToolTip(fix.tooltip)
        across.addWidget(self.detail, 1, Qt.AlignmentFlag.AlignVCenter)
        if fix.switch is not None:
            self.show_switch(fix.switch)

    def show_switch(self, switch: FixSwitch) -> None:
        self._switch.setChecked(switch.on)
        self._switch.setEnabled(switch.can_be_switched)
        self._switch.setToolTip(switch_tooltip(switch))
        self._bad.show_as(bad=switch.bad, offered=switch.redrew_something)

    def enterEvent(self, event):
        if self._bad is not None:
            self._bad.pointed_at(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._bad is not None:
            self._bad.pointed_at(False)
        super().leaveEvent(event)


def _name_width(fixes: list[ListedFix]) -> int:
    return max(TickControl(fix.part.capitalize()).sizeHint().width() for fix in fixes)


class FixList(QWidget):
    changed = Signal(str, str, bool)

    def __init__(self, fixes: list[ListedFix], beside: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("fixList")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_CSS)
        across = QHBoxLayout(self)
        across.setContentsMargins(0, GAP_SMALL, GAP_SMALL, GAP_SMALL)
        across.setSpacing(GAP_MEDIUM)
        across.addWidget(beside, 0, Qt.AlignmentFlag.AlignTop)
        down = QVBoxLayout()
        down.setContentsMargins(0, 0, 0, 0)
        down.setSpacing(GAP_SMALL)
        width = _name_width(fixes)
        self._lines = [_FixLine(fix, width) for fix in fixes]
        for line in self._lines:
            line.changed.connect(self.changed)
            down.addWidget(line)
        across.addLayout(down, 1)

    def lines(self) -> list[_FixLine]:
        return list(self._lines)

    def show_switches(self, switches: list[FixSwitch]) -> None:
        by_part = {switch.part: switch for switch in switches}
        for line in self._lines:
            if line.part in by_part:
                line.show_switch(by_part[line.part])
