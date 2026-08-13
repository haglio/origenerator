"""Genau's drive readout, drawn in Qt — the stroke being sent, and pressable.

Where the parts sit and what a press on one asks for is
:mod:`player_core.drive_layout`, which genau's own readout is drawn from too:
the trace of the stroke in the middle (blue while live, grey while not), Center
down the left — its number, then a −/+ pair riding the dotted line it moves —
Amplitude down the right, and Speed under the trace. This module is the painter
over that layout, and nothing else. Genau paints the same rects with Pillow into
an mpv overlay; this paints them with QPainter into a widget floated over a
slideshow.

Under the block sits the row genau keeps in Fun Time's console rather than in
the readout: cruise control, which varies the stroke hands-free, and the
waveform, which cycles through the shapes. There is no console here to put them
in, and a readout missing them is a readout of half the stroke.

The on/off switch is not here. It is a button in the window's own toolbar, and
this panel is what appears once it is pressed.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer

from origenerator import stroke_engine
from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND
from origenerator.paths import ensure_player_core_on_path, ensure_shared_ui_on_path

ensure_shared_ui_on_path()
ensure_player_core_on_path()

from player_core import drive_layout  # noqa: E402
from player_core.drive_layout import (  # noqa: E402
    AMPLITUDE, CENTER, SECTION_H, SECTION_W, SPEED, DriveControl, DriveTrack,
    Rect, clamp01, geometry, hit, track_value,
)
from shared_ui.colors import BLUE, TEXT_MUTED, TEXT_PRIMARY  # noqa: E402

_TRACK = QColor(56, 56, 62)  # the unfilled part of a bar

_PAD = 10          # the slab's breathing room around the block
_TRACE_SAMPLES = drive_layout.TRACE_SAMPLES
_TRACE_SECONDS = 12.0
_REPAINT_MS = 100  # the trace scrolls with the phase while the panel shows

# The row under the block: cruise control and the waveform.
CRUISE, SHAPE = "cruise", "shape"
_ROW_H = drive_layout.GAP + drive_layout.CONTROL_SIZE
_WAVE_GLYPH = "∿"
# Fun Time's console names the shape beside its mark; so does this.
_SHAPE_NAMES = {"rounded_square": "Square", "sine": "Sine",
                "triangle": "Triangle", "sawtooth": "Sawtooth"}

PANEL_W = SECTION_W + 2 * _PAD
PANEL_H = SECTION_H + _ROW_H + 2 * _PAD


def _limits(state) -> drive_layout.Limits:
    """Which dials have run out of road — what dims the mark that would now do
    nothing."""
    dials = state.state
    half = dials.amplitude // 2
    return drive_layout.Limits(
        spd_at_min=dials.speed <= stroke_engine.MIN_SPEED,
        spd_at_max=dials.speed >= stroke_engine.MAX_SPEED,
        amp_at_min=dials.amplitude <= 0,
        amp_at_max=dials.amplitude >= 100,
        ctr_at_min=dials.intended_center <= half,
        ctr_at_max=dials.intended_center >= 100 - half,
    )


def controls(x: int, y: int, state, active: bool) -> list[DriveControl]:
    """Every mark on the panel: the shared −/+ pair per axis, plus this app's
    own row — cruise control (lit while it has the dials) and the waveform."""
    row_y = y + SECTION_H + drive_layout.GAP
    size = drive_layout.CONTROL_SIZE
    g = geometry(x, y, drive_layout.fraction(state.state.center))
    return [
        *drive_layout.controls(x, y, state.state.center, _limits(state)),
        DriveControl((g.wave[0], row_y, size, size), CRUISE, "cc",
                     not state.cruise.active),
        DriveControl((g.wave[0] + size + drive_layout.GAP, row_y, size, size),
                     SHAPE, _WAVE_GLYPH, False),
    ]


def tracks(x: int, y: int, state) -> list[DriveTrack]:
    return drive_layout.tracks(x, y, state.state.center)


class StrokePanel(QWidget):
    """The pressable drive readout, floated over whichever surface hosts it."""

    def __init__(self, stroke, parent=None):
        super().__init__(parent)
        self._stroke = stroke
        self._drag_track: DriveTrack | None = None
        self.setFixedSize(PANEL_W, PANEL_H)
        self.setToolTip(f"OSR2 stroke — {STROKE_KEY_LEGEND}")
        # The trace scrolls with the phase, so repaint on a beat while shown.
        self._repaint = QTimer(self)
        self._repaint.setInterval(_REPAINT_MS)
        self._repaint.timeout.connect(self.update)

    def refresh(self) -> None:
        self.update()

    # Fun Time insets its HUD from the window's top-left corner by this much,
    # and a reader glancing between the two apps is looking for one panel in one
    # place.
    MARGIN = 8

    def reposition(self) -> None:
        """The parent's top-left corner, where Fun Time puts the same readout."""
        parent = self.parentWidget()
        if parent is not None:
            self.move(self.MARGIN, self.MARGIN)

    def showEvent(self, event):
        super().showEvent(event)
        self._repaint.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._repaint.stop()

    # --- presses: marks step, bands set, power toggles ---------------------

    def mousePressEvent(self, event):
        self._press_at(int(event.position().x()), int(event.position().y()))

    def _press_at(self, px: int, py: int) -> None:
        """A press at ``(px, py)`` in the panel: a mark steps its axis, a band
        sets it outright. Split out from the event so the mapping can be tested
        without synthesizing mouse events."""
        state = self._stroke.state
        for control in controls(_PAD, _PAD, state, self._stroke.active):
            if hit(control.rect, px, py):
                self._act(control.action)
                self.update()
                return
        for track in tracks(_PAD, _PAD, state):
            if hit(track.rect, px, py):
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
        if action == CRUISE:
            stroke.toggle_cruise()
        elif action == SHAPE:
            stroke.cycle_shape()
        elif action == "speed_down":
            stroke.adjust_speed(-5)
        elif action == "speed_up":
            stroke.adjust_speed(5)
        elif action == "amplitude_up":
            stroke.adjust_amplitude(10)
        elif action == "amplitude_down":
            stroke.adjust_amplitude(-10)
        elif action == "center_up":
            stroke.adjust_center(5)
        elif action == "center_down":
            stroke.adjust_center(-5)

    def _set_from_track(self, track: DriveTrack, px: int, py: int) -> None:
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
        dials = state.state
        g = geometry(_PAD, _PAD, drive_layout.fraction(dials.center))

        self._wave(painter, g.wave, state, level_ink)
        self._amp_bar(painter, g.amp_bar, state, level_ink)
        self._bar(painter, g.speed_bar,
                  (dials.speed - stroke_engine.MIN_SPEED)
                  / (stroke_engine.MAX_SPEED - stroke_engine.MIN_SPEED), level_ink)
        marks = controls(_PAD, _PAD, state, live)
        for control in marks:
            self._control(painter, control)

        tiny = painter.font()
        tiny.setPointSize(7)
        painter.setFont(tiny)
        self._stacked(painter, g.axis_label_y, "Center", str(dials.center),
                      right=g.center_label_right, ink=value_ink)
        self._stacked(painter, g.axis_label_y, "Amp", str(dials.amplitude),
                      left=g.amp_label_left, ink=value_ink)
        self._speed_label(painter, g.speed_label_y, g.speed_label_x,
                          str(dials.speed), ink=value_ink)
        row = [c for c in marks if c.action == SHAPE][0].rect
        painter.setPen(QPen(value_ink, 1))
        painter.drawText(QRectF(row[0] + row[2] + drive_layout.GAP, row[1],
                                SECTION_W, row[3]),
                         int(Qt.AlignmentFlag.AlignVCenter),
                         _SHAPE_NAMES.get(dials.shape.value, dials.shape.value))
        painter.end()

    def _wave(self, painter: QPainter, rect: Rect, state, ink: QColor) -> None:
        x, y, w, h = rect
        painter.setPen(QPen(QColor(TEXT_MUTED), 1))
        painter.setBrush(_TRACK)
        painter.drawRect(x, y, w - 1, h - 1)
        # The center's dotted ruler — the height the stroke swings about.
        dotted = QPen(QColor(TEXT_MUTED), 1, Qt.PenStyle.DotLine)
        painter.setPen(dotted)
        center_y = y + round((1 - state.state.center / 100) * (h - 1))
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
        half = state.state.amplitude / 200  # amplitude% of the axis, as a 0-1 half-span
        center = state.state.center / 100
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
        painter.drawRect(x, y, max(1, round(clamp01(fill) * w)), h)

    def _control(self, painter: QPainter, control: DriveControl) -> None:
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
