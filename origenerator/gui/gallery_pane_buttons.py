from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtWidgets import QToolButton, QWidget
from shared_ui.colors import BG_PRIMARY
from shared_ui.flow_layout import FlowLayout
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.palette import BLUE, YELLOW, as_hex
from shared_ui.reference import REFERENCE_WINDOW_TITLE
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
from origenerator.gui.link_tip import LinkTip, link
from origenerator.gui.reference_window import ReferenceWindow
from origenerator.gui.two_screens import LEFT, TwoScreens


def _lit(color: str) -> str:
    return f"QToolButton:checked {{ background-color: {color}; border-radius: {BUTTON_RADIUS}px; }}"


_LIT = _lit(as_hex(BLUE))
_LIT_WHILE_THE_ROOM_IS_PAUSED = _lit(as_hex(YELLOW))

GROUP_TIP = "Group the selected folders into a collection of your own"
POPULATE_ELSEWHERE_TIP = (
    "Populate is running in another folder<br>"
    f"{link('populate', 'Go to it')} · click the switch to stop it"
)


class Button(NamedTuple):
    enabled: bool = True
    visible: bool = True
    tip: str = ""
    checked: bool | None = None


class OfferedPress:
    def __init__(self, offer: Callable[[], Button]):
        self._offer = offer

    def isHidden(self) -> bool:  # noqa: N802 -- read where a QToolButton's is
        return not self._offer().visible

    def isEnabled(self) -> bool:  # noqa: N802 -- read where a QToolButton's is
        return self._offer().enabled

    def toolTip(self) -> str:  # noqa: N802 -- read where a QToolButton's is
        return self._offer().tip


class ButtonStates(NamedTuple):
    back: Button
    forward: Button
    undo: Button
    redo: Button
    group: Button
    favorite: Button
    enhance: Button
    delete: Button
    slideshow: Button
    populate: Button
    populate_tip: str = ""


class ButtonHandlers(NamedTuple):
    go_back: Callable[[], None]
    go_forward: Callable[[], None]
    undo: Callable[[], None]
    redo: Callable[[], None]
    start_slideshow: Callable[[], None]
    toggle_populate: Callable[[bool], None]
    go_to_populating_folder: Callable[[str], None]
    favorite: Callable[[bool], None]
    enhance: Callable[[bool], None]
    group: Callable[[], None]
    delete: Callable[[], None]
    toggle_radio: Callable[[bool], None]
    toggle_mic: Callable[[bool], None]
    pause_or_play: Callable[[], None]
    quit: Callable[[], None]


class _AudioSwitch(QToolButton):
    def set_frozen(self, frozen: bool) -> None:
        self.setStyleSheet(_LIT_WHILE_THE_ROOM_IS_PAUSED if frozen else _LIT)
        self.setIcon(icons.radio_icon(lit_ink=BG_PRIMARY if frozen else None))


class _PlayPause(QToolButton):
    def nextCheckState(self) -> None:
        pass

    def set_frozen(self, frozen: bool) -> None:
        self.setChecked(not frozen)
        self.setIcon(icons.play_icon() if frozen else icons.pause_icon())
        self.setToolTip("Play everything" if frozen else "Pause everything")


def _tool_button(icon, tooltip: str, handler, *, checkable=False,
                 kind=QToolButton) -> QToolButton:
    btn = kind()
    btn.setIcon(icon)
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    (btn.toggled if checkable else btn.clicked).connect(handler)
    return btn


def _lit_switch(icon, tooltip: str, handler) -> QToolButton:
    switch = _tool_button(icon, tooltip, handler, checkable=True)
    switch.setStyleSheet(_LIT)
    return switch


def _reference_button() -> QToolButton:
    button = QToolButton()
    button.setIcon(icons.question_icon())
    button.setToolTip(REFERENCE_WINDOW_TITLE)
    button.setCheckable(True)
    button.setStyleSheet(_LIT)
    ReferenceWindow(button)
    return button


class GalleryPaneButtons(QWidget):
    def __init__(self, handlers: ButtonHandlers, *, hosted: bool,
                 two_screens: TwoScreens | None = None):
        super().__init__()
        self._two_screens = two_screens or TwoScreens(self)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)  # Qt's column above gives it the rows it asks for only with this
        self.setSizePolicy(policy)
        self.back = _tool_button(icons.back_icon(), "Back", handlers.go_back)
        self.forward = _tool_button(icons.forward_icon(), "Forward", handlers.go_forward)
        self.undo = _tool_button(icons.undo_icon(), "Undo", handlers.undo)
        self.redo = _tool_button(icons.redo_icon(), "Redo", handlers.redo)
        self.slideshow = _tool_button(
            icons.slideshow_icon(), "Play this folder as a slideshow",
            handlers.start_slideshow)
        self.slideshow.hide()
        self.populate = _lit_switch(
            icons.populate_icon(),
            "Populate: repeatedly generate variations of this folder until "
            "toggled off",
            handlers.toggle_populate,
        )
        self.populate_tip = LinkTip(self.populate)
        self.populate_tip.link_activated.connect(handlers.go_to_populating_folder)
        self.favorite = _lit_switch(icons.star_switch_icon(), "Favorite", handlers.favorite)
        self.enhance = _lit_switch(icons.enhance_icon(), "Enhance", handlers.enhance)
        self.group = _tool_button(
            icons.custom_collection_icon(), GROUP_TIP, handlers.group)
        self.group.hide()
        self.delete = _tool_button(icons.delete_icon(), "Delete", handlers.delete)
        self.radio = None
        self.mic = None
        self.play_pause = None
        self.power = None
        self.reference = None
        self.switch = None
        if not hosted:
            self.power = _tool_button(icons.power_icon(), "Quit", handlers.quit)
            self.play_pause = _tool_button(icons.pause_icon(), "", handlers.pause_or_play,
                                           kind=_PlayPause)
            self.play_pause.setCheckable(True)
            self.play_pause.setStyleSheet(_LIT)
            omnipause.holds(self.play_pause)
            self.reference = _reference_button()
            self.radio = _tool_button(
                icons.radio_icon(),
                f"Origenerator Radio: play {RADIO_STATIONS} library videos at once, "
                "audio only, shuffling endlessly",
                handlers.toggle_radio, checkable=True, kind=_AudioSwitch,
            )
            omnipause.holds(self.radio)
            self.mic = _lit_switch(
                icons.mic_icon(),
                "Listen: bare words for the collections and this bank (“experiments”, "
                "“undo”, “star”), Fun Time's own words over a slideshow (“next”, "
                "“trash”, “lock”), and orders about the image (“enhance”, “fix "
                "hands”, “animate as kino”)",
                handlers.toggle_mic,
            )
            self.switch = self._switch_between_the_monitors()
        layout = FlowLayout(self)
        self._groups: list[tuple[QToolButton, ...]] = []
        for listed in (
            (self.back, self.forward),
            (self.undo, self.redo),
            (self.group,),
            (self.favorite, self.enhance, self.delete),
            (self.slideshow, self.populate, self.radio),
            (self.power, self.play_pause, self.reference, self.mic, self.switch),
        ):
            buttons = tuple(b for b in listed if b is not None)
            layout.add_group(buttons)
            self._groups.append(buttons)
        self._point_the_switch_where_core_would_move()
        self._draw_at_the_huds_scale(hosted=hosted)

    def _draw_at_the_huds_scale(self, *, hosted: bool) -> None:
        layout = self.layout()
        layout.setSpacing(ui_scale.landing_at_the_huds_scale(BUTTON_GAP, hosted=hosted))
        layout.set_row_spacing(ui_scale.landing_at_the_huds_scale(BUTTON_ROW_GAP, hosted=hosted))
        layout.set_group_spacing(ui_scale.landing_at_the_huds_scale(BUTTON_GROUP_GAP, hosted=hosted))
        square = ui_scale.landing_at_the_huds_scale(BUTTON_SIZE, hosted=hosted)
        for buttons in self._groups:
            for button in buttons:
                fill_square_with_icon(button, size=square)

    def become_hosted(self) -> None:
        self._draw_at_the_huds_scale(hosted=True)
        self._room_switches = (self.radio, self.mic, self.play_pause, self.power, self.reference,
                               self.switch)
        self._show_the_room_switches(False)
        self.radio = self.mic = self.play_pause = self.power = self.reference = None
        self.switch = None

    def become_standalone(self) -> None:
        self._draw_at_the_huds_scale(hosted=False)
        (self.radio, self.mic, self.play_pause, self.power, self.reference,
         self.switch) = self._room_switches
        self._show_the_room_switches(True)
        self._point_the_switch_where_core_would_move()

    def _switch_between_the_monitors(self) -> QToolButton:
        self._two_screens.switched.connect(self._point_the_switch_where_core_would_move)
        return _tool_button(icons.switch_icon(LEFT), "Switch Core and the slideshow",
                            self._two_screens.switch)

    def _point_the_switch_where_core_would_move(self) -> None:
        direction = self._two_screens.core_would_move()
        if self.switch is not None:
            self.switch.setVisible(direction is not None)
            self.switch.setIcon(icons.switch_icon(direction or LEFT))

    def turn_the_radio_on(self) -> None:
        if self.radio is not None:
            self.radio.setChecked(True)

    def _show_the_room_switches(self, shown: bool) -> None:
        for switch in self._room_switches:
            if switch is not None:
                switch.setVisible(shown)

    def apply(self, state: ButtonStates) -> None:
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
            (self.populate, state.populate),
        ):
            button.setEnabled(stands.enabled)
            button.setVisible(stands.visible)
            button.setToolTip(stands.tip)
            if stands.checked is not None and button.isChecked() != stands.checked:
                button.blockSignals(True)
                button.setChecked(stands.checked)
                button.blockSignals(False)
        self.populate_tip.set_html(state.populate_tip)
