"""Genau's console, shown here — the same one Fun Time draws, minus its mode row.

Nothing on it is drawn here. :class:`player_core.console_hud.ConsolePainter`
paints it, and this widget renders that into a bitmap and blits it: the status
line, the transport, the clip-seconds pace, the hands-free row, the OSR2 line
and the drive readout under them, all the code Fun Time runs. What a press posts
is that console's own answer too — the same command strings Fun Time routes —
and this only routes them to what this app has: the slideshow for the transport
and the pace, the stroke driver for everything about the stroke.

The one row left off is the one naming the three players, and the minimize
button riding it (``modes_row=False``). This console is inside another app's
window, so it is not one of those three and has no borderless window of its own
to park.

The on/off switch is not on it either. That is a button in the toolbar, and this
panel is what appears once it is pressed.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtCore import Qt, QTimer

from origenerator import osr2, stroke_engine
from origenerator.gui.slideshow_pace import STEP_S as DWELL_STEP_S
from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND
from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core import drive_layout  # noqa: E402
from player_core.console import ConsoleModel, console_rows, row_width  # noqa: E402
from player_core.console_hud import (  # noqa: E402
    ConsoleHud, ConsolePainter, ModeHud, hud_xy,
)
from player_core.direct_control import POSITION_MAX  # noqa: E402
from player_core.drive_readout import (  # noqa: E402
    DRIVEN_BY_GENAU, DRIVEN_BY_NOTHING, DriveHud,
)

_TRACE_SECONDS = 12.0
_REPAINT_MS = 100  # the trace scrolls with the phase while the panel shows


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


def drive_hud(state, active: bool, dwell_s: int = 0) -> DriveHud:
    """The live stroke as the readout's own view of it.

    The dials, where the device is, and the stroke sampled forward — the same
    samples it is being sent, so the trace is the motion rather than a drawing
    of it. ``driven`` is what dims the whole readout: nothing reaching the
    device is a picture of a stroke nobody is making, and it goes grey exactly
    as Fun Time's does.
    """
    dials = state.state
    limits = _limits(state)
    return DriveHud(
        speed=dials.speed, amplitude=dials.amplitude, center=dials.center,
        shape=dials.shape.value,
        position=round(POSITION_MAX * stroke_engine.position(state) / 100),
        driven=DRIVEN_BY_GENAU if active else DRIVEN_BY_NOTHING,
        advance_interval=dwell_s,
        trace_seconds=_TRACE_SECONDS,
        spd_at_min=limits.spd_at_min, spd_at_max=limits.spd_at_max,
        amp_at_min=limits.amp_at_min, amp_at_max=limits.amp_at_max,
        ctr_at_min=limits.ctr_at_min, ctr_at_max=limits.ctr_at_max,
        waveform=tuple(stroke_engine.trace(
            state, drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)),
    )


def console_hud(stroke, host, *, device_on: bool = True,
                enhanced_filter=None) -> ConsoleHud:
    """The whole console as Fun Time's painter takes it.

    ``mode`` is genau because that is what this is: a self-generated stroke over
    what is on screen, with no Nau playlist behind it. The empty
    :class:`ModeHud` is what leaves the status line saying only whether the
    slide is held — there is no compilation, no browse order and no length
    filter here to report.

    ``device_on`` is whether the OSR2 is answering at all
    (:func:`origenerator.osr2.device_on`). A stroke running with the device off
    is a stroke nobody is receiving, and the console says so exactly as Fun
    Time's does: the OSR2 row reads "Off" and the painter takes that as nothing
    driving, which greys the readout and holds the trace still. The stroke goes
    on stroking — it cannot see the device either way — so this is the only
    thing standing between a switched-off OSR2 and a console animating a blue
    wave nothing is riding.

    ``enhanced_filter`` is this app's
    :class:`~origenerator.gui.enhanced_filter.EnhancedFilter`, or ``None`` where
    whoever built the panel has none to offer. The console draws that button
    only where there is one behind it — an enhancement is a thing this app
    makes, so Genau's own console has no such set to narrow — and says
    "Enhanceds" in its status line while it is on.
    """
    driving = stroke.active and device_on
    return ConsoleHud(
        modes=ModeHud(),
        console=ConsoleModel(
            mode="genau", active=True, locked=host.locked,
            osr2="genau" if driving else "off",
            cruise=stroke.state.cruise.active,
            shape=stroke.state.state.shape.value,
            advance_interval=host.dwell_s,
            enhanced_filter=(None if enhanced_filter is None
                             else enhanced_filter.active),
        ),
        drive=drive_hud(stroke.state, driving, host.dwell_s),
        modes_row=False,
    )


def panel_size(stroke, host, enhanced_filter=None) -> tuple[int, int]:
    """How big the console draws, which is what the widget has to be.

    Told about the filter the way the drawing is: its button widens the
    transport row, and a widget built one button short would show a cropped
    console until the first repaint resized it.
    """
    return ConsolePainter().rgba(
        console_hud(stroke, host, enhanced_filter=enhanced_filter))[1]


class StrokePanel(QWidget):
    """The console, floated over whichever surface hosts it.

    It shows exactly while the stroke is running. A readout of a stroke nobody
    is making is not information, and every surface that floats one — the main
    window, the fullscreen show — was hosting it on the
    assumption that some other code would hide it. So the rule
    lives here, where the driver is: the panel follows its own subject.
    """

    # Fun Time insets its HUD from the window's top-left corner by this much, and
    # a reader glancing between the two apps looks for one panel in one place.
    MARGIN = hud_xy()[0]

    def __init__(self, stroke, parent=None, host=None, pace=None, device_on=None,
                 enhanced_filter=None):
        super().__init__(parent)
        self._stroke = stroke
        # The enhanced-only switch this console carries, or None where the
        # surface that built the panel has none — see console_hud.
        self._enhanced_filter = enhanced_filter
        # How to ask whether the OSR2 is on the wire, or None for the real read.
        # Injectable so a test never reaches the machine's own broker stamps.
        self._ask_device = device_on
        # Without a slideshow behind it the console still has a pace to set: the
        # one the next slideshow will open at.
        self._host = host if host is not None else PaceOnlyHost(
            pace if pace is not None else SlideshowPace(parent=self))
        self._painter = ConsolePainter()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setToolTip(f"OSR2 stroke — {STROKE_KEY_LEGEND}")
        self.setFixedSize(*panel_size(stroke, self._host, enhanced_filter))
        # The trace scrolls with the phase, so repaint on a beat while shown.
        self._repaint = QTimer(self)
        self._repaint.setInterval(_REPAINT_MS)
        self._repaint.timeout.connect(self.update)
        # Present only while the stroke is running, and following it from
        # wherever it was toggled — the signal for a driver that has one, and
        # :meth:`refresh` (which the hosts call on every stroke key) for one that
        # doesn't.
        self.setVisible(bool(getattr(stroke, "active", False)))
        signal = getattr(stroke, "active_changed", None)
        if signal is not None:
            signal.connect(self._on_active_changed)

    def _on_active_changed(self, active: bool) -> None:
        self.setVisible(active)
        self.update()

    def refresh(self) -> None:
        """Redraw, and re-check whether the stroke is running.

        The hosts call this after every stroke key, which is the one moment the
        answer can have changed under a driver that reports no signal — so the
        panel appears and disappears on the key that did it, not only on the
        signal a full driver happens to emit.
        """
        self.setVisible(bool(getattr(self._stroke, "active", False)))
        self.update()

    def reposition(self) -> None:
        """The parent's top-left corner, where Fun Time puts the same console."""
        parent = self.parentWidget()
        if parent is not None:
            self.move(self.MARGIN, self.MARGIN)

    def showEvent(self, event):
        super().showEvent(event)
        self._repaint.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._repaint.stop()

    # --- presses: the console says what they post, this routes them ---------

    def mousePressEvent(self, event):
        self._post(self._painter.press_at(*self._window(event)))

    def mouseMoveEvent(self, event):
        if self._painter.holding:
            self._post(self._painter.drag_to(*self._window(event)))

    def mouseReleaseEvent(self, event):
        self._painter.release()

    def _window(self, event) -> tuple[int, int]:
        """This widget's coordinates as the window ones the painter expects.

        It sits at the same inset from its parent that Fun Time's does from its
        window, so putting the margin back is the whole conversion.
        """
        return (int(event.position().x()) + self.MARGIN,
                int(event.position().y()) + self.MARGIN)

    def _post(self, action: str) -> None:
        """Do here what Fun Time would route to whichever player owns it."""
        if not action:
            return
        stroke, host = self._stroke, self._host
        if action.startswith("genau_") and "_" in action[6:]:
            axis, _, value = action[6:].rpartition("_")
            if value.isdigit() and axis in ("amp", "center", "speed"):
                {"amp": stroke.set_amplitude, "center": stroke.set_center,
                 "speed": stroke.set_speed}[axis](int(value))
                self.update()
                return
        step = {
            "genau_speed_up": (stroke.adjust_speed, 5),
            "genau_speed_down": (stroke.adjust_speed, -5),
            "genau_amplitude_up": (stroke.adjust_amplitude, 10),
            "genau_amplitude_down": (stroke.adjust_amplitude, -10),
            "genau_center_up": (stroke.adjust_center, 5),
            "genau_center_down": (stroke.adjust_center, -5),
            "genau_prev_clip": (host.stroke_step, -1),
            "genau_next_clip": (host.stroke_step, 1),
        }.get(action)
        if step is not None:
            step[0](step[1])
        elif action == "genau_toggle_cruise":
            stroke.toggle_cruise()
        elif action == "genau_cycle_shape":
            stroke.cycle_shape()
        elif action == "quarter_button":
            stroke.quarter_offset()
        elif action == "main_lock":
            host.stroke_toggle_hold()
        elif action == "genau_weird_clip":
            host.stroke_cull()
        elif action == "genau_filter_enhanced" and self._enhanced_filter is not None:
            # The console draws this button only where there is a filter behind
            # it, so the guard is against a stale press rather than a real one.
            self._enhanced_filter.toggle()
        elif action in ("genau_advance_up", "genau_advance_down"):
            delta = DWELL_STEP_S if action.endswith("up") else -DWELL_STEP_S
            host.set_dwell_s(host.dwell_s + delta)  # the pace clamps its own ends
        self.update()

    # --- painting: the console's own painter, blitted ----------------------

    def render_console(self) -> tuple[bytes, tuple[int, int]]:
        """The console drawn — the picture, before it is a widget. Returned
        rather than blitted straight so a test can look at what was actually
        drawn without a screen in front of it."""
        return self._painter.rgba(
            console_hud(self._stroke, self._host, device_on=self._device_on(),
                        enhanced_filter=self._enhanced_filter))

    def _device_on(self) -> bool:
        """Whether the OSR2 is answering, asked afresh on every draw — the device
        is switched on and off behind this app's back, so there is nothing to
        cache the answer against."""
        ask = self._ask_device if self._ask_device is not None else osr2.device_on
        return bool(ask())

    def paintEvent(self, event):
        raw, (width, height) = self.render_console()
        if (width, height) != (self.width(), self.height()):
            # The rows change width with what they say — a two-digit dwell, a
            # longer waveform name — so the widget follows the picture rather
            # than cropping it.
            self.setFixedSize(width, height)
        painter = QPainter(self)
        painter.drawImage(0, 0, QImage(raw, width, height,
                                       QImage.Format.Format_RGBA8888))
        painter.end()
