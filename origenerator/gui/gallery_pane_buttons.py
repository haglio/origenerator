from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PyQt6.QtWidgets import QToolButton, QWidget
from shared_ui.colors import BG_PRIMARY
from shared_ui.icon_button import fill_square_with_icon
from shared_ui.palette import BLUE, YELLOW, as_hex
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


_LIT = _lit(as_hex(BLUE))
_LIT_WHILE_THE_ROOM_IS_PAUSED = _lit(as_hex(YELLOW))

AUTO_ELSEWHERE_TIP = (
    "Auto-generate is running in another folder<br>"
    f"{link('auto', 'Go to it')} · click the switch to stop it"
)


class Button(NamedTuple):
    enabled: bool = True
    visible: bool = True
    tip: str = ""
    checked: bool | None = None


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
    auto: Button
    auto_tip: str = ""


class ButtonHandlers(NamedTuple):
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
    pause_or_play: Callable[[], None]


def _landing_at_the_huds_scale(length: int, *, hosted: bool) -> int:
    return length if hosted else round(length * ui_scale.HOSTED_SCALE)


class _SoundSwitch(QToolButton):
    def set_frozen(self, frozen: bool) -> None:
        self.setStyleSheet(_LIT_WHILE_THE_ROOM_IS_PAUSED if frozen else _LIT)
        self.setIcon(icons.radio_icon(lit_ink=BG_PRIMARY if frozen else None))


class _PlayPause(QToolButton):
    def set_frozen(self, frozen: bool) -> None:
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


def _group_gap() -> QWidget:
    return QWidget()


class GalleryPaneButtons(QWidget):
    def __init__(self, handlers: ButtonHandlers, *, hosted: bool):
        super().__init__()
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
        self.auto = _tool_button(
            icons.auto_generate_icon(),
            "Auto-generate: repeatedly generate variations of this folder until "
            "toggled off",
            handlers.toggle_auto, checkable=True,
        )
        self.auto.setStyleSheet(_LIT)
        self.auto_tip = LinkTip(self.auto)
        self.auto_tip.link_activated.connect(handlers.go_to_auto_generating_folder)
        self.favorite = _tool_button(icons.star_icon(filled=True), "Favorite", handlers.favorite)
        self.enhance = _tool_button(icons.enhance_icon(), "Enhance", handlers.enhance)
        self.group = _tool_button(
            icons.custom_collection_icon(),
            "Group the selected folders into a collection of your own", handlers.group)
        self.group.hide()
        self.delete = _tool_button(icons.delete_icon(), "Delete", handlers.delete)
        self.radio = None
        self.mic = None
        self.play_pause = None
        if not hosted:
            self.play_pause = _tool_button(icons.pause_icon(), "", handlers.pause_or_play,
                                           kind=_PlayPause)
            omnipause.holds(self.play_pause)
            self.radio = _tool_button(
                icons.radio_icon(),
                f"Origenerator Radio: play {RADIO_STATIONS} library videos at once, "
                "sound only, shuffling endlessly",
                handlers.toggle_radio, checkable=True, kind=_SoundSwitch,
            )
            omnipause.holds(self.radio)
            self.mic = _tool_button(
                icons.mic_icon(),
                "Listen: bare words for the collections and this bank (“experiments”, "
                "“undo”, “star”), Fun Time's own words over a slideshow (“next”, "
                "“trash”, “lock”), and orders about the image (“enhance”, “fix "
                "hands”, “animate as kino”)",
                handlers.toggle_mic, checkable=True,
            )
            self.mic.setStyleSheet(_LIT)
        layout = FlowLayout(self)
        self._groups: list[tuple[QWidget, tuple[QToolButton, ...]]] = []
        for listed in (
            (self.play_pause,),
            (self.back, self.forward),
            (self.undo, self.redo),
            (self.group,),
            (self.favorite, self.enhance, self.delete),
            (self.slideshow, self.auto, self.radio),
            (self.mic,),
        ):
            buttons = tuple(b for b in listed if b is not None)
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
                fill_square_with_icon(button, size=square)

    def become_hosted(self) -> None:
        self._draw_at_the_huds_scale(hosted=True)
        self._room_switches = (self.radio, self.mic, self.play_pause)
        self._show_the_room_switches(False)
        self.radio = self.mic = self.play_pause = None

    def become_standalone(self) -> None:
        self._draw_at_the_huds_scale(hosted=False)
        self.radio, self.mic, self.play_pause = self._room_switches
        self._show_the_room_switches(True)

    def turn_the_radio_on(self) -> None:
        if self.radio is not None:
            self.radio.setChecked(True)

    def _show_the_room_switches(self, shown: bool) -> None:
        for switch in self._room_switches:
            if switch is not None:
                switch.setVisible(shown)
        self._show_the_gaps()

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
            (self.auto, state.auto),
        ):
            button.setEnabled(stands.enabled)
            button.setVisible(stands.visible)
            button.setToolTip(stands.tip)
            if stands.checked is not None and button.isChecked() != stands.checked:
                button.blockSignals(True)
                button.setChecked(stands.checked)
                button.blockSignals(False)
        self.auto_tip.set_html(state.auto_tip)
        self._show_the_gaps()

    def _show_the_gaps(self) -> None:
        leading = True
        for gap, buttons in self._groups:
            showing = any(not button.isHidden() for button in buttons)
            gap.setVisible(showing and not leading)
            leading = leading and not showing
