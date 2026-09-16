"""Genau's console, shown here — the same one Fun Time draws, minus its mode row.

Nothing on it is drawn here. :class:`player_core.console_hud.ConsolePainter`
paints it, and this widget renders that into a bitmap and blits it: the status
line, the transport, the clip-seconds pace, the hands-free row, the OSR2 line
and the drive readout under them, all the code Fun Time runs. What a press posts
is that console's own answer too — the same command strings Fun Time routes —
and this only routes them to what this app has: the slideshow for the transport
and the pace, the motion driver for everything about the motion.

The one row left off is the one naming the three players, and the minimize
button riding it (``modes_row=False``). This console is inside another app's
window, so it is not one of those three and has no borderless window of its own
to park.

The on/off switch IS on it: the control-state group -- parked, retracted,
driving, control off -- is the app's one OSR2 switch now, and the toolbar's
separate one is gone.  What is not on it are the two switches saying what
a show may play: over a show those are on the players' HUD this panel sits
under (:mod:`origenerator.gui.show_hud`), the same buttons a satellite's HUD
carries, and a second pair here would be two switches for one thing.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget

from origenerator import motion_engine, osr2
from origenerator.gui.motion_hud import MOTION_KEY_LEGEND
from origenerator.gui.slideshow_pace import STEP_S as DWELL_STEP_S
from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
from origenerator.paths import ensure_player_core_on_path

ensure_player_core_on_path()

from player_core import drive_layout  # noqa: E402
from player_core.console import (  # noqa: E402
    OSR2_CONTROL_BUTTONS,
    OSR2_CONTROL_UNANSWERED,
    OSR2_DRIVING,
    OSR2_PARKED,
    OSR2_RETRACTED,
    ConsoleModel,
)
from player_core.console_hud import (  # noqa: E402
    OSR2_ROBOT_HAND,
    ConsoleHud,
    ConsolePainter,
    ModeHud,
    hud_xy,
)
from player_core.drive_readout import (  # noqa: E402
    DRIVEN_BY_FUNSCRIPT,
    DRIVEN_BY_NOTHING,
    DRIVEN_BY_ROBOT_HAND,
    DriveHud,
)
from player_core.robot_hand import (  # noqa: E402
    PARK_CENTER,
    POSITION_MAX,
    RETRACT_CENTER,
)

# Which of the console's four control buttons asks for which state, read off
# player_core's own mapping so a press cannot drift from the button that lights.
_OSR2_CONTROL_BY_COMMAND = {verb: state for state, verb in OSR2_CONTROL_BUTTONS.items()}

_TRACE_SECONDS = 12.0
_REPAINT_MS = 100  # the trace scrolls with the phase while the panel shows


def _limits(state) -> drive_layout.Limits:
    """Which dials have run out of road — what dims the mark that would now do
    nothing."""
    dials = state.state
    half = dials.amplitude // 2
    return drive_layout.Limits(
        spd_at_min=dials.speed <= motion_engine.MIN_SPEED,
        spd_at_max=dials.speed >= motion_engine.MAX_SPEED,
        amp_at_min=dials.amplitude <= 0,
        amp_at_max=dials.amplitude >= 100,
        ctr_at_min=dials.intended_center <= half,
        ctr_at_max=dials.intended_center >= 100 - half,
    )


def drive_hud(state, active: bool, dwell_s: int = 0) -> DriveHud:
    """The live motion as the readout's own view of it.

    The dials, where the device is, and the motion sampled forward — the same
    samples it is being sent, so the trace is the motion rather than a drawing
    of it. ``driven`` is what dims the whole readout: nothing reaching the
    device is a picture of a motion nobody is making, and it goes grey exactly
    as Fun Time's does.
    """
    dials = state.state
    limits = _limits(state)
    heights, slide = motion_engine.trace_window(state, drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    return DriveHud(
        speed=dials.speed, amplitude=dials.amplitude, center=dials.center,
        shape=dials.shape.value,
        position=round(POSITION_MAX * motion_engine.position(state) / 100),
        driven=DRIVEN_BY_ROBOT_HAND if active else DRIVEN_BY_NOTHING,
        advance_interval=dwell_s,
        trace_seconds=_TRACE_SECONDS,
        spd_at_min=limits.spd_at_min, spd_at_max=limits.spd_at_max,
        amp_at_min=limits.amp_at_min, amp_at_max=limits.amp_at_max,
        ctr_at_min=limits.ctr_at_min, ctr_at_max=limits.ctr_at_max,
        waveform=tuple(heights[:drive_layout.TRACE_SAMPLES]),
        slide=slide,
        edge=heights[drive_layout.TRACE_SAMPLES],
    )


def script_hud(script, motion, dwell_s: int) -> DriveHud:
    """The readout while a funscript has the device: the script's own line from
    the playhead forward, in the green every scripted thing in this family is
    drawn in.

    The dials beside it stay the motion's.  They are what driving puts back the
    moment the script is done, and the readout dims every one of them anyway
    while something other than the motion is sending.
    """
    heights = script.trace(drive_layout.TRACE_SAMPLES, _TRACE_SECONDS)
    dials = motion.state
    return DriveHud(
        speed=dials.speed, amplitude=dials.amplitude, center=dials.center,
        shape=dials.shape.value,
        position=round(POSITION_MAX * (heights[0] if heights else 0.0)),
        driven=DRIVEN_BY_FUNSCRIPT, advance_interval=dwell_s,
        trace_seconds=_TRACE_SECONDS, waveform=heights)


def console_hud(motion, host, *, device_on: bool = True,
                control: str = OSR2_CONTROL_UNANSWERED, script=None) -> ConsoleHud:
    """The whole console as Fun Time's painter takes it.

    ``mode`` is genau because that is what this is: a self-generated motion over
    what is on screen, with no Nau playlist under it. The empty
    :class:`ModeHud` is what leaves the status line saying only whether the
    slide is held — there is no compilation, no browse order and no length
    filter here to report.

    ``script`` is the funscript driver, when this app has one: while it has the
    device the readout is the script's line rather than the motion's, and the
    OSR2 row says FunScript -- the motion is stopped, and drawing it would be a
    picture of something nobody is sending.

    ``device_on`` is whether the OSR2 is answering at all
    (:func:`origenerator.osr2.device_on`). A motion running with the device off
    is a motion nobody is receiving, and the console says so exactly as Fun
    Time's does: the OSR2 row reads "Off" and the painter takes that as nothing
    driving, which greys the readout and holds the trace still. The motion goes
    on — it cannot see the device either way — so this is the only
    thing standing between a switched-off OSR2 and a console animating a blue
    wave nothing is riding.

    Neither filter switch is offered (both ``None``): the console draws those
    only where the host hands over a set to narrow, and here the show's own HUD
    carries them instead.
    """
    scripted = script is not None and script.active and device_on
    driving = motion.active and device_on and not scripted
    return ConsoleHud(
        modes=ModeHud(),
        console=ConsoleModel(
            mode="genau", active=True, locked=host.locked,
            osr2=(DRIVEN_BY_FUNSCRIPT if scripted
                  else OSR2_ROBOT_HAND if driving else "off"),
            osr2_control=control,
            cruise=motion.state.cruise.active,
            learned=motion.state.learned.active,
            shape=motion.state.state.shape.value,
            advance_interval=host.dwell_s,
        ),
        drive=(script_hud(script, motion.state, host.dwell_s) if scripted
               else drive_hud(motion.state, driving, host.dwell_s)),
        modes_row=False,
    )


def panel_size(motion, host, control: str = OSR2_CONTROL_UNANSWERED) -> tuple[int, int]:
    """How big the console draws, which is what the widget has to be."""
    return ConsolePainter().rgba(console_hud(motion, host, control=control))[1]


class MotionPanel(QWidget):
    """The console, floated over whichever surface hosts it.

    It is always here, motion or no motion. Part of what is on it is not about a
    running motion at all — the pace an unheld slide moves on at — and a panel
    that appeared only once the device was being driven made that reachable
    only by starting a motion first. With nothing driving, it draws itself
    exactly as Fun Time's does with the OSR2 off: the OSR2 row reads "Off", the
    readout greys, and the trace holds still rather than animating a wave
    nobody is riding.
    """

    # Fun Time insets its HUD from the window's top-left corner by this much, and
    # a reader glancing between the two apps looks for one panel in one place.
    MARGIN = hud_xy()[0]

    def __init__(self, motion, parent=None, host=None, pace=None, device_on=None,
                 control=None):
        super().__init__(parent)
        self._motion = motion
        # The app's one OSR2 switch: the control-state group's four buttons
        # read which state it is in and ask it for another.  None where nobody
        # handed one over, which is what a test's bare panel gets -- the group
        # then draws as driving and its presses reach only the motion.
        self._control = control
        if control is not None:
            control.changed.connect(self.refresh)
            # And whenever the app re-aims the device: which driver has it moves
            # with the video in front as much as with a press on this panel.
            control.settled.connect(self.refresh)
        # How to ask whether the OSR2 is on the wire, or None for the real read.
        # Injectable so a test never reaches the machine's own broker stamps.
        self._ask_device = device_on
        # Without a slideshow under it the console still has a pace to set: the
        # one the next slideshow will open at.
        self._host = host if host is not None else PaceOnlyHost(
            pace if pace is not None else SlideshowPace(parent=self))
        self._painter = ConsolePainter()
        # A video surface is a native window on Windows, and a plain sibling
        # widget cannot paint over one however it is stacked — which is why
        # every other panel floated over a show (the HUD, the toast, the queue)
        # is native too.  Native itself, this stacks against the media by
        # Z-order like any other window, so the console is reachable over a
        # clip that fills the corner it sits in, not only over a still.
        #
        # Native and NOT translucent, exactly like the HUD beside it.  The
        # slab's rounded corners and see-through ground come from the RGBA
        # picture the painter hands over, composited onto whatever the parent
        # paints beneath — Qt does that for any child that neither fills its
        # own background nor claims to paint opaquely.  Asking for a
        # translucent surface as well used to be harmless on a plain child
        # widget, but on a native child it asks Windows for an alpha surface,
        # and the console then came out TWICE over a show: once where Qt drew
        # it and once more at double its offset, where that surface ended up.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setToolTip(f"OSR2 motion — {MOTION_KEY_LEGEND}")
        self.setFixedSize(*panel_size(motion, self._host, self._osr2_control()))
        # A show's console is built while its video is already driving, so the
        # first paint must be the size that console draws at.
        # The trace scrolls with the phase, so repaint on a beat while it is
        # moving — and only while it is. A still console redrawn ten times a
        # second is the same picture at Pillow's price, and with the panel now
        # always up that price would be paid for the whole session.
        self._repaint = QTimer(self)
        self._repaint.setInterval(_REPAINT_MS)
        self._repaint.timeout.connect(self.update)
        # Followed from wherever the motion was toggled — the signal for a driver
        # that has one, and :meth:`refresh` (which the hosts call on every motion
        # key) for one that doesn't.
        signal = getattr(motion, "active_changed", None)
        if signal is not None:
            signal.connect(self._on_active_changed)

    def _on_active_changed(self, _active: bool) -> None:
        self._sync_repaint()
        self.update()

    def refresh(self) -> None:
        """Redraw, and re-check whether the motion is running.

        The hosts call this after every motion key, which is the one moment the
        answer can have changed under a driver that reports no signal — so the
        trace starts and stops on the key that did it, not only on the signal a
        full driver happens to emit.
        """
        self._sync_repaint()
        self.update()

    def _sync_repaint(self) -> None:
        """Animate only what is moving: a shown panel with something driving.

        Either driver moves the line -- the motion's wave scrolls with its
        phase, the script's with the playhead -- and neither does while the
        device is held at an end or let go of.
        """
        if self.isVisible() and self._driving():
            self._repaint.start()
        else:
            self._repaint.stop()

    def _driving(self) -> bool:
        if self._control is not None:
            return self._control.source() is not None
        return bool(getattr(self._motion, "active", False))

    def reposition(self, below=None) -> None:
        """The parent's top-left corner, where Fun Time puts the same console —
        or, given the rect of a panel already in that corner, directly under
        it, in the same column and a panel-inset apart.

        *below* is the players' HUD a show wears: Fun Time draws its console on
        the main player and that HUD on the satellites, two windows, but a show
        wears both in one, and the two are in the same corner, so the console
        takes the slot beneath.  It follows the HUD's left edge rather than its
        own margin, so the two read as one column of panels rather than as two
        panels that missed each other.
        """
        parent = self.parentWidget()
        if parent is None:
            return
        if below is None:
            self.move(self.MARGIN, self.MARGIN)
        else:
            self.move(below.x(), below.bottomLeft().y() + 1 + below.x())

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_repaint()

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
        motion, host = self._motion, self._host
        if action.startswith("robot_hand_") and "_" in action[11:]:
            axis, _, value = action[11:].rpartition("_")
            if value.isdigit() and axis in ("amp", "center", "speed"):
                {"amp": motion.set_amplitude, "center": motion.set_center,
                 "speed": motion.set_speed}[axis](int(value))
                self.update()
                return
        step = {
            "robot_hand_speed_up": (motion.adjust_speed, 5),
            "robot_hand_speed_down": (motion.adjust_speed, -5),
            "robot_hand_amplitude_up": (motion.adjust_amplitude, 10),
            "robot_hand_amplitude_down": (motion.adjust_amplitude, -10),
            "robot_hand_center_up": (motion.adjust_center, 5),
            "robot_hand_center_down": (motion.adjust_center, -5),
            "genau_prev_clip": (host.show_step, -1),
            "genau_next_clip": (host.show_step, 1),
        }.get(action)
        if step is not None:
            step[0](step[1])
        elif action in _OSR2_CONTROL_BY_COMMAND:
            self._ask_for_control(_OSR2_CONTROL_BY_COMMAND[action])
        elif action == "robot_hand_toggle_cruise":
            motion.toggle_cruise()
        elif action == "robot_hand_toggle_learned":
            motion.toggle_learned()
        elif action == "robot_hand_cycle_shape":
            motion.cycle_shape()
        elif action == "quarter_button":
            motion.quarter_offset()
        elif action == "main_lock":
            host.show_toggle_hold()
        elif action == "genau_weird_clip":
            host.show_cull()
        elif action in ("genau_clip_seconds_up", "genau_clip_seconds_down"):
            delta = DWELL_STEP_S if action.endswith("up") else -DWELL_STEP_S
            host.set_dwell_s(host.dwell_s + delta)  # the pace clamps its own ends
        self.update()

    # --- painting: the console's own painter, blitted ----------------------

    def _ask_for_control(self, state: str) -> None:
        """A press on the control-state group.  With no switch handed over there
        is still the motion to hold, which is what a panel outside a gallery can
        do about the device."""
        if self._control is not None:
            self._control.set_state(state)
        elif state == OSR2_DRIVING:
            self._motion.release()
        elif state in (OSR2_PARKED, OSR2_RETRACTED):
            self._motion.hold(
                PARK_CENTER if state == OSR2_PARKED else RETRACT_CENTER)

    def _script(self):
        """The app's funscript driver, when the switch handed one over."""
        return self._control.script if self._control is not None else None

    def _osr2_control(self) -> str:
        # Unanswered with no switch handed over: the group then draws the two
        # holds it has always had and no off button, which is a switch nothing
        # would hear.  The holds still reach the motion -- see _ask_for_control.
        return (OSR2_CONTROL_UNANSWERED if self._control is None
                else self._control.state())

    def render_console(self) -> tuple[bytes, tuple[int, int]]:
        """The console drawn — the picture, before it is a widget. Returned
        rather than blitted straight so a test can look at what was actually
        drawn without a screen in front of it."""
        return self._painter.rgba(console_hud(
            self._motion, self._host, device_on=self._device_on(),
            control=self._osr2_control(), script=self._script()))

    def _device_on(self) -> bool:
        """Whether the OSR2 is answering, asked afresh on every draw — the device
        is switched on and off without this app knowing, so there is nothing to
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
