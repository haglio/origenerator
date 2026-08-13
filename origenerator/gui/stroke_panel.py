"""The drive readout, floated over whichever surface hosts it — and pressable.

Nothing here draws the readout. :class:`player_core.drive_readout.DriveSection`
does, the same painter Fun Time's console shows, onto the same
:class:`player_core.hud_panel.HudPanel` slab; this renders that into a Pillow
image and blits it. Sharing the *layout* and repainting the design in QPainter
was not enough — it had its own font, its own slab and its own trace, and read
as this app's idea of Genau's readout rather than Genau's readout.

What this adds is the row Fun Time keeps in its console, because there is no
console here: cruise control, which varies the stroke hands-free, and the
waveform. Both are drawn through the readout's own ``draw_control``, so they are
the same mark as the six above them rather than a lookalike.

The on/off switch is not here. It is a button in the window's toolbar, and this
panel is what appears once it is pressed.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import Qt, QTimer

from origenerator import stroke_engine
from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND
from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core import drive_layout  # noqa: E402
from player_core.direct_control import POSITION_MAX  # noqa: E402
from player_core.drive_layout import (  # noqa: E402
    CENTER, SECTION_H, SECTION_W, SPEED, DriveControl, DriveTrack, geometry,
    hit, track_value,
)
from player_core.drive_readout import (  # noqa: E402
    DRIVEN_BY_GENAU, DRIVEN_BY_NOTHING, DriveHud, DriveSection,
)
from player_core.hud_panel import HudPanel  # noqa: E402

_PAD = 10          # the slab's breathing room around the block
_TRACE_SECONDS = 12.0
_REPAINT_MS = 100  # the trace scrolls with the phase while the panel shows

# The row under the block: cruise control and the waveform.
CRUISE, SHAPE = "cruise", "shape"
_ROW_H = drive_layout.GAP + drive_layout.CONTROL_SIZE
_WAVE_GLYPH = "∿"

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


def drive_hud(state, active: bool) -> DriveHud:
    """The live stroke as the readout's own view of it.

    Everything the picture is made of: the dials, where the device is, and the
    stroke sampled forward — the same samples it is being sent, so the trace is
    the motion rather than a drawing of it. ``driven`` is what dims the whole
    readout: nothing reaching the device is a picture of a stroke nobody is
    making, and it goes grey exactly as Fun Time's does.
    """
    dials = state.state
    limits = _limits(state)
    return DriveHud(
        speed=dials.speed, amplitude=dials.amplitude, center=dials.center,
        shape=dials.shape.value,
        position=round(POSITION_MAX * stroke_engine.position(state) / 100),
        driven=DRIVEN_BY_GENAU if active else DRIVEN_BY_NOTHING,
        trace_seconds=_TRACE_SECONDS,
        spd_at_min=limits.spd_at_min, spd_at_max=limits.spd_at_max,
        amp_at_min=limits.amp_at_min, amp_at_max=limits.amp_at_max,
        ctr_at_min=limits.ctr_at_min, ctr_at_max=limits.ctr_at_max,
        waveform=tuple(stroke_engine.trace(
            state, drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)),
    )


def extra_controls(x: int, y: int, state) -> list[DriveControl]:
    """This app's own row under the block — cruise control (lit while it has the
    dials) and the waveform. Fun Time's console carries these two; there is no
    console here."""
    row_y = y + SECTION_H + drive_layout.GAP
    size = drive_layout.CONTROL_SIZE
    g = geometry(x, y, drive_layout.fraction(state.state.center))
    return [
        DriveControl((g.wave[0], row_y, size, size), CRUISE, "cc",
                     not state.cruise.active),
        DriveControl((g.wave[0] + size + drive_layout.GAP, row_y, size, size),
                     SHAPE, _WAVE_GLYPH, False),
    ]


def controls(x: int, y: int, state, active: bool) -> list[DriveControl]:
    """Every mark on the panel: the readout's own six, and this app's two."""
    return [
        *drive_layout.controls(x, y, state.state.center, _limits(state),
                               dim=not active),
        *extra_controls(x, y, state),
    ]


def tracks(x: int, y: int, state) -> list[DriveTrack]:
    return drive_layout.tracks(x, y, state.state.center)


class StrokePanel(QWidget):
    """The pressable drive readout, floated over whichever surface hosts it."""

    # Fun Time insets its HUD from the window's top-left corner by this much, and
    # a reader glancing between the two apps looks for one panel in one place.
    MARGIN = 8

    def __init__(self, stroke, parent=None):
        super().__init__(parent)
        self._stroke = stroke
        self._drag_track: DriveTrack | None = None
        self._section = DriveSection()
        self.setFixedSize(PANEL_W, PANEL_H)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setToolTip(f"OSR2 stroke — {STROKE_KEY_LEGEND}")
        # The trace scrolls with the phase, so repaint on a beat while shown.
        self._repaint = QTimer(self)
        self._repaint.setInterval(_REPAINT_MS)
        self._repaint.timeout.connect(self.update)

    def refresh(self) -> None:
        self.update()

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

    # --- presses: marks step, bands set ------------------------------------

    def mousePressEvent(self, event):
        self._press_at(int(event.position().x()), int(event.position().y()))

    def _press_at(self, px: int, py: int) -> None:
        """A press at ``(px, py)``: a mark steps its axis, a band sets it
        outright. Split out from the event so the mapping can be tested without
        synthesizing mouse events."""
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

    # --- painting: the readout's own painter, blitted ----------------------

    def render_panel(self) -> HudPanel:
        """The readout drawn onto its slab — the picture, before it is a widget.

        Returned rather than blitted straight, so a test can look at what was
        actually drawn without a screen in front of it.
        """
        state = self._stroke.state
        panel = HudPanel(PANEL_W, PANEL_H)
        hud = drive_hud(state, self._stroke.active)
        self._section.draw(panel.draw, _PAD, _PAD, hud)
        for control in extra_controls(_PAD, _PAD, state):
            self._section.draw_control(panel.draw, control)
        return panel

    def paintEvent(self, event):
        image = self.render_panel().image
        painter = QPainter(self)
        painter.drawImage(0, 0, QImage(
            image.tobytes("raw", "RGBA"), image.width, image.height,
            QImage.Format.Format_RGBA8888))
        painter.end()
