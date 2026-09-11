"""The button bank over the browser pane, and the state it is written from.

The seventh and last of the gallery's screen concerns to come out of the view
that used to hold all of them -- and the one with a model where there was none.

Every button's enabled state, tooltip and visibility used to be recomputed by a
method of its own, and every event handler in the gallery had to remember which
subset of those to call. The comments recorded what that cost: one of them existed
because "nothing else repaints them at that moment", and a media filter ended with
an extra call because the signal that normally re-synced that button never fires
and it went on offering a show of nothing. Both were bugs fixed by adding another
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

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QToolButton, QWidget

from origenerator.config import AMBIENT_AUDIO_VOICES
from origenerator.gui import icons
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.link_tip import LinkTip, link
from origenerator.gui.motion_hud import MOTION_KEY_LEGEND
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.spacing import (  # noqa: E402
    BUTTON_GAP,
    BUTTON_GROUP_GAP,
    BUTTON_ICON,
    BUTTON_ROW_GAP,
)

# A lit background while a switch is on.
_LIT = "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"

# What the Auto switch's clickable tip says while the loop it would stop is
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
    star: Button
    enhance: Button
    delete: Button
    slideshow: Button
    auto: Button
    # The Auto switch's clickable tip, which stands in for its tooltip while the
    # loop is running somewhere else: only one of the two ever appears.
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
    start_show: Callable[[], None]
    toggle_auto: Callable[[bool], None]
    go_to_looping_folder: Callable[[str], None]
    star: Callable[[], None]
    enhance: Callable[[], None]
    group: Callable[[], None]
    delete: Callable[[], None]
    toggle_audio: Callable[[bool], None]
    toggle_mic: Callable[[bool], None]
    toggle_drive: Callable[[bool], None]


def _tool_button(icon, tooltip: str, handler, *, checkable=False) -> QToolButton:
    """An icon-only button for the bank. A ``checkable`` one is a toggle whose
    ``handler`` receives its on/off state.

    The icon is drawn near the button's full height on purpose. At 16px it sat in
    a 24px button carrying a glyph that used a third of its own canvas — a mark
    covering about a ninth of the button, which reads as a smudge rather than as
    a symbol.
    """
    btn = QToolButton()
    btn.setObjectName("iconButton")
    btn.setIcon(icon)
    btn.setIconSize(QSize(BUTTON_ICON, BUTTON_ICON))
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
    gap = QWidget()
    gap.setFixedSize(BUTTON_GROUP_GAP, 1)
    return gap


class ToolbarBank(QWidget):
    """The sixteen buttons over the browser pane, in six groups a space apart.

    Grouping is what makes an icon-only bank readable — a button's neighbors say
    as much about it as its glyph does — and the bank takes the pane's whole
    width, wrapping onto as many rows as that width needs. Beside the folder path
    it had to share a narrow pane with a name, and what a horizontal layout does
    when it runs out of room is squeeze every button until the glyphs are
    unreadable: a row of smudges. Wrapped, a button is always its own size.

    ``hosted`` builds no audio bed and no microphone: inside a Fun Time session
    the main player owns the room's sound and the session owns the mic, so a
    second switch for either would be a switch over something this window does
    not hold. ``device`` builds no OSR2 switch for the same reason — the session
    keeps the device on its main player.
    """

    def __init__(self, acts: BankActs, *, hosted: bool, device: bool):
        super().__init__()
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)  # so the column above gives it the rows it asks for
        self.setSizePolicy(policy)
        self.back = _tool_button(icons.back_icon(), "Back", acts.go_back)
        self.forward = _tool_button(icons.forward_icon(), "Forward", acts.go_forward)
        self.undo = _tool_button(icons.undo_icon(), "Undo", acts.undo)
        self.redo = _tool_button(icons.redo_icon(), "Redo", acts.redo)
        # Shown wherever there's a collection of media to play — a folder, or the
        # Recents/Starred shelf — with its tooltip naming that subject.
        self.slideshow = _tool_button(
            icons.slideshow_icon(), "Play this folder as a slideshow",
            acts.start_show)
        self.slideshow.hide()
        self.auto = _tool_button(
            icons.autoloop_icon(),
            "Auto-generate: repeatedly generate variations of this folder until "
            "toggled off (Esc stops it too)",
            acts.toggle_auto, checkable=True,
        )
        self.auto.setStyleSheet(_LIT)
        # Never hidden: a loop runs until it is stopped, and a switch that went
        # away with its folder left one running with nothing on screen to say so.
        # It greys instead when there is nothing to do.
        self.auto_tip = LinkTip(self.auto)
        self.auto_tip.link_activated.connect(acts.go_to_looping_folder)
        # Star, enhance, delete: the three things you can do to what is in front
        # of you, each aimed the same way — the picked thumbnails, else the
        # folder on screen. Colored, and grouped, because they are one set: gold
        # for keep, green for make-better, red for take-away.
        self.star = _tool_button(icons.star_icon(filled=True), "Star", acts.star)
        self.enhance = _tool_button(icons.enhance_icon(), "Enhance", acts.enhance)
        # Turn the folders picked in the tree into a folder of their own. Shown
        # only while several are picked — that selection IS the folder, unsaved.
        self.group = _tool_button(
            icons.custom_folder_icon(),
            "Group the selected folders into a folder of your own", acts.group)
        self.group.hide()
        self.delete = _tool_button(icons.delete_icon(), "Delete", acts.delete)
        self.audio = None
        self.mic = None
        if not hosted:
            # While it's on, a few library clips play at once with only their
            # sound — something to work over, tied to nothing on screen.
            self.audio = _tool_button(
                icons.audio_icon(),
                f"Play {AMBIENT_AUDIO_VOICES} library clips at once, sound only, "
                "shuffling endlessly",
                acts.toggle_audio, checkable=True,
            )
            self.audio.setStyleSheet(_LIT)
            # The microphone stands apart from the switches above: those are what
            # the app is doing, and Esc turns all of them off at once — the mic is
            # the one thing it leaves alone, since speaking is how any of them get
            # going again without the keyboard. On is listening, off is not.
            self.mic = _tool_button(
                icons.mic_icon(),
                "Listen: bare words for the shelves and this bank (“experiments”, "
                "“undo”, “star”), Fun Time's own words over a show (“next”, "
                "“weird”, “lock”), orders about the picture (“enhance”, “fix "
                "hands”, “genau it”), and prompt steering while a folder is "
                "auto-generating (left listening by Esc, which stops everything else)",
                acts.toggle_mic, checkable=True,
            )
            self.mic.setStyleSheet(_LIT)
        # One switch for the device, wearing the waveform: on means Origenerator
        # is driving the OSR2, and the app picks the source — the funscript of
        # whatever scripted video is in front, and a self-generated motion
        # whenever there is no script to follow. It used to be two buttons, which
        # asked the user to answer a question the app can answer for itself, and
        # let both sources be armed at once. Always visible (it's app-wide).
        self.drive = None
        if device:
            self.drive = _tool_button(
                icons.motion_icon(),
                "Drive the OSR2 — the funscript of the video in front, or a "
                f"self-generated motion when there is none ({MOTION_KEY_LEGEND}; "
                "Esc to stop)",
                acts.toggle_drive, checkable=True,
            )
            self.drive.setStyleSheet(_LIT)
        # The family's own gap along a row, and its wider one between wrapped
        # rows -- at the single small gap this used, a bank that wrapped had its
        # two rows all but touching.
        layout = FlowLayout(self, spacing=BUTTON_GAP, row_spacing=BUTTON_ROW_GAP)
        self._groups: list[tuple[QWidget, tuple[QToolButton, ...]]] = []
        for buttons in (
            (self.back, self.forward),               # where you are
            (self.undo, self.redo),                  # what you did
            (self.group,),                           # …to the picked folders
            (self.star, self.enhance, self.delete),  # …to what's in front
            (self.slideshow, self.auto,              # what the app is doing,
             self.audio, self.drive),                # and Esc stops
            (self.mic,),                             # what it hears with
        ):
            buttons = tuple(b for b in buttons if b is not None)
            gap = _group_gap()
            layout.addWidget(gap)
            for button in buttons:
                layout.addWidget(button)
            self._groups.append((gap, buttons))
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
            (self.star, state.star),
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
