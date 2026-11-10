from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QRect, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QToolButton
from shared_ui.colors import BG_PRIMARY
from shared_ui.reference import REFERENCE_WINDOW_TITLE, ReferenceDialog
from shared_ui.spacing import BUTTON_ICON_INSET, BUTTON_SIZE_HUD

from origenerator import ui_scale
from origenerator.gui import omnipause
from origenerator.gui.gallery_pane_buttons import (
    POPULATE_ELSEWHERE_TIP,
    Button,
    ButtonHandlers,
    ButtonStates,
    GalleryPaneButtons,
)
from origenerator.gui.stylesheet import build_stylesheet
from tests.lit_switches import lit_in


def _handlers(**overrides) -> ButtonHandlers:
    fields = {name: (lambda *a: None) for name in ButtonHandlers._fields}
    fields.update(overrides)
    return ButtonHandlers(**fields)


def _state(**overrides) -> ButtonStates:
    fields = {name: Button(tip=name) for name in ButtonStates._fields
              if name != "populate_tip"}
    fields["populate_tip"] = ""
    fields.update(overrides)
    return ButtonStates(**fields)


@pytest.fixture
def buttons(qtbot):
    def build(handlers=None, *, hosted=False):
        made = GalleryPaneButtons(handlers or _handlers(), hosted=hosted)
        qtbot.addWidget(made)
        return made
    return build


def test_the_room_s_own_appliances_are_absent_when_a_session_owns_them(buttons):
    hosted = buttons(hosted=True)

    assert hosted.radio is None
    assert hosted.mic is None
    assert buttons().radio is not None


def test_the_row_holds_no_osr2_switch_at_all(buttons):
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
    switch = buttons().radio
    omnipause.freeze(True)

    lit = switch.icon().pixmap(QSize(48, 48), QIcon.Mode.Normal, QIcon.State.On).toImage()
    inked = [lit.pixelColor(x, y) for y in range(lit.height()) for x in range(lit.width())
             if lit.pixelColor(x, y).alpha() == 255]

    assert inked
    assert all(color == BG_PRIMARY for color in inked), (
        "the family's yellow is light, so a mark on it takes the dark ink a lit yellow control "
        "on a HUD does")


def test_the_radio_switch_off_looks_the_same_in_a_paused_room_as_in_a_playing_one(buttons):
    switch = buttons().radio
    playing = switch.grab().toImage()

    omnipause.freeze(True)

    assert switch.grab().toImage() == playing


def test_the_bank_opens_with_its_optional_buttons_away(buttons):
    made = buttons()

    assert made.slideshow.isHidden()
    assert made.group.isHidden()
    assert not made.populate.isHidden(), (
        "never hidden: Populate runs until it is stopped, and a switch that went away with its "
        "folder would leave it running with nothing on screen to say so")


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
    pressed = []
    made = buttons(_handlers(toggle_populate=pressed.append))

    made.apply(_state(populate=Button(checked=True, tip="running here")))

    assert made.populate.isChecked() is True
    assert pressed == []


def test_a_state_that_says_nothing_about_a_switch_leaves_it_as_the_user_set_it(buttons):
    made = buttons()
    made.populate.setChecked(True)

    made.apply(_state())

    assert made.populate.isChecked() is True


def test_populate_running_elsewhere_shows_the_clickable_tip_and_no_tooltip(buttons):
    made = buttons()

    made.apply(_state(populate=Button(tip=""), populate_tip=POPULATE_ELSEWHERE_TIP))

    assert made.populate.toolTip() == ""
    assert "Go to it" in made.populate_tip._html, (
        "naming the folder is no use when its name is a short code, so the tip offers to go "
        "there instead")


def test_the_tip_s_link_leads_wherever_populate_is_now(buttons):
    followed = []
    made = buttons(_handlers(go_to_populating_folder=followed.append))

    made.populate_tip.link_activated.emit("populate")

    assert followed == ["populate"]


def test_a_group_with_nothing_showing_wears_no_gap(buttons):
    made = buttons()

    made.apply(_state(group=Button(visible=False), slideshow=Button(visible=False)))

    gaps = [gap.isVisible() for gap, buttons in made._groups]
    assert gaps[0] is False
    assert gaps[2] is False


def test_the_first_group_that_shows_is_the_one_left_unindented(buttons):
    made = buttons()
    made.show()

    made.apply(_state(back=Button(visible=False), forward=Button(visible=False)))

    gaps = [gap.isVisible() for gap, buttons in made._groups]
    assert gaps[0] is False
    assert gaps[1] is False
    assert gaps[3] is True


def test_every_button_presses_its_own_handler(buttons):
    pressed = []
    made = buttons(_handlers(
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
    made = buttons(_handlers(toggle_radio=heard.append))

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
    made = buttons()
    assert made.group.toolTip() == "Group the selected folders into a collection of your own", (
        "a folder the user gathers is a custom collection, the user's own word for it, so the "
        "button that makes one says collection")


def test_the_play_pause_button_asks_the_room_to_pause_or_play(buttons):
    asked = []
    made = buttons(_handlers(pause_or_play=lambda: asked.append(True)))

    made.play_pause.click()

    assert asked == [True]


def test_the_play_pause_button_shows_what_a_press_would_do_as_fun_times_does(buttons):
    made = buttons()
    assert made.play_pause.toolTip() == "Pause everything"

    omnipause.freeze(True)
    assert made.play_pause.toolTip() == "Play everything"

    omnipause.freeze(False)
    assert made.play_pause.toolTip() == "Pause everything"


def test_the_play_pause_button_is_lit_exactly_while_everything_plays(buttons):
    made = buttons()
    assert made.play_pause.isChecked()

    omnipause.freeze(True)
    assert not made.play_pause.isChecked()

    made.play_pause.click()
    assert not made.play_pause.isChecked()


def test_the_power_button_quits(buttons):
    asked = []
    made = buttons(_handlers(quit=lambda: asked.append(True)))

    made.power.click()

    assert asked == [True]
    assert made.power.toolTip() == "Quit"


def test_a_session_s_own_power_and_play_pause_buttons_stand_in_for_the_room_s(buttons):
    taken = buttons()

    taken.become_hosted()
    assert taken.play_pause is None
    assert taken.power is None
    assert buttons(hosted=True).play_pause is None
    assert buttons(hosted=True).power is None

    taken.become_standalone()
    assert not taken.play_pause.isHidden()
    assert not taken.power.isHidden()


def test_the_question_mark_opens_the_reference_lit_blue_and_closing_the_reference_darkens_it(buttons):
    made = buttons()
    assert made.reference.toolTip() == REFERENCE_WINDOW_TITLE

    made.reference.click()
    [opened] = [window for window in QApplication.topLevelWidgets()
                if isinstance(window, ReferenceDialog) and window.isVisible()]
    assert made.reference.isChecked()

    opened.close()
    assert not made.reference.isChecked()

    made.reference.click()
    made.reference.click()
    assert not any(isinstance(window, ReferenceDialog) and window.isVisible()
                   for window in QApplication.topLevelWidgets())


def test_a_session_s_own_reference_stands_in_for_the_room_s(buttons):
    assert buttons(hosted=True).reference is None
