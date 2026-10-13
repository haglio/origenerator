"""CombinePanel: two drop slots + a Generate button for the image+video combine."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PyQt6.QtWidgets import QHBoxLayout
from shared_ui.colors import hovered
from shared_ui.spacing import BUTTON_GAP, BUTTON_GROUP_GAP
from shared_ui.testing import ground

from origenerator import recipe_match
from origenerator.gui.combine_panel import CombinePanel, CombineRequest
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.stylesheet import build_stylesheet

TOOLTIP = Qt.ItemDataRole.ToolTipRole


def _panel(qtbot, start_pictures=None):
    """Pictures are ``img*`` and videos ``vid*``; a video lends the image slot the
    picture ``start_pictures`` names for it, and nothing when it names none."""
    start_pictures = start_pictures or {}
    panel = CombinePanel(
        image_lent_by=lambda pid: pid if pid.startswith("img") else start_pictures.get(pid),
        video_lent_by=lambda pid: pid if pid.startswith("vid") else None,
        preview=lambda pid: (None, None),
    )
    qtbot.addWidget(panel)
    return panel


def _drag_over(zone, pid):
    # Hold the QMimeData in a local: the event keeps only a pointer to it.
    mime = generation_mime(pid)
    event = QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dragEnterEvent(event)
    return event


def _let_go_over(zone, pid):
    mime = generation_mime(pid)
    event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dropEvent(event)
    return event


def _under_the_drag(slot) -> bool:
    return slot._label.property("dropTarget")


def _pick_act(panel, act):
    """Choose an act in the dropdown, as a click on its row would; "" is the
    neutral "(custom)" and so is an act the list does not carry."""
    index = panel._category.findText(act)
    panel._category.setCurrentIndex(index if index >= 1 else 0)


def _pick_lane(panel, intent):
    """Click the lane's radio; the group's exclusivity releases the other."""
    radio = (panel._genau_radio if intent == recipe_match.GENAU
             else panel._video_radio)
    radio.setChecked(True)



def test_only_the_video_slot_is_drained_of_color(qtbot):
    # The video is here for its settings — never for what it looks like — while
    # the image is the very thing being animated.
    panel = _panel(qtbot)

    assert panel.video_slot._grayscale
    assert not panel.image_slot._grayscale


def test_generate_is_disabled_until_both_slots_are_filled(qtbot):
    panel = _panel(qtbot)
    assert not panel._generate_btn.isEnabled()

    panel.image_slot.set_item("img1")
    assert not panel._generate_btn.isEnabled()  # the video slot is still empty

    panel.video_slot.set_item("vid1")
    assert panel._generate_btn.isEnabled()       # both filled: ready


def test_grayed_generate_and_edit_say_what_they_still_need(qtbot):
    panel = _panel(qtbot)
    needs_image = "Nothing to start from — drop an image first"
    assert (panel._generate_btn.toolTip(), panel._open_btn.toolTip()) == (needs_image, needs_image)

    panel.image_slot.set_item("img1")

    needs_recipe = "Pick an act or drop a video first"
    assert (panel._generate_btn.toolTip(), panel._open_btn.toolTip()) == (needs_recipe, needs_recipe)


def test_once_ready_generate_drops_its_reason_and_edit_says_what_it_does(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")

    panel.video_slot.set_item("vid1")

    assert panel._generate_btn.toolTip() == ""
    assert panel._open_btn.toolTip() == (
        "Load this combination into a generate tab to edit before running it.")


def test_clicking_generate_asks_for_the_dropped_pair(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    got = []
    panel.combine_requested.connect(got.append)

    panel._generate_btn.click()

    assert got == [CombineRequest(image_id="img1", video_id="vid1",
                                  intent=recipe_match.VIDEO)]


def test_open_in_generator_button_tracks_the_same_enablement_as_generate(qtbot):
    # "Edit…" needs the same ingredients as Generate — a source image
    # and a recipe — so it lights and dims in lockstep with the Generate button.
    panel = _panel(qtbot)
    assert not panel._open_btn.isEnabled()

    panel.image_slot.set_item("img1")
    assert not panel._open_btn.isEnabled()  # image alone, no recipe yet

    panel.video_slot.set_item("vid1")
    assert panel._open_btn.isEnabled()       # both filled: ready to open


@pytest.mark.parametrize("name", ["_generate_btn", "_open_btn"], ids=["Generate", "Edit"])
def test_a_ready_button_sits_one_step_lighter_under_the_pointer(qtbot, pointer, name):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    panel.setStyleSheet(build_stylesheet())
    panel.show()
    qtbot.waitExposed(panel)
    button = getattr(panel, name)
    pointer.off(button)
    at_rest = ground(button)
    pointer.on(button)

    assert ground(button) == hovered(QColor(at_rest)).name()


def test_clicking_open_emits_the_dropped_recipe_for_the_generator(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    opened = []
    panel.combine_requested.connect(opened.append)

    panel._open_btn.click()

    # The same pair Generate would ask for, marked as bound for the generator.
    assert opened == [CombineRequest(image_id="img1", video_id="vid1",
                                     intent=recipe_match.VIDEO, edit_first=True)]


def test_clicking_open_with_a_picked_act_emits_the_category(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "delta")
    opened = []
    panel.combine_requested.connect(opened.append)

    panel._open_btn.click()

    assert opened == [CombineRequest(image_id="img1", category="delta",
                                     intent=recipe_match.VIDEO, edit_first=True)]


def test_show_drop_candidates_lights_only_the_matching_slot(qtbot):
    panel = _panel(qtbot)  # image slot accepts img*, video slot accepts vid*

    panel.show_drop_candidates("img7")
    assert panel.image_slot._label.property("dragActive") is True
    assert panel.video_slot._label.property("dragActive") is False

    panel.show_drop_candidates("vid7")  # a video now: the other slot lights instead
    assert panel.image_slot._label.property("dragActive") is False
    assert panel.video_slot._label.property("dragActive") is True

    panel.clear_drop_candidates()
    assert panel.image_slot._label.property("dragActive") is False
    assert panel.video_slot._label.property("dragActive") is False


def test_a_video_let_go_between_the_slots_lands_in_both(qtbot):
    panel = _panel(qtbot, start_pictures={"vid1": "img1"})

    _let_go_over(panel._between, "vid1")

    assert panel.image_slot.current_id() == "img1"  # the picture the video was made from
    assert panel.video_slot.current_id() == "vid1"


def test_a_video_over_the_room_between_the_slots_lights_both(qtbot):
    panel = _panel(qtbot, start_pictures={"vid1": "img1"})

    assert _drag_over(panel._between, "vid1").isAccepted()
    assert _under_the_drag(panel.image_slot) and _under_the_drag(panel.video_slot)

    panel._between.dragLeaveEvent(QDragLeaveEvent())
    assert not _under_the_drag(panel.image_slot) and not _under_the_drag(panel.video_slot)


def test_letting_go_between_the_slots_puts_both_out(qtbot):
    panel = _panel(qtbot, start_pictures={"vid1": "img1"})
    _drag_over(panel._between, "vid1")

    _let_go_over(panel._between, "vid1")

    assert not _under_the_drag(panel.image_slot) and not _under_the_drag(panel.video_slot)


def test_between_the_slots_a_video_lands_only_where_it_lends_something(qtbot):
    panel = _panel(qtbot)  # the gallery holds no picture vid7 was made from

    _drag_over(panel._between, "vid7")
    assert not _under_the_drag(panel.image_slot) and _under_the_drag(panel.video_slot)

    _let_go_over(panel._between, "vid7")
    assert panel.image_slot.current_id() is None
    assert panel.video_slot.current_id() == "vid7"


def test_a_picture_let_go_between_the_slots_lands_in_the_image_slot(qtbot):
    panel = _panel(qtbot)

    _let_go_over(panel._between, "img1")

    assert panel.image_slot.current_id() == "img1"
    assert panel.video_slot.current_id() is None


def test_what_lends_neither_slot_anything_cannot_be_let_go_between_them(qtbot):
    panel = _panel(qtbot)

    assert not _drag_over(panel._between, "elsewhere").isAccepted()
    assert not _let_go_over(panel._between, "elsewhere").isAccepted()


def test_with_an_act_picked_the_room_between_reaches_only_the_image_slot(qtbot):
    # The video slot is hidden under an act, so nothing shows it as a target.
    panel = _panel(qtbot, start_pictures={"vid1": "img1"})
    _pick_act(panel, "alpha")

    _let_go_over(panel._between, "vid1")

    assert panel.image_slot.current_id() == "img1"
    assert panel.video_slot.current_id() is None
    assert panel.selected_category() == "alpha"


def test_the_room_between_the_slots_is_the_whole_gap_that_parts_them(qtbot):
    panel = _panel(qtbot)
    panel.setStyleSheet(build_stylesheet())
    panel.show()
    qtbot.waitExposed(panel)

    between = panel._between.geometry()
    assert between.top() == panel.image_slot.geometry().bottom() + 1
    assert between.bottom() + 1 == panel._video_part.geometry().top()
    # As far apart as a group's gap set them in this column before it took drops.
    assert between.height() == BUTTON_GAP + BUTTON_GROUP_GAP


def test_the_neutral_option_is_custom_leading_the_acts(qtbot):
    panel = _panel(qtbot)
    assert panel.selected_category() == ""  # neutral by default
    items = [panel._category.itemText(i) for i in range(panel._category.count())]
    assert items[0] == "(custom)"
    assert items[1:] == list(recipe_match.CATEGORIES)   # the six acts follow it


def _enabled(panel, text) -> bool:
    return panel._category.model().item(panel._category.findText(text)).isEnabled()


def test_acts_with_no_video_to_mine_are_greyed_out(qtbot):
    panel = _panel(qtbot)

    panel.set_available_categories({"beta", "epsilon"})

    assert _enabled(panel, "beta") and _enabled(panel, "epsilon")
    assert not _enabled(panel, "gamma")  # nothing in the gallery to build a recipe from
    assert not _enabled(panel, "dancing")
    assert _enabled(panel, "(custom)")     # the neutral option always stays pickable


def test_an_act_becomes_pickable_once_a_video_of_it_exists(qtbot):
    panel = _panel(qtbot)
    panel.set_available_categories(set())
    assert not _enabled(panel, "dancing")

    panel.set_available_categories({"dancing"})  # the user just made one

    assert _enabled(panel, "dancing")


def test_a_greyed_act_explains_itself(qtbot):
    panel = _panel(qtbot)
    panel.set_available_categories({"beta"})
    index = panel._category.findText("gamma")
    assert "no past" in panel._category.itemData(index, TOOLTIP).lower()
    assert not panel._category.itemData(panel._category.findText("beta"), TOOLTIP)


def test_dropdown_sits_beside_the_video_slot_in_one_part(qtbot):
    panel = _panel(qtbot)
    # The dropdown configures the *video* recipe, so it shares one container with the
    # video slot — laid out side by side, not stacked, and not a peer of the image.
    assert panel._category.parent() is panel.video_slot.parent()
    assert panel.image_slot.parent() is not panel.video_slot.parent()
    assert isinstance(panel._category.parent().layout(), QHBoxLayout)


def test_a_picked_category_enables_generate_with_only_an_image(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    assert not panel._generate_btn.isEnabled()  # image alone, no recipe chosen yet

    _pick_act(panel, "alpha")
    assert panel._generate_btn.isEnabled()      # a category is a recipe — no video needed

    _pick_act(panel, "")                       # back to neutral
    assert not panel._generate_btn.isEnabled()


def test_picking_an_act_clears_the_dropped_video_without_collapsing(qtbot):
    panel = _panel(qtbot)
    panel.video_slot.set_item("vid1")
    height = panel._video_part.sizeHint().height()

    _pick_act(panel, "alpha")

    assert panel.video_slot.current_id() is None  # the act supersedes it, so the video is dropped
    assert panel._video_part.sizeHint().height() == height  # hidden, but its room stays put


def test_going_back_to_custom_brings_back_the_video_the_act_replaced(qtbot):
    panel = _panel(qtbot)
    panel.video_slot.set_item("vid1")
    _pick_act(panel, "alpha")

    _pick_act(panel, "")

    assert panel.video_slot.current_id() == "vid1"


def test_a_remembered_video_that_no_longer_fits_its_slot_is_not_brought_back(qtbot):
    fitting = {"vid1"}
    panel = CombinePanel(image_lent_by=lambda pid: pid,
                         video_lent_by=lambda pid: pid if pid in fitting else None,
                         preview=lambda pid: (None, None))
    qtbot.addWidget(panel)
    panel.video_slot.set_item("vid1")
    _pick_act(panel, "alpha")
    fitting.clear()  # binned while the act was picked

    _pick_act(panel, "")

    assert panel.video_slot.current_id() is None


def test_each_lane_keeps_its_own_dropped_video(qtbot):
    panel = _panel(qtbot)
    panel.video_slot.set_item("vid1")
    _pick_lane(panel, recipe_match.GENAU)
    assert panel.video_slot.current_id() is None
    panel.video_slot.set_item("vid2")

    _pick_lane(panel, recipe_match.VIDEO)
    assert panel.video_slot.current_id() == "vid1"

    _pick_lane(panel, recipe_match.GENAU)
    assert panel.video_slot.current_id() == "vid2"


def test_dropping_a_video_resets_the_dropdown_to_neutral(qtbot):
    panel = _panel(qtbot)
    _pick_act(panel, "delta")

    panel.video_slot.set_item("vid1")

    assert panel.selected_category() == ""          # a dropped video wipes the act back to "(custom)"
    assert panel.video_slot.current_id() == "vid1"  # ...and the video is what's kept


def test_the_video_slot_shows_only_while_custom_is_picked(qtbot):
    panel = _panel(qtbot)
    assert not panel.video_slot.isHidden()

    _pick_act(panel, "gamma")
    assert panel.video_slot.isHidden()

    _pick_act(panel, "")
    assert not panel.video_slot.isHidden()


def test_generate_emits_the_picked_act(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "delta")
    cats = []
    panel.combine_requested.connect(cats.append)

    panel._generate_btn.click()

    assert cats == [CombineRequest(image_id="img1", category="delta",
                                   intent=recipe_match.VIDEO)]


# --- the Video/Genau radio: what the result is for ----------------------------


def test_the_lane_defaults_to_video(qtbot):
    # The long-standing behavior of this panel, and by far the more common ask, so
    # the Genau flick is the deliberate detour rather than the default.
    panel = _panel(qtbot)
    assert panel.selected_intent() == recipe_match.VIDEO
    assert panel._video_radio.text() == "Video"
    assert panel._video_radio.isChecked()
    assert not panel._genau_radio.isChecked()


def _top_to_bottom(layout):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.layout() is not None:
            yield from _top_to_bottom(item.layout())
        elif item.widget() is not None:
            yield item.widget()


def test_the_radio_sits_below_the_dropdown_it_changes(qtbot):
    panel = _panel(qtbot)
    order = list(_top_to_bottom(panel.layout()))
    assert order.index(panel._intent_part) == order.index(panel._video_part) + 1


def test_generate_carries_the_chosen_lane(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "delta")
    _pick_lane(panel, recipe_match.GENAU)
    cats = []
    panel.combine_requested.connect(cats.append)

    panel._generate_btn.click()

    assert cats == [CombineRequest(image_id="img1", category="delta",
                                   intent=recipe_match.GENAU)]


def test_switching_the_lane_announces_it_once(qtbot):
    # buttonToggled fires for both radios on one click — the off edge and the on
    # edge — and the view answers each by re-greying the whole act list.
    panel = _panel(qtbot)
    heard = []
    panel.intent_changed.connect(heard.append)

    _pick_lane(panel, recipe_match.GENAU)
    assert heard == [recipe_match.GENAU]

    _pick_lane(panel, recipe_match.VIDEO)
    assert heard == [recipe_match.GENAU, recipe_match.VIDEO]


def test_a_greyed_act_explains_itself_in_the_lanes_own_terms(qtbot):
    panel = _panel(qtbot)
    _pick_lane(panel, recipe_match.GENAU)
    panel.set_available_categories({"beta"})

    reason = panel._category.itemData(panel._category.findText("gamma"), TOOLTIP)
    # An act the video lane answers happily can still have no loop under it, so
    # the greyed-out reason has to name which lane it is talking about.
    assert reason == "No past looping “gamma” flick to base a Genau recipe on yet"


def test_the_genau_lane_names_what_it_makes_in_the_overlays_word(qtbot):
    panel = _panel(qtbot)

    assert panel._genau_radio.toolTip() == (
        "Make a Genau flick: one complete cycle, looping, sent to Genau when done.")


def test_an_act_the_new_lane_cannot_answer_is_not_left_selected(qtbot):
    # Otherwise Generate stays lit on a pick the lane has no recipe for, and the
    # click can only end in "no recipe yet".
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "gamma")
    assert panel._generate_btn.isEnabled()

    panel.set_available_categories({"beta"})  # gamma just went unanswerable

    assert panel.selected_category() == ""
    assert not panel._generate_btn.isEnabled()
