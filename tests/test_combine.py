from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QStyle, QVBoxLayout, QWidget
from shared_ui.colors import BG_SECONDARY, BLUE, hovered
from shared_ui.spacing import BUTTON_GAP, BUTTON_GROUP_GAP
from shared_ui.testing import ground
from shared_ui.tick_control import TickControl

from origenerator import action_settings
from origenerator.gui.action_row import ACTION_LABEL
from origenerator.gui.combine import (
    Combine,
    CombineRequest,
    ZoneLookups,
    _text_inset,
    combine_checkbox,
)
from origenerator.gui.drags import under_way
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.recent_videos import RecentVideo
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.thumbnail_dropdown import THUMBNAILS_ROLE

TOOLTIP = Qt.ItemDataRole.ToolTipRole


class _Uses:
    def __init__(self):
        self.said: list[tuple[str, str]] = []

    def record(self, intent, video):
        self.said.append((intent, video))

    def history(self, intent):
        newest_first = (video for lane, video in reversed(self.said) if lane == intent)
        return [RecentVideo(video, None) for video in dict.fromkeys(newest_first)]


def _panel(qtbot, start_images=None, *, fitting=None, preview=None, uses=None):
    start_images = start_images or {}
    uses = uses if uses is not None else _Uses()
    seen = preview or (lambda pid: (None, None))
    combine = Combine(
        image_lookups=ZoneLookups(
            lambda pid: pid if pid.startswith("img") else start_images.get(pid), seen),
        video_lookups=ZoneLookups(
            lambda pid: pid if pid.startswith("vid") and (
                fitting is None or pid in fitting) else None, seen),
        history=uses.history,
    )
    combine.video_used.connect(uses.record)
    qtbot.addWidget(combine)
    return combine


def _drag_over(zone, pid):
    # The event keeps only a pointer to the QMimeData, so hold it in a local.
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


def _under_the_drag(zone) -> bool:
    return zone._label.property("dropTarget")


def _pick_action(combine, action):
    index = combine._category.findText(action)
    combine._category.setCurrentIndex(index if index >= 1 else 0)


def _pick_lane(combine, intent):
    radio = (combine._genau_radio if intent == action_settings.GENAU
             else combine._video_radio)
    radio.setChecked(True)



def test_the_two_edit_buttons_say_which_settings_each_one_edits(qtbot):
    combine = _panel(qtbot)

    assert combine._open_btn.text() == "Edit individual…", (
        "the user's pair: one for the combination in the drop zones, one for the settings every "
        "animation of an action runs")
    assert combine._defaults_btn.text() == "Edit default…"


def test_the_animation_settings_are_editable_with_nothing_in_the_drop_zones(qtbot):
    combine = _panel(qtbot)
    asked = []
    combine.animation_settings_requested.connect(lambda: asked.append(True))

    combine._defaults_btn.click()

    assert combine._defaults_btn.isEnabled(), (
        "what it opens is about the animations, not about a dropped image, so it is not gated "
        "on one the way Generate and the other Edit button are")
    assert asked == [True]


def _actions(combine):
    return [combine._category.itemText(i) for i in range(1, combine._category.count())]


def test_the_action_list_carries_every_video_action_in_the_setter_tools_order(qtbot):
    combine = _panel(qtbot)

    assert _actions(combine) == ["alpha", "beta", "alpha + beta"]

    _pick_lane(combine, action_settings.GENAU)

    assert _actions(combine) == ["alpha", "beta", "alpha + beta"]


def test_an_action_both_lanes_carry_stays_picked_across_the_switch(qtbot):
    combine = _panel(qtbot)
    _pick_action(combine, "alpha")

    _pick_lane(combine, action_settings.GENAU)

    assert combine.selected_category() == "alpha"


def test_only_the_video_drop_zone_is_drained_of_color(qtbot):
    combine = _panel(qtbot)

    assert combine.video_zone._grayscale, (
        "the video zone holds a source video, not a result: in color it reads as a second subject "
        "beside the image it will animate")
    assert not combine.image_zone._grayscale


def test_generate_is_disabled_until_both_drop_zones_are_filled(qtbot):
    combine = _panel(qtbot)
    assert not combine._generate_btn.isEnabled()

    combine.image_zone.set_item("img1")
    assert not combine._generate_btn.isEnabled()

    combine.video_zone.set_item("vid1")
    assert combine._generate_btn.isEnabled()


def test_grayed_generate_and_edit_say_what_they_still_need(qtbot):
    combine = _panel(qtbot)
    needs_image = "Nothing to start from — drop an image first"
    assert (combine._generate_btn.toolTip(), combine._open_btn.toolTip()) == (needs_image, needs_image)

    combine.image_zone.set_item("img1")

    needs_action_or_video = "Pick an action or drop a video first"
    assert (combine._generate_btn.toolTip(), combine._open_btn.toolTip()) == (needs_action_or_video, needs_action_or_video)


def test_once_ready_generate_drops_its_reason_and_edit_says_what_it_does(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")

    combine.video_zone.set_item("vid1")

    assert combine._generate_btn.toolTip() == ""
    assert combine._open_btn.toolTip() == (
        "Load this combination into a generate tab to edit before running it.")


def test_clicking_generate_asks_for_the_dropped_pair(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")
    got = []
    combine.combine_requested.connect(got.append)

    combine._generate_btn.click()

    assert got == [CombineRequest(image_id="img1", video_id="vid1",
                                  intent=action_settings.VIDEO)]


def test_open_in_generator_button_tracks_the_same_enablement_as_generate(qtbot):
    combine = _panel(qtbot)
    assert not combine._open_btn.isEnabled()

    combine.image_zone.set_item("img1")
    assert not combine._open_btn.isEnabled()

    combine.video_zone.set_item("vid1")
    assert combine._open_btn.isEnabled()


def test_generate_says_it_draws_a_random_seed_for_a_video_on_its_own_start_image(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})
    combine.image_zone.set_item("img1")

    combine.video_zone.set_item("vid1")

    assert combine._generate_btn.text() == "Generate with Random seed"


def test_generate_stays_plain_for_a_video_on_another_image(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})
    combine.image_zone.set_item("img2")

    combine.video_zone.set_item("vid1")

    assert combine._generate_btn.text() == "Generate"


def test_generate_goes_back_to_plain_once_the_image_changes(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})
    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")

    combine.image_zone.set_item("img2")

    assert combine._generate_btn.text() == "Generate"


def test_generate_grays_while_the_pair_dropped_in_is_already_being_made(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")

    combine.note_folder_generating(True)

    assert not combine._generate_btn.isEnabled()
    assert combine._generate_btn.toolTip() == "This folder is already making one"
    assert combine._open_btn.isEnabled(), (
        "there is still a tab to open the pair in")


def test_generate_comes_back_once_that_one_is_made(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")
    combine.note_folder_generating(True)

    combine.note_folder_generating(False)

    assert combine._generate_btn.isEnabled()
    assert combine._generate_btn.toolTip() == ""


def test_generate_is_blue_while_it_can_run_and_gray_while_it_cannot(qtbot):
    combine = _panel(qtbot)
    combine.setStyleSheet(build_stylesheet())
    with qtbot.waitExposed(combine):
        combine.show()
    cannot_run = ground(combine._generate_btn)

    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")

    assert ground(combine._generate_btn) == BLUE.name()
    assert cannot_run == BG_SECONDARY.name()


@pytest.mark.parametrize("name", ["_generate_btn", "_open_btn"], ids=["Generate", "Edit"])
def test_a_ready_button_sits_one_step_lighter_under_the_pointer(qtbot, pointer, name):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")
    combine.setStyleSheet(build_stylesheet())
    with qtbot.waitExposed(combine):
        combine.show()
    button = getattr(combine, name)
    pointer.off(button)
    at_rest = ground(button)
    pointer.on(button)

    assert ground(button) == hovered(QColor(at_rest)).name()


def test_clicking_open_emits_the_dropped_video_for_the_generator(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    combine.video_zone.set_item("vid1")
    opened = []
    combine.combine_requested.connect(opened.append)

    combine._open_btn.click()

    assert opened == [CombineRequest(image_id="img1", video_id="vid1",
                                     intent=action_settings.VIDEO, edit_first=True)]


def test_clicking_open_with_a_picked_action_emits_the_category(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "alpha + beta")
    opened = []
    combine.combine_requested.connect(opened.append)

    combine._open_btn.click()

    assert opened == [CombineRequest(image_id="img1", category="alpha + beta",
                                     intent=action_settings.VIDEO, edit_first=True)]


def test_a_checkbox_beside_the_action_list_rides_on_what_combine_asks_for(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "beta")
    asked = []
    combine.combine_requested.connect(asked.append)
    box = combine.findChild(TickControl, combine_checkbox("third box"))

    box.click()
    combine._generate_btn.click()

    assert asked == [CombineRequest(image_id="img1", category="beta",
                                    intent=action_settings.VIDEO, checked=("third box",))]


def test_the_checkbox_sits_to_the_right_of_the_action_list(qtbot):
    combine = _panel(qtbot)
    combine.resize(600, 400)
    combine.show()
    box = combine.findChild(TickControl, combine_checkbox("third box"))

    assert box.mapTo(combine, QPoint()).x() > combine._category.mapTo(combine, QPoint()).x()
    assert abs(box.mapTo(combine, QPoint()).y() - combine._category.mapTo(combine, QPoint()).y()) < (
        combine._category.height())


def test_ticking_the_checkbox_says_so_for_the_actions_to_be_offered_again(qtbot):
    combine = _panel(qtbot)

    with qtbot.waitSignal(combine.checked_changed):
        combine.findChild(TickControl, combine_checkbox("third box")).click()

    assert combine.checked_boxes() == ("third box",)


def test_a_drag_under_way_lights_only_the_drop_zone_it_fits(qtbot):
    combine = _panel(qtbot)
    image, video = generation_mime("img7"), generation_mime("vid7")

    under_way.started.emit(image, None)
    assert combine.image_zone._label.property("dragActive") is True
    assert combine.video_zone._label.property("dragActive") is False
    under_way.ended.emit()

    under_way.started.emit(video, None)
    assert combine.image_zone._label.property("dragActive") is False
    assert combine.video_zone._label.property("dragActive") is True

    under_way.ended.emit()
    assert combine.image_zone._label.property("dragActive") is False
    assert combine.video_zone._label.property("dragActive") is False


def test_a_video_let_go_between_the_drop_zones_lands_in_both(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})

    _let_go_over(combine._between, "vid1")

    assert combine.image_zone.current_id() == "img1"
    assert combine.video_zone.current_id() == "vid1"


def test_a_video_over_the_room_between_the_drop_zones_lights_both(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})

    assert _drag_over(combine._between, "vid1").isAccepted()
    assert _under_the_drag(combine.image_zone)
    assert _under_the_drag(combine.video_zone)

    combine._between.dragLeaveEvent(QDragLeaveEvent())
    assert not _under_the_drag(combine.image_zone)
    assert not _under_the_drag(combine.video_zone)


def test_both_drop_zones_stay_lit_while_the_drag_moves_about_between_them(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})
    _drag_over(combine._between, "vid1")
    mime = generation_mime("vid1")
    event = QDragMoveEvent(QPoint(5, 3), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    combine._between.dragMoveEvent(event)

    assert event.isAccepted()
    assert _under_the_drag(combine.image_zone)
    assert _under_the_drag(combine.video_zone)


def test_letting_go_between_the_drop_zones_puts_both_out(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})
    _drag_over(combine._between, "vid1")

    _let_go_over(combine._between, "vid1")

    assert not _under_the_drag(combine.image_zone)
    assert not _under_the_drag(combine.video_zone)


def test_between_the_drop_zones_a_video_lands_only_where_it_lends_something(qtbot):
    combine = _panel(qtbot)

    _drag_over(combine._between, "vid7")
    assert not _under_the_drag(combine.image_zone)
    assert _under_the_drag(combine.video_zone)

    _let_go_over(combine._between, "vid7")
    assert combine.image_zone.current_id() is None
    assert combine.video_zone.current_id() == "vid7"


def test_an_image_let_go_between_the_drop_zones_lands_in_the_image_drop_zone(qtbot):
    combine = _panel(qtbot)

    _let_go_over(combine._between, "img1")

    assert combine.image_zone.current_id() == "img1"
    assert combine.video_zone.current_id() is None


def test_what_lends_neither_drop_zone_anything_cannot_be_let_go_between_them(qtbot):
    combine = _panel(qtbot)

    assert not _drag_over(combine._between, "elsewhere").isAccepted()
    assert not _let_go_over(combine._between, "elsewhere").isAccepted()


def test_with_an_action_picked_the_room_between_reaches_only_the_image_drop_zone(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})
    _pick_action(combine, "alpha")

    _let_go_over(combine._between, "vid1")

    assert combine.image_zone.current_id() == "img1"
    assert combine.video_zone.current_id() is None
    assert combine.selected_category() == "alpha"


def test_the_room_between_the_drop_zones_is_the_whole_gap_that_parts_them(qtbot):
    combine = _panel(qtbot)
    combine.setStyleSheet(build_stylesheet())
    with qtbot.waitExposed(combine):
        combine.show()

    between = combine._between.geometry()
    assert between.top() == combine.image_zone.geometry().bottom() + 1
    assert between.bottom() + 1 == combine._video_part.geometry().top()
    assert between.height() == BUTTON_GAP + BUTTON_GROUP_GAP, (
        "as far apart as a group's gap set the two in this column before the room between them "
        "took drops")


def test_the_neutral_option_is_custom_leading_the_actions(qtbot):
    combine = _panel(qtbot)
    assert combine.selected_category() == ""
    items = [combine._category.itemText(i) for i in range(combine._category.count())]
    assert items[0] == "(custom)"
    assert items[1:] == ["alpha", "beta", "alpha + beta"]


def _enabled(combine, text) -> bool:
    return combine._category.model().item(combine._category.findText(text)).isEnabled()


def test_actions_with_no_video_to_mine_are_grayed_out(qtbot):
    combine = _panel(qtbot)

    combine.set_available_categories({"beta", "alpha + beta"})

    assert _enabled(combine, "beta")
    assert _enabled(combine, "alpha + beta")
    assert not _enabled(combine, "alpha")
    assert _enabled(combine, "(custom)")


def test_an_action_becomes_pickable_once_a_video_of_it_exists(qtbot):
    combine = _panel(qtbot)
    combine.set_available_categories(set())
    assert not _enabled(combine, "alpha + beta")

    combine.set_available_categories({"alpha + beta"})

    assert _enabled(combine, "alpha + beta")


def test_a_grayed_action_explains_itself(qtbot):
    combine = _panel(qtbot)
    combine.set_available_categories({"beta"})
    index = combine._category.findText("alpha")
    assert "no past" in combine._category.itemData(index, TOOLTIP).lower()
    assert not combine._category.itemData(combine._category.findText("beta"), TOOLTIP)


def test_dropdown_sits_beside_the_video_drop_zone_in_one_part(qtbot):
    combine = _panel(qtbot)
    assert combine._action_part.parent() is combine.video_zone.parent()
    assert combine.image_zone.parent() is not combine.video_zone.parent()
    assert isinstance(combine.video_zone.parent().layout(), QHBoxLayout)


def test_the_word_action_sits_under_the_dropdown_it_names(qtbot):
    combine = _panel(qtbot)
    column = combine._action_part.layout()
    order = [column.itemAt(i).widget() for i in range(column.count())]
    named = [w for w in order if isinstance(w, QLabel) and w.text() == ACTION_LABEL]
    above = column.itemAt(order.index(named[0]) - 1).layout()

    assert isinstance(column, QVBoxLayout)
    assert len(named) == 1
    assert above.itemAt(0).widget() is combine._category


def test_a_picked_category_enables_generate_with_only_an_image(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    assert not combine._generate_btn.isEnabled()

    _pick_action(combine, "alpha")
    assert combine._generate_btn.isEnabled()

    _pick_action(combine, "")
    assert not combine._generate_btn.isEnabled()


def test_picking_an_action_clears_the_dropped_video_without_collapsing(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")
    height = combine._video_part.sizeHint().height()

    _pick_action(combine, "alpha")

    assert combine.video_zone.current_id() is None
    assert combine._video_part.sizeHint().height() == height


def test_going_back_to_custom_brings_back_the_video_the_action_replaced(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")
    _pick_action(combine, "alpha")

    _pick_action(combine, "")

    assert combine.video_zone.current_id() == "vid1"


def test_a_remembered_video_that_no_longer_fits_its_drop_zone_is_not_brought_back(qtbot):
    fitting = {"vid1"}
    combine = _panel(qtbot, fitting=fitting)
    combine.video_zone.set_item("vid1")
    _pick_action(combine, "alpha")
    fitting.clear()

    _pick_action(combine, "")

    assert combine.video_zone.current_id() is None


def test_a_trashed_video_leaves_the_drop_zone_empty_rather_than_bringing_back_an_older_one(qtbot):
    fitting = {"vid1", "vid2"}
    combine = _panel(qtbot, fitting=fitting)
    combine.video_zone.set_item("vid1")
    combine.video_zone.set_item("vid2")
    _pick_action(combine, "alpha")
    fitting.discard("vid2")

    _pick_action(combine, "")
    _pick_lane(combine, action_settings.GENAU)
    _pick_lane(combine, action_settings.VIDEO)

    assert combine.video_zone.current_id() is None


def test_each_lane_keeps_its_own_dropped_video(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")
    _pick_lane(combine, action_settings.GENAU)
    assert combine.video_zone.current_id() is None
    combine.video_zone.set_item("vid2")

    _pick_lane(combine, action_settings.VIDEO)
    assert combine.video_zone.current_id() == "vid1"

    _pick_lane(combine, action_settings.GENAU)
    assert combine.video_zone.current_id() == "vid2"


def _listed_under_recent(combine):
    combine._recent_videos.refresh()
    return [combine._recent_videos.itemData(row, THUMBNAILS_ROLE)[0].item
            for row in range(combine._recent_videos.count())]


def test_a_video_put_in_the_drop_zone_is_listed_under_recent(qtbot):
    combine = _panel(qtbot)

    combine.video_zone.set_item("vid1")

    assert _listed_under_recent(combine) == ["vid1"]


def test_recent_lists_the_newest_first_and_each_video_once(qtbot):
    combine = _panel(qtbot)

    for video in ("vid1", "vid2", "vid1", "vid3"):
        combine.video_zone.set_item(video)

    assert _listed_under_recent(combine) == ["vid3", "vid1", "vid2"]


def test_each_lane_lists_the_videos_it_had(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")
    _pick_lane(combine, action_settings.GENAU)
    combine.video_zone.set_item("vid2")

    assert _listed_under_recent(combine) == ["vid2"]
    _pick_lane(combine, action_settings.VIDEO)
    assert _listed_under_recent(combine) == ["vid1"]


def test_recent_keeps_every_video_the_lane_has_had(qtbot):
    combine = _panel(qtbot)

    for n in range(40):
        combine.video_zone.set_item(f"vid{n}")

    assert _listed_under_recent(combine) == [f"vid{n}" for n in range(39, -1, -1)]


def test_picking_a_recent_video_puts_it_in_the_drop_zone_and_lists_it_first(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")
    combine.video_zone.set_item("vid2")
    dropdown = combine._recent_videos
    dropdown.showPopup()
    view = dropdown.view()

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualRect(dropdown.model().index(1, 0)).center())

    assert combine.video_zone.current_id() == "vid1"
    assert _listed_under_recent(combine) == ["vid1", "vid2"]


def _first_widget_of(item):
    held = item.layout()
    return held.itemAt(0).widget() if held is not None else item.widget()


def test_recent_sits_under_the_action_dropdown_left_of_the_video_drop_zone(qtbot):
    combine = _panel(qtbot)
    column = combine._action_part.layout()
    order = [_first_widget_of(column.itemAt(i)) for i in range(column.count())]
    named = next(w for w in order if isinstance(w, QLabel) and w.text() == ACTION_LABEL)

    assert order.index(combine._recent_videos) > order.index(named) > order.index(combine._category)


def test_recent_shows_only_while_custom_is_picked(qtbot):
    combine = _panel(qtbot)
    assert not combine._recent_videos.isHidden()

    _pick_action(combine, "beta")
    assert combine._recent_videos.isHidden()

    _pick_action(combine, "")
    assert not combine._recent_videos.isHidden()


def test_picking_an_action_keeps_the_room_recent_takes(qtbot):
    combine = _panel(qtbot)
    column = combine._action_part
    height = column.sizeHint().height()

    _pick_action(combine, "alpha")

    assert column.sizeHint().height() == height


def test_recent_lists_what_the_lane_was_given_before_this_session(qtbot):
    uses = _Uses()
    uses.record(action_settings.VIDEO, "vid1")
    uses.record(action_settings.VIDEO, "vid2")
    uses.record(action_settings.GENAU, "vid3")

    combine = _panel(qtbot, uses=uses)

    assert _listed_under_recent(combine) == ["vid2", "vid1"]
    _pick_lane(combine, action_settings.GENAU)
    assert _listed_under_recent(combine) == ["vid3"]


def test_recent_lists_the_video_in_the_drop_zone_first_whatever_came_since(qtbot):
    uses = _Uses()
    combine = _panel(qtbot, uses=uses)
    combine.video_zone.set_item("vid1")
    uses.record(action_settings.VIDEO, "vid2")

    assert _listed_under_recent(combine) == ["vid1", "vid2"], (
        "a newer use can come from the drop zone in another copy of the app")


def test_a_video_put_in_the_drop_zone_is_said_with_the_lane_it_went_in_under(qtbot):
    uses = _Uses()
    combine = _panel(qtbot, uses=uses)
    _pick_lane(combine, action_settings.GENAU)

    combine.video_zone.set_item("vid1")

    assert uses.said == [(action_settings.GENAU, "vid1")]


def test_a_lanes_video_shown_again_is_not_said_again(qtbot):
    uses = _Uses()
    combine = _panel(qtbot, uses=uses)
    combine.video_zone.set_item("vid1")
    _pick_lane(combine, action_settings.GENAU)
    _pick_lane(combine, action_settings.VIDEO)
    _pick_action(combine, "alpha")
    _pick_action(combine, "")
    combine.set_dropped_videos({action_settings.VIDEO: "vid1"})

    assert uses.said == [(action_settings.VIDEO, "vid1")]


def test_recent_reads_its_videos_only_when_it_opens(qtbot):
    asked = []
    combine = _panel(qtbot, preview=lambda pid: asked.append(pid) or (None, None))

    for n in range(5):
        combine.video_zone.set_item(f"vid{n}")
    _pick_lane(combine, action_settings.GENAU)

    assert asked == [f"vid{n}" for n in range(5)]


def test_a_lane_that_has_had_no_video_lists_none_under_recent(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")

    _pick_lane(combine, action_settings.GENAU)

    assert _listed_under_recent(combine) == []
    assert combine._recent_videos.isEnabled()


def test_dropping_a_video_resets_the_dropdown_to_neutral(qtbot):
    combine = _panel(qtbot)
    _pick_action(combine, "alpha + beta")

    combine.video_zone.set_item("vid1")

    assert combine.selected_category() == ""
    assert combine.video_zone.current_id() == "vid1"


def test_the_video_drop_zone_shows_only_while_custom_is_picked(qtbot):
    combine = _panel(qtbot)
    assert not combine.video_zone.isHidden()

    _pick_action(combine, "beta")
    assert combine.video_zone.isHidden()

    _pick_action(combine, "")
    assert not combine.video_zone.isHidden()


def test_generate_emits_the_picked_action(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "alpha + beta")
    cats = []
    combine.combine_requested.connect(cats.append)

    combine._generate_btn.click()

    assert cats == [CombineRequest(image_id="img1", category="alpha + beta",
                                   intent=action_settings.VIDEO)]



def test_the_lane_defaults_to_kino(qtbot):
    combine = _panel(qtbot)
    assert combine.selected_intent() == action_settings.VIDEO, (
        "Kino is the default because it is what Combine has long done and by far the more "
        "common ask; Genau is the deliberate detour")
    assert combine._video_radio.text() == "Kino"
    assert combine._video_radio.isChecked()
    assert not combine._genau_radio.isChecked()


def _top_to_bottom(layout):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.layout() is not None:
            yield from _top_to_bottom(item.layout())
        elif item.widget() is not None:
            yield item.widget()


def test_the_radio_sits_below_the_dropdown_it_changes(qtbot):
    combine = _panel(qtbot)
    order = list(_top_to_bottom(combine.layout()))
    assert order.index(combine._intent_part) == order.index(combine._video_part) + 1


def test_an_intent_that_is_neither_lane_puts_the_video_lane_back(qtbot):
    combine = _panel(qtbot)
    combine.set_intent(action_settings.GENAU)

    combine.set_intent("neither")

    assert combine.selected_intent() == action_settings.VIDEO


def test_generate_carries_the_chosen_lane(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "alpha")
    _pick_lane(combine, action_settings.GENAU)
    cats = []
    combine.combine_requested.connect(cats.append)

    combine._generate_btn.click()

    assert cats == [CombineRequest(image_id="img1", category="alpha",
                                   intent=action_settings.GENAU)]


def test_switching_the_lane_announces_it_once(qtbot):
    combine = _panel(qtbot)
    heard = []
    combine.intent_changed.connect(heard.append)

    _pick_lane(combine, action_settings.GENAU)
    assert heard == [action_settings.GENAU], (
        "only the lane switched on is passed along: the gallery answers each announcement by "
        "graying the whole action list again")

    _pick_lane(combine, action_settings.VIDEO)
    assert heard == [action_settings.GENAU, action_settings.VIDEO]


def test_a_grayed_action_explains_itself_in_the_lanes_own_terms(qtbot):
    combine = _panel(qtbot)
    _pick_lane(combine, action_settings.GENAU)
    combine.set_available_categories({"beta"})

    reason = combine._category.itemData(combine._category.findText("alpha"), TOOLTIP)
    assert reason == "No past looping “alpha” flick to take settings from yet"


def test_the_genau_lane_names_what_it_makes_in_the_overlays_word(qtbot):
    combine = _panel(qtbot)

    assert combine._genau_radio.toolTip() == (
        "Make a Genau flick: one complete cycle, looping, sent to Genau when done.")


def test_an_action_the_new_lane_cannot_answer_is_not_left_selected(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "alpha")
    assert combine._generate_btn.isEnabled()

    combine.set_available_categories({"beta"})

    assert combine.selected_category() == ""
    assert not combine._generate_btn.isEnabled()


def test_the_action_list_is_labelled_the_way_an_images_own_action_is(qtbot):
    combine = _panel(qtbot)

    assert ACTION_LABEL in [label.text() for label in combine.findChildren(QLabel)]


def test_the_action_list_opens_wide_enough_for_the_longest_action(qtbot):
    dropdown = _panel(qtbot)._category
    longest = max(dropdown.fontMetrics().horizontalAdvance(dropdown.itemText(i))
                  for i in range(dropdown.count()))

    assert dropdown.view().minimumWidth() > longest


def test_the_word_action_keeps_its_own_height_under_the_dropdown(qtbot):
    combine = _panel(qtbot)
    pane = QWidget()
    qtbot.addWidget(pane)
    combine.setParent(pane)
    pane.resize(420, 460)
    combine.setGeometry(0, 0, 420, 460)
    pane.show()
    combine.layout().activate()
    named = next(w for w in combine._action_part.findChildren(QLabel)
             if w.text() == ACTION_LABEL)

    assert named.height() == named.sizeHint().height()
    assert named.y() == combine._category.y() + combine._category.height()


def test_the_word_action_lines_up_with_the_words_in_the_dropdown(qtbot):
    combine = _panel(qtbot)
    named = next(w for w in combine._action_part.findChildren(QLabel)
             if w.text() == ACTION_LABEL)

    assert named.indent() == _text_inset(combine._category) > 0


def test_the_two_radios_are_further_apart_than_a_circle_is_from_its_own_word(qtbot):
    combine = _panel(qtbot)
    row = combine._intent_part.layout()

    assert row.spacing() > combine._video_radio.style().pixelMetric(
        QStyle.PixelMetric.PM_RadioButtonLabelSpacing, None, combine._video_radio)




def test_both_zones_paste_a_name_and_only_the_image_zone_browses(qtbot):
    browsed = []
    shared = {"named": {"AB12CD34 001": "img1"}.get, "name_of": {"img1": "AB12CD34 001"}.get}
    combine = Combine(
        image_lookups=ZoneLookups(
            lambda pid: pid, lambda pid: (None, None),
            browse=lambda: browsed.append("asked"), **shared),
        video_lookups=ZoneLookups(lambda pid: pid, lambda pid: (None, None), **shared),
        history=lambda intent: [])
    qtbot.addWidget(combine)
    image_actions = {action.text(): action for action in combine.image_zone.menu().actions()}
    assert list(image_actions) == ["Paste Origenerator name", "Browse..."]
    assert [action.text() for action in combine.video_zone.menu().actions()] == [
        "Paste Origenerator name"]

    image_actions["Browse..."].trigger()
    QApplication.clipboard().setText("AB12CD34 001")
    {action.text(): action for action in combine.image_zone.menu().actions()}[
        "Paste Origenerator name"].trigger()

    assert browsed == ["asked"]
    assert combine.image_zone.current_id() == "img1"
    assert combine.image_zone.toolTip() == "AB12CD34 001"
