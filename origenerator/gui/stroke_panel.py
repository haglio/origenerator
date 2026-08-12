"""Genau's drive readout, copied — the stroke being sent, drawn and pressable.

This is genau's ``drive_hud`` block, reproduced control for control so the two
apps read as one device surface: the trace of the stroke in the middle (blue
while live, grey while not), Center down the left — its number, then a −/+ pair
riding the dotted line it moves — Amplitude down the right — a −/+ pair at the
ends of its bar, then its number — and Speed under the trace with its own −/+
and number. The marks step an axis; each band is the picture of its own value,
so a press in one asks for the value drawn under the pointer and a held button
keeps asking as it moves (genau's ``tracks`` behavior, same math).

One mark genau doesn't have: the power square at the top-left corner. Genau's
engine is toggled from its own console; origenerator's has no console, so the
panel itself carries the on/off — the same square the other marks are drawn as,
▶ to take the device and ■ to park it (Space still does the same).

The geometry and hit-testing live in pure functions mirroring genau's, so the
widget is a thin painter over testable layout.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer

from origenerator import stroke_engine
from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BLUE, TEXT_MUTED, TEXT_PRIMARY

Rect = tuple[int, int, int, int]  # (x, y, w, h)

# Genau's drive_hud dimensions, kept verbatim so the copy is the original.
_LABEL_H = 14
_BAR_H = 12
_CTRL = 14
_GAP = 6
_AMP_W = 18
_WAVE_H = 96
_CTR_LABEL_W = 34
_AMP_LABEL_W = 24
_WAVE_W = 120
_TRACK = QColor(56, 56, 62)  # the unfilled part of a bar

SECTION_W = _CTR_LABEL_W + _GAP + _CTRL + _GAP + _WAVE_W + _GAP + _AMP_W + _GAP + _AMP_LABEL_W
SECTION_H = _WAVE_H + _GAP + _CTRL + 2 + _LABEL_H

_PAD = 10          # the slab's breathing room around the block
_TRACE_SAMPLES = 80
_TRACE_SECONDS = 12.0
_LESS, _MORE = "−", "+"
_REPAINT_MS = 100  # the trace scrolls with the phase while the panel shows

AMPLITUDE, CENTER, SPEED, POWER = "amp", "center", "speed", "power"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _percent(fraction: float) -> int:
    return round(_clamp01(fraction) * 100)


@dataclass(frozen=True)
class PanelControl:
    rect: Rect
    action: str
    glyph: str
    dim: bool


@dataclass(frozen=True)
class PanelTrack:
    """A band that takes its value from where you press in it (genau's
    ``DriveTrack``): along the speed bar for the rate, up the amplitude bar for
    the reach, anywhere in the trace for the height the stroke swings about."""

    rect: Rect
    axis: str
    center: float


@dataclass(frozen=True)
class _Geometry:
    wave: Rect
    speed_bar: Rect
    speed_down: Rect
    speed_up: Rect
    amp_bar: Rect
    amp_up: Rect
    amp_down: Rect
    center_up: Rect
    center_down: Rect
    power: Rect
    center_label_right: int
    amp_label_left: int
    axis_label_y: int
    speed_label_y: int
    speed_label_x: int


def geometry(x: int, y: int, center_frac: float) -> _Geometry:
    """Every rect the panel draws or hit-tests — genau's ``_geometry``, plus the
    power square in the top-left corner."""
    ctr_ctrl_x = x + _CTR_LABEL_W + _GAP
    wave_x = ctr_ctrl_x + _CTRL + _GAP
    amp_x = wave_x + _WAVE_W + _GAP
    wave = (wave_x, y, _WAVE_W, _WAVE_H)
    wave_bottom = y + _WAVE_H

    amp_up = (amp_x, y, _AMP_W, _CTRL)
    amp_down = (amp_x, wave_bottom - _CTRL, _AMP_W, _CTRL)
    amp_bar = (amp_x, y + _CTRL + 2, _AMP_W, _WAVE_H - 2 * (_CTRL + 2))

    center_y = y + round((1 - center_frac) * (_WAVE_H - 1))
    up_y = min(max(y, center_y - _CTRL - 1), wave_bottom - 2 * _CTRL - 2)
    center_up = (ctr_ctrl_x, up_y, _CTRL, _CTRL)
    center_down = (ctr_ctrl_x, up_y + _CTRL + 2, _CTRL, _CTRL)

    speed_y = wave_bottom + _GAP
    speed_down = (wave_x, speed_y, _CTRL, _CTRL)
    speed_up = (amp_x + _AMP_W - _CTRL, speed_y, _CTRL, _CTRL)
    bar_x = wave_x + _CTRL + 4
    speed_bar = (bar_x, speed_y + (_CTRL - _BAR_H) // 2,
                 (amp_x + _AMP_W - _CTRL - 4) - bar_x, _BAR_H)

    return _Geometry(
        wave=wave, speed_bar=speed_bar, speed_down=speed_down, speed_up=speed_up,
        amp_bar=amp_bar, amp_up=amp_up, amp_down=amp_down,
        center_up=center_up, center_down=center_down,
        power=(x, y, _CTRL, _CTRL),
        center_label_right=x + _CTR_LABEL_W,
        amp_label_left=amp_x + _AMP_W + _GAP,
        axis_label_y=y + (_WAVE_H - 2 * _LABEL_H) // 2,
        speed_label_y=speed_y + _CTRL + 2,
        speed_label_x=(wave_x + amp_x + _AMP_W) // 2,
    )


def controls(x: int, y: int, state: stroke_engine.StrokeState,
             active: bool) -> list[PanelControl]:
    """The panel's marks: genau's −/+ pair per axis (dimmed at the end of its
    range), plus the power square (▶ off, ■ driving)."""
    g = geometry(x, y, state.center / 100)
    return [
        PanelControl(g.power, POWER, "■" if active else "▶", False),
        PanelControl(g.speed_down, "speed_down", _LESS, state.speed <= stroke_engine.MIN_SPEED),
        PanelControl(g.speed_up, "speed_up", _MORE, state.speed >= stroke_engine.MAX_SPEED),
        PanelControl(g.amp_up, "amp_up", _MORE, state.amplitude >= 100),
        PanelControl(g.amp_down, "amp_down", _LESS, state.amplitude <= 0),
        PanelControl(g.center_up, "center_up", _MORE, state.center >= 100 - state.amplitude // 2),
        PanelControl(g.center_down, "center_down", _LESS, state.center <= state.amplitude // 2),
    ]


def tracks(x: int, y: int, state: stroke_engine.StrokeState) -> list[PanelTrack]:
    center = state.center / 100
    g = geometry(x, y, center)
    return [
        PanelTrack(g.amp_bar, AMPLITUDE, center),
        PanelTrack(g.wave, CENTER, center),
        PanelTrack(g.speed_bar, SPEED, center),
    ]


def track_value(track: PanelTrack, px: int, py: int) -> int:
    """The 0-100 level a press at ``(px, py)`` asks for — genau's math: along
    the speed bar, the height of the trace for center, and the reach out from
    the center for amplitude."""
    x, y, w, h = track.rect
    if track.axis == SPEED:
        return _percent((px - x) / max(1, w - 1))
    height = _clamp01(1 - (py - y) / max(1, h - 1))
    if track.axis == CENTER:
        return _percent(height)
    return _percent(2 * abs(height - track.center))


def _hit(rect: Rect, px: int, py: int) -> bool:
    x, y, w, h = rect
    return x <= px < x + w and y <= py < y + h


class StrokePanel(QWidget):
    """The pressable drive readout, floated over whichever surface hosts it."""

    def __init__(self, stroke, parent=None):
        super().__init__(parent)
        self._stroke = stroke
        self._drag_track: PanelTrack | None = None
        self.setFixedSize(SECTION_W + 2 * _PAD, SECTION_H + 2 * _PAD)
        self.setToolTip(f"OSR2 stroke — {STROKE_KEY_LEGEND}")
        # The trace scrolls with the phase, so repaint on a beat while shown.
        self._repaint = QTimer(self)
        self._repaint.setInterval(_REPAINT_MS)
        self._repaint.timeout.connect(self.update)

    def refresh(self) -> None:
        self.update()

    def reposition(self) -> None:
        """Top-center of the parent — where the fullscreen views float it."""
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(0, (parent.width() - self.width()) // 2), 16)

    def showEvent(self, event):
        super().showEvent(event)
        self._repaint.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._repaint.stop()

    # --- presses: marks step, bands set, power toggles ---------------------

    def mousePressEvent(self, event):
        px, py = int(event.position().x()), int(event.position().y())
        state = self._stroke.state
        for control in controls(_PAD, _PAD, state, self._stroke.active):
            if _hit(control.rect, px, py):
                self._act(control.action)
                self.update()
                return
        for track in tracks(_PAD, _PAD, state):
            if _hit(track.rect, px, py):
                self._drag_track = track
                self._set_from_track(track, px, py)
                return

    def mouseMoveEvent(self, event):
        if self._drag_track is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_track(self._drag_track, int(event.position().x()),
                                 int(event.position().y()))

    def mouseReleaseEvent(self, event):
        self._drag_track = None

    def _act(self, action: str) -> None:
        stroke = self._stroke
        if action == POWER:
            stroke.toggle()
        elif action == "speed_down":
            stroke.adjust_speed(-5)
        elif action == "speed_up":
            stroke.adjust_speed(5)
        elif action == "amp_up":
            stroke.adjust_amplitude(10)
        elif action == "amp_down":
            stroke.adjust_amplitude(-10)
        elif action == "center_up":
            stroke.adjust_center(5)
        elif action == "center_down":
            stroke.adjust_center(-5)

    def _set_from_track(self, track: PanelTrack, px: int, py: int) -> None:
        value = track_value(track, px, py)
        if track.axis == SPEED:
            self._stroke.set_speed(value)
        elif track.axis == CENTER:
            self._stroke.set_center(value)
        else:
            self._stroke.set_amplitude(value)
        self.update()

    # --- painting ----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 225))
        painter.drawRoundedRect(self.rect(), 6, 6)

        state = self._stroke.state
        live = self._stroke.active
        # Blue is the stroke's own color while it reaches the device; everything
        # goes the muted grey of a dead control while nothing is being sent.
        level_ink = QColor(BLUE) if live else QColor(TEXT_MUTED)
        value_ink = QColor(TEXT_PRIMARY) if live else QColor(TEXT_MUTED)
        g = geometry(_PAD, _PAD, state.center / 100)

        self._wave(painter, g.wave, state, level_ink)
        self._amp_bar(painter, g.amp_bar, state, level_ink)
        self._bar(painter, g.speed_bar,
                  (state.speed - stroke_engine.MIN_SPEED)
                  / (stroke_engine.MAX_SPEED - stroke_engine.MIN_SPEED), level_ink)
        for control in controls(_PAD, _PAD, state, live):
            self._control(painter, control)

        tiny = painter.font()
        tiny.setPointSize(7)
        painter.setFont(tiny)
        self._stacked(painter, g.axis_label_y, "Center", str(state.center),
                      right=g.center_label_right, ink=value_ink)
        self._stacked(painter, g.axis_label_y, "Amp", str(state.amplitude),
                      left=g.amp_label_left, ink=value_ink)
        self._speed_label(painter, g.speed_label_y, g.speed_label_x,
                          str(state.speed), ink=value_ink)
        painter.end()

    def _wave(self, painter: QPainter, rect: Rect, state, ink: QColor) -> None:
        x, y, w, h = rect
        painter.setPen(QPen(QColor(TEXT_MUTED), 1))
        painter.setBrush(_TRACK)
        painter.drawRect(x, y, w - 1, h - 1)
        # The center's dotted ruler — the height the stroke swings about.
        dotted = QPen(QColor(TEXT_MUTED), 1, Qt.PenStyle.DotLine)
        painter.setPen(dotted)
        center_y = y + round((1 - state.center / 100) * (h - 1))
        painter.drawLine(x + 2, center_y, x + w - 3, center_y)
        # The stroke itself, sampled forward from now.
        samples = stroke_engine.trace(state, _TRACE_SAMPLES, _TRACE_SECONDS)
        painter.setPen(QPen(ink, 2))
        points = [
            QPointF(x + i * (w - 1) / (len(samples) - 1), y + (1 - value) * (h - 1))
            for i, value in enumerate(samples)
        ]
        for start, end in zip(points, points[1:]):
            painter.drawLine(start, end)
        # The device's position now, ticked down the left edge.
        pos_y = y + round((1 - stroke_engine.position(state) / 100) * (h - 1))
        painter.setPen(QPen(ink, 3))
        painter.drawLine(x, pos_y, x + 5, pos_y)

    def _amp_bar(self, painter: QPainter, rect: Rect, state, ink: QColor) -> None:
        """Genau's amplitude bar: drawn out from the center in both directions,
        so the blue span is exactly the heights the stroke reaches."""
        x, y, w, h = rect
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_TRACK)
        painter.drawRect(x, y, w, h)
        half = state.amplitude / 200  # amplitude% of the axis, as a 0-1 half-span
        center = state.center / 100
        top = y + round((1 - min(1.0, center + half)) * (h - 1))
        bottom = y + round((1 - max(0.0, center - half)) * (h - 1))
        painter.setBrush(ink)
        painter.drawRect(x, top, w, max(1, bottom - top))

    def _bar(self, painter: QPainter, rect: Rect, fill: float, ink: QColor) -> None:
        x, y, w, h = rect
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_TRACK)
        painter.drawRect(x, y, w, h)
        painter.setBrush(ink)
        painter.drawRect(x, y, max(1, round(_clamp01(fill) * w)), h)

    def _control(self, painter: QPainter, control: PanelControl) -> None:
        x, y, w, h = control.rect
        ink = QColor(TEXT_MUTED) if control.dim else QColor(TEXT_PRIMARY)
        painter.setPen(QPen(ink, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(x, y, w - 1, h - 1, 3, 3)
        painter.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, control.glyph)

    def _stacked(self, painter: QPainter, y: int, key: str, value: str, *,
                 left: int | None = None, right: int | None = None,
                 ink: QColor) -> None:
        metrics = painter.fontMetrics()
        for line_no, (text, text_ink) in enumerate(
                ((key, QColor(TEXT_MUTED)), (value, ink))):
            x = left if left is not None else (right or 0) - metrics.horizontalAdvance(text)
            painter.setPen(text_ink)
            painter.drawText(QRectF(x, y + line_no * _LABEL_H, 60, _LABEL_H),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    def _speed_label(self, painter: QPainter, y: int, center_x: int, value: str,
                     *, ink: QColor) -> None:
        metrics = painter.fontMetrics()
        key = "Speed"
        span = metrics.horizontalAdvance(key) + 6 + metrics.horizontalAdvance(value)
        key_x = center_x - span // 2
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(QRectF(key_x, y, 60, _LABEL_H),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, key)
        painter.setPen(ink)
        painter.drawText(
            QRectF(key_x + metrics.horizontalAdvance(key) + 6, y, 40, _LABEL_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
