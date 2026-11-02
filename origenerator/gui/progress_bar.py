from __future__ import annotations

from PyQt6.QtCore import QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QFontMetrics, QPainterPath
from PyQt6.QtWidgets import (
    QProgressBar,
    QStyle,
    QStyleOptionProgressBar,
    QStylePainter,
)
from shared_ui.colors import BG_PRIMARY, BLUE_LIGHT
from shared_ui.spacing import BUTTON_RADIUS, GAP_DIALOG, GAP_MEDIUM

_TEXT_MARGIN = GAP_MEDIUM
_SCROLL_MS = 33
_SCROLL_PX = 1.0
_SCROLL_GAP = GAP_DIALOG
_HOLD_TICKS = 45
_SUBSTEP_BAR_PX = 6
_SUBSTEP_BAR_RADIUS = BUTTON_RADIUS
_SUBSTEP_BAR_TROUGH = BG_PRIMARY
_SUBSTEP_BAR_FILL = BLUE_LIGHT


BAR_HEIGHT = 26


class ProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("progressBar")
        self.setTextVisible(True)
        self._caption = ""
        self._pass_progress: tuple[int, int] | None = None
        self._scrolled = 0.0
        self._hold = 0
        self._scroll = QTimer(self)
        self._scroll.setInterval(_SCROLL_MS)
        self._scroll.timeout.connect(self._advance)

    def text(self) -> str:
        return self._caption

    def caption(self) -> str:
        return self._caption

    def scrolling(self) -> bool:
        return QFontMetrics(self.font()).horizontalAdvance(self._caption) > self._room()

    def scrolled(self) -> float:
        return self._scrolled

    def _room(self) -> int:
        return max(0, self.width() - _TEXT_MARGIN)

    def pass_progress(self) -> tuple[int, int] | None:
        return self._pass_progress

    def show_progress(self, caption: str, progress: tuple[int, int] | None,
                      pass_progress: tuple[int, int] | None = None):
        self._caption = caption
        self._pass_progress = pass_progress
        if progress and progress[1] > 0:
            self.setRange(0, progress[1])
            self.setValue(progress[0])
        else:
            self.setRange(0, 0)
        self._retime_scroll()
        self.update()

    def _retime_scroll(self) -> None:
        if self.scrolling() and self.isVisible():
            if not self._scroll.isActive():
                self._scrolled, self._hold = 0.0, _HOLD_TICKS
                self._scroll.start()
        elif self._scroll.isActive():
            self._scroll.stop()
            self._scrolled = 0.0

    def _advance(self) -> None:
        if self._hold > 0:
            self._hold -= 1
            return
        self._scrolled += _SCROLL_PX
        if self._scrolled >= self._lap():
            self._scrolled, self._hold = 0.0, _HOLD_TICKS
        self.update()

    def _lap(self) -> float:
        return QFontMetrics(self.font()).horizontalAdvance(self._caption) + _SCROLL_GAP

    def showEvent(self, event):
        super().showEvent(event)
        self._retime_scroll()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._scroll.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._retime_scroll()

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionProgressBar()
        self.initStyleOption(option)
        caption, option.text = option.text, ""
        option.textVisible = False
        painter.drawControl(QStyle.ControlElement.CE_ProgressBar, option)
        self._paint_substep_bar(painter)
        if self.isTextVisible() and caption:
            self._paint_caption(painter, caption)

    def _paint_caption(self, painter, caption: str) -> None:
        if not self.scrolling():
            painter.drawItemText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                                 self.palette(), self.isEnabled(), caption,
                                 self.foregroundRole())
            return
        painter.save()
        painter.setClipRect(self.rect())
        lap = self._lap()
        left = _TEXT_MARGIN / 2 - self.scrolled()
        for start in (left, left + lap):
            painter.drawItemText(
                QRect(round(start), 0, round(lap), self.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.palette(), self.isEnabled(), caption, self.foregroundRole(),
            )
        painter.restore()

    def _paint_substep_bar(self, painter):
        if self._pass_progress is None or self.maximum() <= 0:
            return
        done, total = self._pass_progress
        if total <= 0:
            return
        inner = self.rect().adjusted(1, 1, -1, -1)
        if inner.height() <= _SUBSTEP_BAR_PX or inner.width() <= 0:
            return
        painter.save()
        rounded_inside = QPainterPath()
        rounded_inside.addRoundedRect(QRectF(inner), _SUBSTEP_BAR_RADIUS, _SUBSTEP_BAR_RADIUS)
        painter.setClipPath(rounded_inside)
        substep = QRect(inner.x(), inner.bottomLeft().y() - _SUBSTEP_BAR_PX + 1,
                        inner.width(), _SUBSTEP_BAR_PX)
        painter.fillRect(substep, _SUBSTEP_BAR_TROUGH)
        filled = round(substep.width() * min(done, total) / total)
        if filled > 0:
            painter.fillRect(QRect(substep.x(), substep.y(), filled, substep.height()),
                             _SUBSTEP_BAR_FILL)
        painter.restore()
