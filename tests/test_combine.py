"""Combine: two drop zones + a Generate button for the image+video combine."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QStyle, QVBoxLayout, QWidget
from shared_ui.colors import BG_SECONDARY, BLUE, hovered
from shared_ui.spacing import BUTTON_GAP, BUTTON_GROUP_GAP
from shared_ui.testing import ground

from origenerator import action_settings, animation_paths
from origenerator.gui.action_dropdown import ACTION_LABEL
from origenerator.gui.combine import Combine, CombineRequest, _text_inset
from origenerator.gui.drags import under_way
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.thumbnail_dropdown import THUMBNAILS_ROLE

TOOLTIP = Qt.ItemDataRole.ToolTipRole


class _Uses:
    """What the controller keeps of the videos the combine says went into its drop zone."""

    def __init__(self):
        self.said: list[tuple[str, str]] = []

    def record(self, intent, video):
        self.said.append((intent, video))

    def history(self, intent):
        newest_first = (video for lane, video in reversed(self.said) if lane == intent)
        return list(dict.fromkeys(newest_first))


def _panel(qtbot, start_images=None, *, fitting=None, preview=None, uses=None):
    """Images are ``img*`` and videos ``vid*``; a video lends the image drop zone the
    image ``start_images`` names for it, and nothing when it names none.
    ``fitting`` narrows the videos the video drop zone takes to the ones it holds."""
    start_images = start_images or {}
    uses = uses if uses is not None else _Uses()
    combine = Combine(
        image_lent_by=lambda pid: pid if pid.startswith("img") else start_images.get(pid),
        video_lent_by=lambda pid: pid if pid.startswith("vid") and (
            fitting is None or pid in fitting) else None,
        preview=preview or (lambda pid: (None, None)),
        history=uses.history,
    )
    combine.video_used.connect(uses.record)
    qtbot.addWidget(combine)
    return combine


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


def _under_the_drag(zone) -> bool:
    return zone._label.property("dropTarget")


def _pick_action(combine, act):
    """Choose an act in the dropdown, as a click on its row would; "" is the
    neutral "(custom)" and so is an act the list does not carry."""
    index = combine._category.findText(act)
    combine._category.setCurrentIndex(index if index >= 1 else 0)


def _pick_lane(combine, intent):
    """Click the lane's radio; the group's exclusivity releases the other."""
    radio = (combine._genau_radio if intent == action_settings.GENAU
             else combine._video_radio)
    radio.setChecked(True)



def test_the_two_edit_buttons_say_which_settings_each_one_edits(qtbot):
    """His pair: one for the combination in the drop zones, one for the settings every
    animation of an act runs."""
    combine = _panel(qtbot)

    assert combine._open_btn.text() == "Edit individual…"
    assert combine._defaults_btn.text() == "Edit default…"


def test_the_animation_settings_are_editable_with_nothing_in_the_drop_zones(qtbot):
    """What it opens is about the 93 animations, not about a dropped image, so
    it is not gated on one the way Generate and "Edit individual…" are."""
    combine = _panel(qtbot)
    asked = []
    combine.animation_settings_requested.connect(lambda: asked.append(True))

    combine._defaults_btn.click()

    assert combine._defaults_btn.isEnabled()
    assert asked == [True]


def _acts(combine):
    """The acts the Action list carries, the neutral first row aside."""
    return [combine._category.itemText(i) for i in range(1, combine._category.count())]


def test_the_action_list_carries_the_acts_that_lane_has_a_row_for(qtbot):
    """One row per act per lane in his table; the list carried the same fixed set
    under both lanes, in an order of its own."""
    combine = _panel(qtbot)

    assert _acts(combine) == ["alpha", "beta", "gamma", "delta", "epsilon", "dancing"]

    _pick_lane(combine, action_settings.GENAU)

    assert _acts(combine) == ["alpha", "beta", "gamma"]


def test_an_act_the_new_lane_has_no_row_for_is_not_left_picked(qtbot):
    combine = _panel(qtbot)
    _pick_action(combine, "delta")

    _pick_lane(combine, action_settings.GENAU)

    assert combine.selected_category() == ""


def test_an_act_both_lanes_carry_stays_picked_across_the_switch(qtbot):
    combine = _panel(qtbot)
    _pick_action(combine, "alpha")

    _pick_lane(combine, action_settings.GENAU)

    assert combine.selected_category() == "alpha"


def test_only_the_video_drop_zone_is_drained_of_color(qtbot):
    # The video is here for its settings — never for what it looks like — while
    # the image is the very thing being animated.
    combine = _panel(qtbot)

    assert combine.video_zone._grayscale
    assert not combine.image_zone._grayscale


def test_generate_is_disabled_until_both_drop_zones_are_filled(qtbot):
    combine = _panel(qtbot)
    assert not combine._generate_btn.isEnabled()

    combine.image_zone.set_item("img1")
    assert not combine._generate_btn.isEnabled()  # the video drop zone is still empty

    combine.video_zone.set_item("vid1")
    assert combine._generate_btn.isEnabled()       # both filled: ready


def test_grayed_generate_and_edit_say_what_they_still_need(qtbot):
    combine = _panel(qtbot)
    needs_image = "Nothing to start from — drop an image first"
    assert (combine._generate_btn.toolTip(), combine._open_btn.toolTip()) == (needs_image, needs_image)

    combine.image_zone.set_item("img1")

    needs_action_or_video = "Pick an act or drop a video first"
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
    # "Edit individual…" needs the same ingredients as Generate — a source image
    # and settings — so it lights and dims in lockstep with the Generate button.
    combine = _panel(qtbot)
    assert not combine._open_btn.isEnabled()

    combine.image_zone.set_item("img1")
    assert not combine._open_btn.isEnabled()  # image alone, no settings yet

    combine.video_zone.set_item("vid1")
    assert combine._open_btn.isEnabled()       # both filled: ready to open


def test_generate_says_it_draws_a_random_seed_for_a_video_on_its_own_start_image(qtbot):
    # The press gives the video's settings fresh seeds, so it makes a new
    # variation rather than the same video again, and the button says so.
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
    assert combine._open_btn.isEnabled()  # there is still a tab to open it in


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

    # The same pair Generate would ask for, marked as bound for the generator.
    assert opened == [CombineRequest(image_id="img1", video_id="vid1",
                                     intent=action_settings.VIDEO, edit_first=True)]


def test_clicking_open_with_a_picked_act_emits_the_category(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "delta")
    opened = []
    combine.combine_requested.connect(opened.append)

    combine._open_btn.click()

    assert opened == [CombineRequest(image_id="img1", category="delta",
                                     intent=action_settings.VIDEO, edit_first=True)]


def test_a_drag_under_way_lights_only_the_drop_zone_it_fits(qtbot):
    combine = _panel(qtbot)  # image drop zone accepts img*, video drop zone accepts vid*
    image, video = generation_mime("img7"), generation_mime("vid7")

    under_way.started.emit(image, None)
    assert combine.image_zone._label.property("dragActive") is True
    assert combine.video_zone._label.property("dragActive") is False
    under_way.ended.emit()

    under_way.started.emit(video, None)  # a video now: the other drop zone lights instead
    assert combine.image_zone._label.property("dragActive") is False
    assert combine.video_zone._label.property("dragActive") is True

    under_way.ended.emit()
    assert combine.image_zone._label.property("dragActive") is False
    assert combine.video_zone._label.property("dragActive") is False


def test_a_video_let_go_between_the_drop_zones_lands_in_both(qtbot):
    combine = _panel(qtbot, start_images={"vid1": "img1"})

    _let_go_over(combine._between, "vid1")

    assert combine.image_zone.current_id() == "img1"  # the image the video was made from
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
    combine = _panel(qtbot)  # the gallery holds no image vid7 was made from

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


def test_with_an_act_picked_the_room_between_reaches_only_the_image_drop_zone(qtbot):
    # The video drop zone is hidden under an act, so nothing shows it as a target.
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
    # As far apart as a group's gap set them in this column before it took drops.
    assert between.height() == BUTTON_GAP + BUTTON_GROUP_GAP


def test_the_neutral_option_is_custom_leading_the_acts(qtbot):
    combine = _panel(qtbot)
    assert combine.selected_category() == ""  # neutral by default
    items = [combine._category.itemText(i) for i in range(combine._category.count())]
    assert items[0] == "(custom)"
    assert items[1:] == list(animation_paths.acts(action_settings.VIDEO))


def _enabled(combine, text) -> bool:
    return combine._category.model().item(combine._category.findText(text)).isEnabled()


def test_acts_with_no_video_to_mine_are_grayed_out(qtbot):
    combine = _panel(qtbot)

    combine.set_available_categories({"beta", "epsilon"})

    assert _enabled(combine, "beta")
    assert _enabled(combine, "epsilon")
    assert not _enabled(combine, "gamma")  # nothing in the gallery to take settings from
    assert not _enabled(combine, "dancing")
    assert _enabled(combine, "(custom)")     # the neutral option always stays pickable


def test_an_act_becomes_pickable_once_a_video_of_it_exists(qtbot):
    combine = _panel(qtbot)
    combine.set_available_categories(set())
    assert not _enabled(combine, "dancing")

    combine.set_available_categories({"dancing"})  # the user just made one

    assert _enabled(combine, "dancing")


def test_a_grayed_act_explains_itself(qtbot):
    combine = _panel(qtbot)
    combine.set_available_categories({"beta"})
    index = combine._category.findText("gamma")
    assert "no past" in combine._category.itemData(index, TOOLTIP).lower()
    assert not combine._category.itemData(combine._category.findText("beta"), TOOLTIP)


def test_dropdown_sits_beside_the_video_drop_zone_in_one_part(qtbot):
    combine = _panel(qtbot)
    # The dropdown configures the *video* settings, so it shares one container with the
    # video drop zone — laid out side by side, not stacked, and not a peer of the image.
    assert combine._action_part.parent() is combine.video_zone.parent()
    assert combine.image_zone.parent() is not combine.video_zone.parent()
    assert isinstance(combine.video_zone.parent().layout(), QHBoxLayout)


def test_the_word_action_sits_under_the_dropdown_it_names(qtbot):
    """Beside a dropdown squeezed into a narrow pane the word does not fit, and
    read as "Ac…"; the list opens upwards, so underneath stays clear."""
    combine = _panel(qtbot)
    column = combine._action_part.layout()
    order = [column.itemAt(i).widget() for i in range(column.count())]
    named = [w for w in order if isinstance(w, QLabel) and w.text() == ACTION_LABEL]

    assert isinstance(column, QVBoxLayout)
    assert len(named) == 1
    assert order.index(named[0]) == order.index(combine._category) + 1


def test_a_picked_category_enables_generate_with_only_an_image(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    assert not combine._generate_btn.isEnabled()  # image alone, no settings chosen yet

    _pick_action(combine, "alpha")
    assert combine._generate_btn.isEnabled()      # a category is settings enough — no video needed

    _pick_action(combine, "")                       # back to neutral
    assert not combine._generate_btn.isEnabled()


def test_picking_an_act_clears_the_dropped_video_without_collapsing(qtbot):
    combine = _panel(qtbot)
    combine.video_zone.set_item("vid1")
    height = combine._video_part.sizeHint().height()

    _pick_action(combine, "alpha")

    assert combine.video_zone.current_id() is None  # the act supersedes it, so the video is dropped
    assert combine._video_part.sizeHint().height() == height  # hidden, but its room stays put


def test_going_back_to_custom_brings_back_the_video_the_act_replaced(qtbot):
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
    fitting.clear()  # trashed while the act was picked

    _pick_action(combine, "")

    assert combine.video_zone.current_id() is None


def test_a_trashed_video_leaves_the_drop_zone_empty_rather_than_bringing_back_an_older_one(qtbot):
    fitting = {"vid1", "vid2"}
    combine = _panel(qtbot, fitting=fitting)
    combine.video_zone.set_item("vid1")
    combine.video_zone.set_item("vid2")
    _pick_action(combine, "alpha")
    fitting.discard("vid2")  # trashed while the act was picked

    _pick_action(combine, "")
    _pick_lane(combine, action_settings.GENAU)
    _pick_lane(combine, action_settings.VIDEO)

    assert combine.video_zone.current_id() is None
    assert _listed_under_recent(combine) == ["vid1"]


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


def test_a_video_that_no_longer_fits_the_drop_zone_is_not_listed(qtbot):
    fitting = {"vid1", "vid2"}
    combine = _panel(qtbot, fitting=fitting)
    combine.video_zone.set_item("vid1")
    combine.video_zone.set_item("vid2")
    fitting.discard("vid1")  # trashed since

    assert _listed_under_recent(combine) == ["vid2"]


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


def test_recent_sits_under_the_action_dropdown_left_of_the_video_drop_zone(qtbot):
    combine = _panel(qtbot)
    column = combine._action_part.layout()
    order = [column.itemAt(i).widget() for i in range(column.count())]
    named = next(w for w in order if isinstance(w, QLabel) and w.text() == ACTION_LABEL)

    assert order.index(combine._recent_videos) > order.index(named) > order.index(combine._category)


def test_recent_shows_only_while_custom_is_picked(qtbot):
    combine = _panel(qtbot)
    assert not combine._recent_videos.isHidden()

    _pick_action(combine, "gamma")
    assert combine._recent_videos.isHidden()

    _pick_action(combine, "")
    assert not combine._recent_videos.isHidden()


def test_picking_an_act_keeps_the_room_recent_takes(qtbot):
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
    uses.record(action_settings.VIDEO, "vid2")  # given the drop zone in another copy of the app

    assert _listed_under_recent(combine) == ["vid1", "vid2"]


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
    _pick_action(combine, "delta")

    combine.video_zone.set_item("vid1")

    assert combine.selected_category() == ""          # a dropped video wipes the act back to "(custom)"
    assert combine.video_zone.current_id() == "vid1"  # ...and the video is what's kept


def test_the_video_drop_zone_shows_only_while_custom_is_picked(qtbot):
    combine = _panel(qtbot)
    assert not combine.video_zone.isHidden()

    _pick_action(combine, "gamma")
    assert combine.video_zone.isHidden()

    _pick_action(combine, "")
    assert not combine.video_zone.isHidden()


def test_generate_emits_the_picked_act(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "delta")
    cats = []
    combine.combine_requested.connect(cats.append)

    combine._generate_btn.click()

    assert cats == [CombineRequest(image_id="img1", category="delta",
                                   intent=action_settings.VIDEO)]


# --- the Kino/Genau radio: what the result is for -----------------------------


def test_the_lane_defaults_to_kino(qtbot):
    # The long-standing behavior of this combine, and by far the more common ask, so
    # the Genau flick is the deliberate detour rather than the default.
    combine = _panel(qtbot)
    assert combine.selected_intent() == action_settings.VIDEO
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


def test_generate_carries_the_chosen_lane(qtbot):
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "alpha")  # one both lanes have a row for, so the pick stands
    _pick_lane(combine, action_settings.GENAU)
    cats = []
    combine.combine_requested.connect(cats.append)

    combine._generate_btn.click()

    assert cats == [CombineRequest(image_id="img1", category="alpha",
                                   intent=action_settings.GENAU)]


def test_switching_the_lane_announces_it_once(qtbot):
    # buttonToggled fires for both radios on one click — the off edge and the on
    # edge — and the view answers each by re-graying the whole act list.
    combine = _panel(qtbot)
    heard = []
    combine.intent_changed.connect(heard.append)

    _pick_lane(combine, action_settings.GENAU)
    assert heard == [action_settings.GENAU]

    _pick_lane(combine, action_settings.VIDEO)
    assert heard == [action_settings.GENAU, action_settings.VIDEO]


def test_a_grayed_act_explains_itself_in_the_lanes_own_terms(qtbot):
    combine = _panel(qtbot)
    _pick_lane(combine, action_settings.GENAU)
    combine.set_available_categories({"beta"})

    reason = combine._category.itemData(combine._category.findText("gamma"), TOOLTIP)
    # An act the video lane answers happily can still have no loop under it, so
    # the grayed-out reason has to name which lane it is talking about.
    assert reason == "No past looping “gamma” flick to take settings from yet"


def test_the_genau_lane_names_what_it_makes_in_the_overlays_word(qtbot):
    combine = _panel(qtbot)

    assert combine._genau_radio.toolTip() == (
        "Make a Genau flick: one complete cycle, looping, sent to Genau when done.")


def test_an_act_the_new_lane_cannot_answer_is_not_left_selected(qtbot):
    # Otherwise Generate stays lit on a pick the lane has no settings for, and the
    # click can only end in "no past video yet".
    combine = _panel(qtbot)
    combine.image_zone.set_item("img1")
    _pick_action(combine, "gamma")
    assert combine._generate_btn.isEnabled()

    combine.set_available_categories({"beta"})  # gamma just went unanswerable

    assert combine.selected_category() == ""
    assert not combine._generate_btn.isEnabled()


def test_the_act_list_is_labelled_the_way_an_images_own_action_is(qtbot):
    """One word for the two halves of the same vocabulary: what an image shows,
    and what it can be made to do."""
    combine = _panel(qtbot)

    assert ACTION_LABEL in [label.text() for label in combine.findChildren(QLabel)]


def test_the_act_list_opens_wide_enough_for_the_longest_act(qtbot):
    """The field is squeezed by the pane it sits in; the open list is not, or the
    acts arrive cut short where they are read."""
    dropdown = _panel(qtbot)._category
    longest = max(dropdown.fontMetrics().horizontalAdvance(dropdown.itemText(i))
                  for i in range(dropdown.count()))

    assert dropdown.view().minimumWidth() > longest


def test_the_word_action_keeps_its_own_height_under_the_dropdown(qtbot):
    """Given the whole row's spare height it sat centered in a block three times
    its own, a word adrift in the area rather than a label on the dropdown."""
    combine = _panel(qtbot)
    pane = QWidget()
    qtbot.addWidget(pane)
    combine.setParent(pane)
    pane.resize(420, 460)
    combine.setGeometry(0, 0, 420, 460)
    pane.show()
    combine.layout().activate()
    named = [w for w in combine._action_part.findChildren(QLabel)
             if w.text() == ACTION_LABEL][0]

    assert named.height() == named.sizeHint().height()
    assert named.y() == combine._category.y() + combine._category.height()


def test_the_word_action_lines_up_with_the_words_in_the_dropdown(qtbot):
    """Flush to the frame it read as a word in the corner rather than a label on
    the dropdown, whose own text starts a few pixels in."""
    combine = _panel(qtbot)
    named = [w for w in combine._action_part.findChildren(QLabel)
             if w.text() == ACTION_LABEL][0]

    assert named.indent() == _text_inset(combine._category) > 0


def test_the_two_radios_are_further_apart_than_a_circle_is_from_its_own_word(qtbot):
    """"Kino" sat nearer Genau's circle than its own, which reads as labelling
    the wrong one."""
    combine = _panel(qtbot)
    row = combine._intent_part.layout()

    assert row.spacing() > combine._video_radio.style().pixelMetric(
        QStyle.PixelMetric.PM_RadioButtonLabelSpacing, None, combine._video_radio)




def test_both_zones_paste_a_name_and_only_the_image_zone_browses(qtbot):
    browsed = []
    combine = Combine(
        image_lent_by=lambda pid: pid, video_lent_by=lambda pid: pid,
        preview=lambda pid: (None, None), history=lambda intent: [],
        named={"AB12CD34 001": "img1"}.get, name_of={"img1": "AB12CD34 001"}.get,
        browse_image=lambda: browsed.append("asked"))
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
