"""The button bank over the browser pane, and the state it is written from.

The seventh and last of the gallery's screen concerns to come out of the view
that used to hold all of them -- and the one with a model where there was none.

Every button's enabled state, tooltip and visibility used to be recomputed by a
method of its own, and every event handler in the gallery had to remember which
subset of those to call. The comments recorded what that cost: one of them existed
because "nothing else repaints them at that moment", and a media filter ended with
an extra call because the signal that normally re-synced that button never fires
and it went on offering a slideshow of nothing. Both were bugs fixed by adding another
call, and a protocol whose fix is another call guarantees more of them.

There is one call now. :class:`BankState` says how all sixteen buttons stand, as
plain values with no widget in sight; :meth:`ToolbarBank.apply` writes them, and
the gaps between the groups fall out of what is showing. A handler that forgets to
re-aim the bank forgets all of it at once, which is a thing you can see, rather
than one button out of sixteen, which is not.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PyQt6.QtWidgets import QToolButton, QWidget
from shared_ui.colors import BG_PRIMARY
from shared_ui.mark_button import fill_square_with_mark
from shared_ui.palette import AMBER, BLUE, as_hex
from shared_ui.spacing import (
    BUTTON_GAP,
    BUTTON_GROUP_GAP,
    BUTTON_RADIUS,
    BUTTON_ROW_GAP,
    BUTTON_SIZE,
)

from origenerator import ui_scale
from origenerator.config import RADIO_STATIONS
from origenerator.gui import icons, omnipause
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.link_tip import LinkTip, link


def _lit(color: str) -> str:
    return f"QToolButton:checked {{ background-color: {color}; border-radius: {BUTTON_RADIUS}px; }}"


# A lit background while a switch is on.
_LIT = _lit(as_hex(BLUE))
_LIT_WHILE_THE_ROOM_IS_PAUSED = _lit(as_hex(AMBER))

# What the Auto switch's clickable tip says while the Auto-Generate it would stop is
# running in some other folder. Naming that folder is no use when a name is a
# short code with no branch attached to it, so the tip offers to go there.
AUTO_ELSEWHERE_TIP = (
    "Auto-generate is running in another folder<br>"
    f"{link('auto', 'Go to it')} · click the switch to stop it"
)


class Button(NamedTuple):
    """How one button stands: on or off, shown or away, and what it says it does.

    ``checked`` is ``None`` for a button that is not a switch, so a state that
    says nothing about a switch leaves it exactly as the user set it.
    """

    enabled: bool = True
    visible: bool = True
    tip: str = ""
    checked: bool | None = None


class BankState(NamedTuple):
    """How the whole bank stands, as values a test can write by hand.

    One record rather than sixteen methods: what each button depends on is
    gathered once, by whoever can see all of it, and written in one pass.
    """

    back: Button
    forward: Button
    undo: Button
    redo: Button
    group: Button
    favorite: Button
    enhance: Button
    delete: Button
    slideshow: Button
    auto: Button
    # The Auto switch's clickable tip, which stands in for its tooltip while the
    # Auto-Generate is running somewhere else: only one of the two ever appears.
    auto_tip: str = ""


class BankActs(NamedTuple):
    """What each button does when pressed — bound handlers, never names.

    By object rather than by attribute name, for the reason the spoken
    vocabulary learned: a renamed handler spelled as a string breaks a button
    silently, with no import error, no type error and no lint warning.
    """

    go_back: Callable[[], None]
    go_forward: Callable[[], None]
    undo: Callable[[], None]
    redo: Callable[[], None]
    start_slideshow: Callable[[], None]
    toggle_auto: Callable[[bool], None]
    go_to_auto_generating_folder: Callable[[str], None]
    favorite: Callable[[], None]
    enhance: Callable[[], None]
    group: Callable[[], None]
    delete: Callable[[], None]
    toggle_radio: Callable[[bool], None]
    toggle_mic: Callable[[bool], None]


def _landing_at_the_huds_scale(length: int, *, hosted: bool) -> int:
    return length if hosted else round(length * ui_scale.HOSTED_SCALE)


class _SoundSwitch(QToolButton):
    def set_frozen(self, frozen: bool) -> None:
        self.setStyleSheet(_LIT_WHILE_THE_ROOM_IS_PAUSED if frozen else _LIT)
        self.setIcon(icons.radio_icon(lit_ink=BG_PRIMARY if frozen else None))


def _tool_button(icon, tooltip: str, handler, *, checkable=False,
                 kind=QToolButton) -> QToolButton:
    btn = kind()
    btn.setIcon(icon)
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    (btn.toggled if checkable else btn.clicked).connect(handler)
    return btn


def _group_gap() -> QWidget:
    """The space between two groups of the bank.

    Space alone is what separates them — a rule here used to, and in a bank that
    wraps onto a second row a rule can land at the end of one row or the start of
    the next, marking nothing. An empty widget rather than layout spacing because
    the gap comes and goes with the group under it, and a widget is the thing a
    flow layout can be told to leave out.
    """
    return QWidget()


class ToolbarBank(QWidget):
    """The sixteen buttons over the browser pane, in six groups a space apart.

    Grouping is what makes an icon-only bank readable — a button's neighbors say
    as much about it as its glyph does — and the bank takes the pane's whole
    width, wrapping onto as many rows as that width needs. Beside the folder path
    it had to share a narrow pane with a name, and what a horizontal layout does
    when it runs out of room is squeeze every button until the glyphs are
    unreadable: a row of smudges. Wrapped, a button is always its own size.

    ``hosted`` builds no Origenerator Radio switch and no microphone: inside a
    Fun Time session each Satellite Funestra plays its own stations, tuned in
    while a picture is up, and the session owns the mic, so a switch for either
    here would be a switch over something this window does not hold. There is
    no OSR2 switch here at all any more: the Funestras' console carries one, on
    driving and off parked, and that is where the device is switched now, on
    every surface.
    """

    def __init__(self, acts: BankActs, *, hosted: bool):
        super().__init__()
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)  # so the column above gives it the rows it asks for
        self.setSizePolicy(policy)
        self.back = _tool_button(icons.back_icon(), "Back", acts.go_back)
        self.forward = _tool_button(icons.forward_icon(), "Forward", acts.go_forward)
        self.undo = _tool_button(icons.undo_icon(), "Undo", acts.undo)
        self.redo = _tool_button(icons.redo_icon(), "Redo", acts.redo)
        # Shown wherever there's a collection of media to play — a folder, or the
        # Recents/Favorites collection — with its tooltip naming that subject.
        self.slideshow = _tool_button(
            icons.slideshow_icon(), "Play this folder as a slideshow",
            acts.start_slideshow)
        self.slideshow.hide()
        self.auto = _tool_button(
            icons.auto_generate_icon(),
            "Auto-generate: repeatedly generate variations of this folder until "
            "toggled off",
            acts.toggle_auto, checkable=True,
        )
        self.auto.setStyleSheet(_LIT)
        # Never hidden: Auto-Generate runs until it is stopped, and a switch that went
        # away with its folder left it running with nothing on screen to say so.
        # It grays instead when there is nothing to do.
        self.auto_tip = LinkTip(self.auto)
        self.auto_tip.link_activated.connect(acts.go_to_auto_generating_folder)
        # Favorite, enhance, delete: the three things you can do to what is in front
        # of you, each aimed the same way — the picked thumbnails, else the
        # folder on screen. Colored, and grouped, because they are one set: gold
        # for keep, green for make-better, red for take-away.
        self.favorite = _tool_button(icons.star_icon(filled=True), "Favorite", acts.favorite)
        self.enhance = _tool_button(icons.enhance_icon(), "Enhance", acts.enhance)
        # Turn the folders picked in the tree into a folder of their own. Shown
        # only while several are picked — that selection IS the folder, unsaved.
        self.group = _tool_button(
            icons.custom_folder_icon(),
            "Group the selected folders into a folder of your own", acts.group)
        self.group.hide()
        self.delete = _tool_button(icons.delete_icon(), "Delete", acts.delete)
        self.radio = None
        self.mic = None
        if not hosted:
            # While it's on, a few library videos play at once with only their
            # sound — something to work over, tied to nothing on screen.
            self.radio = _tool_button(
                icons.radio_icon(),
                f"Origenerator Radio: play {RADIO_STATIONS} library videos at once, "
                "sound only, shuffling endlessly",
                acts.toggle_radio, checkable=True, kind=_SoundSwitch,
            )
            omnipause.holds(self.radio)
            # The microphone stands apart from the switches above: those are what
            # the app is doing, and the mic is what it hears with. On is listening,
            # off is not.
            self.mic = _tool_button(
                icons.mic_icon(),
                "Listen: bare words for the collections and this bank (“experiments”, "
                "“undo”, “star”), Fun Time's own words over a slideshow (“next”, "
                "“weird”, “lock”), and orders about the picture (“enhance”, “fix "
                "hands”, “animate as kino”)",
                acts.toggle_mic, checkable=True,
            )
            self.mic.setStyleSheet(_LIT)
        # The family's own gap along a row, and its wider one between wrapped
        # rows -- at the single small gap this used, a bank that wrapped had its
        # two rows all but touching.
        layout = FlowLayout(self)
        self._groups: list[tuple[QWidget, tuple[QToolButton, ...]]] = []
        for buttons in (
            (self.back, self.forward),               # where you are
            (self.undo, self.redo),                  # what you did
            (self.group,),                           # …to the picked folders
            (self.favorite, self.enhance, self.delete),  # …to what's in front
            (self.slideshow, self.auto, self.radio),  # what the app is doing
            (self.mic,),                             # what it hears with
        ):
            buttons = tuple(b for b in buttons if b is not None)
            gap = _group_gap()
            layout.addWidget(gap)
            for button in buttons:
                layout.addWidget(button)
            self._groups.append((gap, buttons))
        self._show_the_gaps()
        self._draw_at_the_huds_scale(hosted=hosted)

    def _draw_at_the_huds_scale(self, *, hosted: bool) -> None:
        layout = self.layout()
        layout.setSpacing(_landing_at_the_huds_scale(BUTTON_GAP, hosted=hosted))
        layout.set_row_spacing(_landing_at_the_huds_scale(BUTTON_ROW_GAP, hosted=hosted))
        square = _landing_at_the_huds_scale(BUTTON_SIZE, hosted=hosted)
        for gap, buttons in self._groups:
            gap.setFixedSize(_landing_at_the_huds_scale(BUTTON_GROUP_GAP, hosted=hosted), 1)
            for button in buttons:
                fill_square_with_mark(button, size=square)

    def become_hosted(self) -> None:
        self._draw_at_the_huds_scale(hosted=True)
        self._room_switches = (self.radio, self.mic)
        self._show_the_room_switches(False)
        self.radio = self.mic = None

    def become_standalone(self) -> None:
        self._draw_at_the_huds_scale(hosted=False)
        self.radio, self.mic = self._room_switches
        self._show_the_room_switches(True)

    def turn_the_radio_on(self) -> None:
        if self.radio is not None:
            self.radio.setChecked(True)

    def _show_the_room_switches(self, shown: bool) -> None:
        for switch in self._room_switches:
            if switch is not None:
                switch.setVisible(shown)
        self._show_the_gaps()

    def apply(self, state: BankState) -> None:
        """Write the whole bank from one state, then re-space the groups.

        Every button, every time: a handler that forgets to re-aim the bank
        forgets all of it at once, which is a thing you can see.
        """
        for button, stands in (
            (self.back, state.back),
            (self.forward, state.forward),
            (self.undo, state.undo),
            (self.redo, state.redo),
            (self.group, state.group),
            (self.favorite, state.favorite),
            (self.enhance, state.enhance),
            (self.delete, state.delete),
            (self.slideshow, state.slideshow),
            (self.auto, state.auto),
        ):
            button.setEnabled(stands.enabled)
            button.setVisible(stands.visible)
            button.setToolTip(stands.tip)
            if stands.checked is not None and button.isChecked() != stands.checked:
                # Around the write, not around the press: a switch put where the
                # app already is must not re-run what the user's own click does.
                button.blockSignals(True)
                button.setChecked(stands.checked)
                button.blockSignals(False)
        self.auto_tip.set_html(state.auto_tip)
        self._show_the_gaps()

    def _show_the_gaps(self) -> None:
        """Show the space in front of each group that has something to show, and
        hide the leading one — so a bank whose optional buttons (Group, Auto,
        Slideshow) are away never wears a stray or doubled gap, and never starts
        indented."""
        leading = True
        for gap, buttons in self._groups:
            showing = any(not button.isHidden() for button in buttons)
            gap.setVisible(showing and not leading)
            leading = leading and not showing
