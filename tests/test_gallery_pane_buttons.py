"""The Gallery pane buttons, written from one state and read with no gallery around it.

Every button's enabled state, tooltip and visibility used to be recomputed by a
method of its own, and the only way to ask how the Gallery pane buttons stood was to build the
app's central widget and read sixteen widgets off it. The state is a plain record
now, so a test writes one by hand.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QToolButton
from shared_ui.colors import BG_PRIMARY
from shared_ui.spacing import BUTTON_ICON_INSET, BUTTON_SIZE_HUD

from origenerator import ui_scale
from origenerator.gui import omnipause
from origenerator.gui.gallery_pane_buttons import (
    AUTO_ELSEWHERE_TIP,
    Button,
    ButtonActs,
    ButtonStates,
    GalleryPaneButtons,
)
from origenerator.gui.stylesheet import build_stylesheet
from tests.lit_switches import lit_in


def _acts(**overrides) -> ButtonActs:
    """Handlers that record rather than act, so a press is observable."""
    fields = {name: (lambda *a: None) for name in ButtonActs._fields}
    fields.update(overrides)
    return ButtonActs(**fields)


def _state(**overrides) -> ButtonStates:
    """A row of buttons standing wholly available, with the parts a test cares about
    overridden."""
    fields = {name: Button(tip=name) for name in ButtonStates._fields
              if name != "auto_tip"}
    fields["auto_tip"] = ""
    fields.update(overrides)
    return ButtonStates(**fields)


@pytest.fixture
def buttons(qtbot):
    def build(acts=None, *, hosted=False):
        made = GalleryPaneButtons(acts or _acts(), hosted=hosted)
        qtbot.addWidget(made)
        return made
    return build


def test_the_room_s_own_appliances_are_absent_when_a_session_owns_them(buttons):
    hosted = buttons(hosted=True)

    assert hosted.radio is None
    assert hosted.mic is None
    assert buttons().radio is not None


def test_the_row_holds_no_osr2_switch_at_all(buttons):
    # The Funestras' console carries the control-state group that switches the
    # device now -- parked, retracted, driving, control off -- and a second
    # switch for one device is what that group replaced.
    assert not hasattr(buttons(), "drive")


def test_a_bank_taken_into_a_session_stands_as_a_hosted_one_is_built(buttons):
    taken = buttons()
    built_hosted = buttons(hosted=True)

    taken.become_hosted()

    def shown(made):
        return sorted(button.toolTip() for button in made.findChildren(QToolButton)
                      if not button.isHidden())

    assert taken.radio is None
    assert taken.mic is None
    assert shown(taken) == shown(built_hosted)


def test_a_bank_handed_back_from_a_session_has_its_room_switches_again(buttons):
    taken = buttons()
    taken.become_hosted()

    taken.become_standalone()

    assert all(switch is not None and not switch.isHidden()
               for switch in (taken.radio, taken.mic))


def test_the_radio_switch_turned_on_in_a_paused_room_is_lit_yellow_at_once(buttons):
    switch = buttons().radio
    omnipause.freeze(True)

    switch.setChecked(True)

    assert lit_in(switch) == "yellow"


def test_the_radio_switch_lit_in_a_paused_room_draws_its_mark_dark_on_the_yellow(buttons):
    """The family's yellow is light, so a mark on it takes the dark ink a lit yellow
    control on a HUD does."""
    switch = buttons().radio
    omnipause.freeze(True)

    lit = switch.icon().pixmap(QSize(48, 48), QIcon.Mode.Normal, QIcon.State.On).toImage()
    inked = [lit.pixelColor(x, y) for y in range(lit.height()) for x in range(lit.width())
             if lit.pixelColor(x, y).alpha() == 255]

    assert inked
    assert all(color == BG_PRIMARY for color in inked)


def test_the_radio_switch_off_looks_the_same_in_a_paused_room_as_in_a_playing_one(buttons):
    switch = buttons().radio
    playing = switch.grab().toImage()

    omnipause.freeze(True)

    assert switch.grab().toImage() == playing


def test_the_bank_opens_with_its_optional_buttons_away(buttons):
    # Auto-Generate runs until it is stopped, so Auto is never hidden; the slideshow and
    # the grouping are offered only where they mean something.
    made = buttons()

    assert made.slideshow.isHidden()
    assert made.group.isHidden()
    assert not made.auto.isHidden()


def test_one_state_writes_every_button(buttons):
    made = buttons()

    made.apply(_state(
        back=Button(enabled=False, tip="Back"),
        undo=Button(tip="Undo: delete of 2 items"),
        delete=Button(enabled=False, tip="Nothing to delete"),
        slideshow=Button(visible=True, tip="Play Latest as a slideshow"),
    ))

    assert made.back.isEnabled() is False
    assert made.undo.toolTip() == "Undo: delete of 2 items"
    assert made.delete.isEnabled() is False
    assert made.delete.toolTip() == "Nothing to delete"
    assert made.slideshow.toolTip() == "Play Latest as a slideshow"


def test_a_switch_put_where_the_app_already_is_does_not_re_run_the_press(buttons):
    # Blocked around the write, not around the press: a row of buttons re-aimed while
    # Auto-Generate is running must not toggle it off.
    pressed = []
    made = buttons(_acts(toggle_auto=pressed.append))

    made.apply(_state(auto=Button(checked=True, tip="running here")))

    assert made.auto.isChecked() is True
    assert pressed == []


def test_a_state_that_says_nothing_about_a_switch_leaves_it_as_the_user_set_it(buttons):
    made = buttons()
    made.auto.setChecked(True)

    made.apply(_state())  # auto's `checked` is None

    assert made.auto.isChecked() is True


def test_auto_generate_running_elsewhere_shows_the_clickable_tip_and_no_tooltip(buttons):
    # Only one of the two ever appears: naming the folder is no use when a name
    # is a short code, so the tip offers to go there instead.
    made = buttons()

    made.apply(_state(auto=Button(tip=""), auto_tip=AUTO_ELSEWHERE_TIP))

    assert made.auto.toolTip() == ""
    assert "Go to it" in made.auto_tip._html


def test_the_tip_s_link_leads_wherever_auto_generate_is_now(buttons):
    followed = []
    made = buttons(_acts(go_to_auto_generating_folder=followed.append))

    made.auto_tip.link_activated.emit("auto")

    assert followed == ["auto"]


def test_a_group_with_nothing_showing_wears_no_gap(buttons):
    # A row whose optional buttons are away must never wear a stray or doubled
    # gap, and must never start indented.
    made = buttons()

    made.apply(_state(group=Button(visible=False), slideshow=Button(visible=False)))

    gaps = [gap.isVisible() for gap, buttons in made._groups]
    assert gaps[0] is False            # the leading group is never indented
    assert gaps[2] is False            # the grouping is away, so its space is too


def test_the_first_group_that_shows_is_the_one_left_unindented(buttons):
    made = buttons()
    made.show()

    made.apply(_state(back=Button(visible=False), forward=Button(visible=False)))

    gaps = [gap.isVisible() for gap, buttons in made._groups]
    assert gaps[0] is False
    assert gaps[1] is False
    assert gaps[3] is True                        # a space in front of the trio


def test_every_button_presses_its_own_handler(buttons):
    pressed = []
    made = buttons(_acts(
        go_back=lambda: pressed.append("back"),
        undo=lambda: pressed.append("undo"),
        favorite=lambda: pressed.append("star"),
        delete=lambda: pressed.append("delete"),
    ))

    made.back.click()
    made.undo.click()
    made.favorite.click()
    made.delete.click()

    assert pressed == ["back", "undo", "star", "delete"]


def test_a_switch_hands_its_handler_the_state_it_landed_in(buttons):
    heard = []
    made = buttons(_acts(toggle_radio=heard.append))

    made.radio.setChecked(True)
    made.radio.setChecked(False)

    assert heard == [True, False]


def _every_button_showing_as_the_app_styles_it(buttons) -> GalleryPaneButtons:
    made = buttons()
    made.setStyleSheet(build_stylesheet())
    made.apply(_state())
    made.show()
    made.layout().activate()
    return made


def _where_the_mark_lands(button: QToolButton) -> QRect:
    worn = button.grab().toImage()
    icon = button.icon()
    button.setIcon(QIcon())
    bare = button.grab().toImage()
    button.setIcon(icon)
    inked = [(x, y) for y in range(worn.height()) for x in range(worn.width())
             if worn.pixel(x, y) != bare.pixel(x, y)]
    xs, ys = [x for x, _ in inked], [y for _, y in inked]
    return QRect(QPoint(min(xs), min(ys)), QPoint(max(xs), max(ys)))


def test_every_button_on_a_standalone_row_is_the_huds_square(buttons):
    made = _every_button_showing_as_the_app_styles_it(buttons)

    for button in made.findChildren(QToolButton):
        assert button.size() == QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD), button.toolTip()


def test_a_hosted_banks_buttons_land_on_screen_the_size_a_standalone_rows_do(buttons):
    hosted = buttons(hosted=True)

    for button in hosted.findChildren(QToolButton):
        drawn = QSize(round(button.width() * ui_scale.HOSTED_SCALE),
                      round(button.height() * ui_scale.HOSTED_SCALE))
        assert drawn == QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD), button.toolTip()


def _gaps(made: GalleryPaneButtons) -> tuple[int, int, int]:
    """Between two buttons of a group, between wrapped rows, and between groups."""
    layout = made.layout()
    return layout.spacing(), layout.row_spacing(), made._groups[0][0].width()


def test_a_standalone_banks_gaps_land_on_screen_the_size_a_hosted_rows_do(buttons):
    standalone, hosted = buttons(), buttons(hosted=True)

    assert _gaps(standalone) == tuple(
        round(gap * ui_scale.HOSTED_SCALE) for gap in _gaps(hosted))


def test_a_bank_taken_into_a_session_wears_the_squares_a_hosted_one_is_built_with(buttons):
    taken = buttons()
    built_hosted = buttons(hosted=True)

    taken.become_hosted()

    assert {button.size() for button in taken.findChildren(QToolButton)} == {
        button.size() for button in built_hosted.findChildren(QToolButton)}
    assert _gaps(taken) == _gaps(built_hosted)


def test_a_bank_handed_back_from_a_session_wears_the_huds_square_again(buttons):
    taken = buttons()
    taken.become_hosted()

    taken.become_standalone()

    assert {button.size() for button in taken.findChildren(QToolButton)} == {
        QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD)}
    assert _gaps(taken) == _gaps(buttons())


def test_every_mark_on_the_row_spans_more_than_half_its_button(buttons):
    made = _every_button_showing_as_the_app_styles_it(buttons)

    for button in made.findChildren(QToolButton):
        mark = _where_the_mark_lands(button)
        assert max(mark.width(), mark.height()) > button.height() / 2, button.toolTip()


def test_every_mark_on_the_row_stays_inside_the_familys_inset(buttons):
    made = _every_button_showing_as_the_app_styles_it(buttons)

    for button in made.findChildren(QToolButton):
        room = button.rect().adjusted(BUTTON_ICON_INSET, BUTTON_ICON_INSET,
                                      -BUTTON_ICON_INSET, -BUTTON_ICON_INSET)
        assert room.contains(_where_the_mark_lands(button)), button.toolTip()


def test_the_group_button_offers_a_collection_of_his_own(buttons):
    # A folder he gathers himself is a custom collection (2026-10-30), and the
    # button that makes one says collection where it used to say folder.
    made = buttons()
    assert made.group.toolTip() == "Group the selected folders into a collection of your own"
