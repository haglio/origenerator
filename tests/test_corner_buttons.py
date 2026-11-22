from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QLabel, QWidget
from shared_ui.spacing import BUTTON_SIZE, BUTTON_SIZE_HUD
from shared_ui.testing import appending_to

from origenerator import gallery
from origenerator.gui import icons, square_buttons
from origenerator.gui.corner_buttons import (
    ENHANCE,
    STAR,
    TRASH,
    CornerButtons,
    corner_size,
    enhance_state,
)
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.media import MediaType


def _image_row(**extra):
    row = {
        "prompt_id": "p1",
        "workflow_name": "sdxl_t2i",
        "workflow_version": "v002",
        "status": "completed",
        "params_json": json.dumps({"positive_prompt": "a paper boat", "seed": 7}),
        "output_files": json.dumps(
            [{"filename": "sdxl_t2i_00001_.png", "subfolder": "image",
              "type": "output"}]),
    }
    row.update(extra)
    return row


def _enhanced_row(settings):
    row = _image_row()
    made_at = gallery.enhance_params_for(row, settings)
    row["output_files"] = json.dumps([
        {"filename": "image_enhance_00001_.png", "subfolder": "image"},
        {"filename": "sdxl_t2i_00001_.png", "subfolder": "image"},
    ])
    row["original_files"] = json.dumps(
        [{"filename": "sdxl_t2i_00001_.png", "subfolder": "image"}])
    row["enhance_history"] = json.dumps(
        [{"filename": "image_enhance_00001_.png", "params": made_at}])
    return row


def test_a_video_has_no_enhance_corner_at_all():
    video = _image_row(workflow_name="wan22_i2v", output_files=json.dumps(
        [{"filename": "wan22_i2v_00001_.mp4", "subfolder": "video",
          "type": "output"}]))
    assert enhance_state(video, gallery.EnhanceSettings()) is None


def test_an_unenhanced_image_offers_the_first_enhancement():
    assert enhance_state(_image_row(), gallery.EnhanceSettings()) == icons.ENHANCE_OPEN


def test_an_image_holding_these_very_settings_has_nothing_to_offer():
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    assert enhance_state(_enhanced_row(settings), settings) == icons.ENHANCE_HELD


def test_a_setting_moved_turns_that_back_into_an_offer():
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    other = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 3.0})
    assert enhance_state(_enhanced_row(settings), other) == icons.ENHANCE_MORE


def _controls(qtbot):
    host = QWidget()
    host.resize(200, 200)
    qtbot.addWidget(host)
    # pytest-qt keeps only a weak reference to a widget it is given, and Qt deletes a child with its parent.
    return host, CornerButtons(host)


def test_nothing_shows_until_there_is_something_to_act_on(qtbot):
    _host, controls = _controls(qtbot)
    assert all(b.isHidden() for b in controls.buttons())


def test_every_corner_is_up_the_moment_there_is_an_item_under_it(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=icons.ENHANCE_OPEN)

    assert all(not b.isHidden() for b in controls.buttons()), (
        "the corners are up at rest, not revealed on hover: a wall of thumbnails has to say "
        "which of them are favorited without being swept")


def test_an_item_the_enhancer_cannot_take_grows_no_plus(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=None)
    star, trash, plus = controls.buttons()

    assert not star.isHidden()
    assert not trash.isHidden()
    assert plus.isHidden()


def test_a_spent_enhance_corner_is_a_sign_rather_than_a_button(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=icons.ENHANCE_HELD)
    plus = controls.buttons()[2]
    assert not plus.isEnabled()

    controls.set_enhance(icons.ENHANCE_MORE)
    assert plus.isEnabled()


def test_a_queued_enhancement_blinks_the_plus_yellow_slowly(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=icons.ENHANCE_QUEUED)
    plus = controls.buttons()[2]
    resting = plus.icon().cacheKey()

    controls._blink.timeout.emit()
    lit = plus.icon().cacheKey()
    controls._blink.timeout.emit()

    assert controls._blink.isActive()
    assert controls._blink.interval() >= 500, (
        "his ask, 2026-11-19: the plus says an enhancement is queued by blinking yellow slowly")
    assert lit == icons.corner_enhance_icon(icons.ENHANCE_HELD, armed=False).cacheKey() != resting
    assert plus.icon().cacheKey() == resting
    assert not plus.isEnabled(), "a second press would queue the same enhancement twice"
    assert plus.toolTip() == "An enhancement of this image is queued"


def test_the_plus_stops_blinking_once_nothing_is_queued(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=icons.ENHANCE_QUEUED)

    controls.set_enhance(icons.ENHANCE_HELD)

    assert not controls._blink.isActive()


def test_taking_the_item_away_takes_every_corner_with_it(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=True, enhance=icons.ENHANCE_HELD)

    controls.hide_all()

    assert all(b.isHidden() for b in controls.buttons())


def test_each_control_names_the_act_it_carries(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=icons.ENHANCE_OPEN)
    fired = []
    controls.triggered.connect(appending_to(fired))

    for button in controls.buttons():
        button.click()

    assert fired == [STAR, TRASH, ENHANCE]


def test_the_star_says_which_way_it_would_go(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=None)
    star = controls.buttons()[0]
    assert star.toolTip() == "Favorite this item"

    controls.show_for(favorite=True, enhance=None)
    assert star.toolTip() == "Unfavorite this item", (
        "the mark is the state and the button at once: a filled star is the favorite and "
        "pressing it takes the favorite away, so an item cannot carry a sign saying one thing "
        "beside a control doing another")


@pytest.mark.parametrize("kind", [MediaType.IMAGE, MediaType.VIDEO])
def test_the_star_and_the_trash_say_whether_they_act_on_an_image_or_a_video(qtbot, kind):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=None, kind=kind)
    star, trash = controls.buttons()[:2]

    assert (star.toolTip(), trash.toolTip()) == (f"Favorite this {kind}", f"Delete this {kind}")


def test_a_corner_button_under_the_pointer_wears_its_armed_icon(qtbot):
    _host, controls = _controls(qtbot)
    controls.show_for(favorite=False, enhance=None)
    star = controls.buttons()[0]

    def mark():
        return star.icon().pixmap(corner_size(), corner_size()).toImage()

    resting = mark()

    star.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))

    assert mark() != resting

    star.leaveEvent(QEvent(QEvent.Type.Leave))

    assert mark() == resting


def test_in_fun_time_they_are_the_familys_square_which_fun_times_scale_lands_at_the_huds(qtbot):
    square_buttons.draw_in_fun_time(True)
    _host, controls = _controls(qtbot)

    assert {button.width() for button in controls.buttons()} == {BUTTON_SIZE}


def test_taken_into_fun_time_they_grow_and_stay_in_their_corners(qtbot):
    _host, controls = _controls(qtbot)
    area = QRect(20, 30, 120, 100)
    controls.place(area)

    square_buttons.draw_in_fun_time(True)
    controls.draw_at_the_huds_scale_again()

    star, trash, plus = (b.geometry() for b in controls.buttons())
    assert {star.width(), trash.width(), plus.width()} == {BUTTON_SIZE}
    assert all(area.contains(corner) for corner in (star, trash, plus))
    assert (star.right(), trash.bottom()) == (plus.right(), plus.bottom())


def test_they_stand_as_far_in_from_a_tiles_corner_as_its_image_or_video_icon_does(qtbot):
    host, controls = _controls(qtbot)
    area = QRect(0, 0, 120, 100)
    icon = ItemTypeIcon(MediaType.IMAGE, host)

    controls.place(area)

    star, trash, _plus = (b.geometry() for b in controls.buttons())
    assert (area.right() - star.right(), star.top(), trash.left()) == (icon.x(), icon.y(), icon.x())


def test_a_tiles_image_or_video_icon_is_shrunk_as_its_corner_buttons_are(qtbot):
    host = _controls(qtbot)[0]

    standalone = ItemTypeIcon(MediaType.IMAGE, host)
    square_buttons.draw_in_fun_time(True)
    in_fun_time = ItemTypeIcon(MediaType.IMAGE, host)

    assert (standalone.width(), in_fun_time.width()) == (
        round(icons.ITEM_TYPE_ICON_SIZE * BUTTON_SIZE_HUD / BUTTON_SIZE), icons.ITEM_TYPE_ICON_SIZE)


def test_they_land_one_to_a_corner_of_the_rectangle_they_are_given(qtbot):
    _host, controls = _controls(qtbot)
    area = QRect(20, 30, 120, 100)

    controls.place(area)

    star, trash, plus = (b.geometry() for b in controls.buttons())
    for corner in (star, trash, plus):
        assert area.contains(corner), (
            "the host says where the item currently is, because only the host knows: the item "
            "in a thumbnail is a fixed rectangle and the one in a preview moves with every "
            "resize and every change of aspect ratio")
        assert corner.size().width() == corner_size() == BUTTON_SIZE_HUD
    assert star.left() == plus.left() > area.center().x()
    assert star.top() < area.center().y() < plus.top()
    assert trash.left() < area.center().x()
    assert trash.top() == plus.top(), (
        "top-left is left free: the item type icon has always lived there, and a control that "
        "landed on it would move depending on which collection is open")


def test_a_corner_controls_line_art_stands_out_from_its_ground_over_a_white_thumbnail(
        qtbot, sheet_put_back_for_later_tests):
    sheet_put_back_for_later_tests.setStyleSheet(build_stylesheet())
    host = QWidget()
    host.resize(200, 200)
    qtbot.addWidget(host)
    thumbnail = QLabel(host)
    thumbnail.setStyleSheet("background: white")
    thumbnail.setGeometry(host.rect())
    controls = CornerButtons(host)
    controls.show_for(favorite=False, enhance=icons.ENHANCE_OPEN)
    controls.place(host.rect())
    host.show()
    trash = controls.buttons()[1].geometry()

    seen = host.grab().toImage()

    ground = seen.pixelColor(trash.center().x(), trash.top() + 2).lightness()
    brightest = max(seen.pixelColor(x, y).lightness()
                    for x in range(trash.left(), trash.right() + 1)
                    for y in range(trash.top(), trash.bottom() + 1))
    assert brightest - ground > 100, (
        "every corner control sits on a dark ground, so its line art reads over a "
        "thumbnail of any color")
