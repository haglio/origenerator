"""The three controls a generation's picture wears in its own corners."""

import json

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from origenerator import gallery
from origenerator.gui import icons
from origenerator.gui.corner_controls import (
    CORNER_SIZE, CornerControls, ENHANCE, STAR, TRASH, enhance_state,
)


def _image_row(**extra):
    """A finished SDXL image, fabricated whole (never lifted from the library)."""
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
    """That image with one enhancement folded onto it, made at ``settings`` — the
    enhanced file leading, the original still listed behind it, and the level
    recording the params the run actually used."""
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


# --- what the enhance corner has to say ---------------------------------------

def test_a_video_has_no_enhance_corner_at_all():
    # The enhancer refines a still; there is no reading of the corner that would
    # be true of a clip, so it grows no plus rather than a dead one.
    video = _image_row(workflow_name="wan22_i2v", output_files=json.dumps(
        [{"filename": "wan22_i2v_00001_.mp4", "subfolder": "video",
          "type": "output"}]))
    assert enhance_state(video, gallery.EnhanceSettings()) is None


def test_an_unenhanced_image_offers_the_first_enhancement():
    assert enhance_state(_image_row(), gallery.EnhanceSettings()) == icons.ENHANCE_OPEN


def test_an_image_holding_these_very_settings_has_nothing_to_offer():
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    assert enhance_state(_enhanced_row(settings), settings) == icons.ENHANCE_HELD


def test_a_knob_moved_turns_that_back_into_an_offer():
    # The image is not finished with the enhancer, it is finished with THESE
    # settings — so the corner offers again as soon as they describe another one.
    settings = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 2.0})
    other = gallery.EnhanceSettings(auto=False, params={"enhance_scale": 3.0})
    assert enhance_state(_enhanced_row(settings), other) == icons.ENHANCE_MORE


# --- when each control is up --------------------------------------------------

def _controls(qtbot):
    """A bare host and its three controls. The host is handed back so the test
    keeps it alive: nothing else references it, and Qt frees the buttons with it."""
    host = QWidget()
    host.resize(200, 200)
    qtbot.addWidget(host)
    return host, CornerControls(host)


def test_nothing_shows_until_there_is_something_to_act_on(qtbot):
    host, controls = _controls(qtbot)
    controls.set_revealed(True)  # a cursor over an empty pane is still nothing
    assert all(b.isHidden() for b in controls.buttons())


def test_the_offers_wait_for_a_cursor_but_the_reports_do_not(qtbot):
    host, controls = _controls(qtbot)
    controls.show_for(starred=True, enhance=icons.ENHANCE_HELD)
    star, trash, plus = controls.buttons()

    assert not star.isHidden()   # a bookmark has to read across a resting wall
    assert not plus.isHidden()   # so does an enhancement
    assert trash.isHidden()      # a delete is an offer, and offers wait

    controls.set_revealed(True)
    assert not trash.isHidden()


def test_a_spent_enhance_corner_is_a_badge_rather_than_a_button(qtbot):
    host, controls = _controls(qtbot)
    controls.show_for(starred=False, enhance=icons.ENHANCE_HELD)
    plus = controls.buttons()[2]
    assert not plus.isEnabled()

    controls.set_enhance(icons.ENHANCE_MORE)
    assert plus.isEnabled()


def test_taking_the_picture_away_takes_every_corner_with_it(qtbot):
    host, controls = _controls(qtbot)
    controls.show_for(starred=True, enhance=icons.ENHANCE_HELD)
    controls.set_revealed(True)

    controls.hide_all()

    assert all(b.isHidden() for b in controls.buttons())


def test_each_control_names_the_act_it_carries(qtbot):
    host, controls = _controls(qtbot)
    controls.show_for(starred=False, enhance=icons.ENHANCE_OPEN)
    fired = []
    controls.triggered.connect(fired.append)

    for button in controls.buttons():
        button.click()

    assert fired == [STAR, TRASH, ENHANCE]


def test_the_star_says_which_way_it_would_go(qtbot):
    host, controls = _controls(qtbot)
    controls.show_for(starred=False, enhance=None)
    star = controls.buttons()[0]
    assert star.toolTip() == "Star this item"

    controls.set_starred(True)
    assert star.toolTip() == "Unstar this item"


def test_they_land_one_to_a_corner_of_the_rectangle_they_are_given(qtbot):
    host, controls = _controls(qtbot)
    picture = QRect(20, 30, 120, 100)

    controls.place(picture)

    star, trash, plus = (b.geometry() for b in controls.buttons())
    for corner in (star, trash, plus):
        assert picture.contains(corner)
        assert corner.size().width() == CORNER_SIZE
    assert star.left() == trash.left() < picture.center().x()
    assert star.top() < picture.center().y() < trash.top()
    assert plus.top() == trash.top()
    assert plus.left() > picture.center().x()
