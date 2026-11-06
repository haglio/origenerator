from __future__ import annotations

import json

from origenerator.action_labels import Labels
from origenerator.animation_names import (
    Animation,
    animation_of,
    image_button_of,
    labels_for,
    named,
)


def _video(actions, checked=()):
    return {"video_actions": json.dumps(list(actions)), "video_checked": json.dumps(list(checked))}


def test_an_animation_is_named_for_its_action_and_then_each_checkbox_it_carries():
    assert Animation("alpha + beta", ("third box",)).name == "alpha + beta + third box"
    assert Animation("alpha").name == "alpha"


def test_a_name_reads_back_as_its_action_and_its_checkboxes_whatever_plus_its_action_holds():
    assert named("alpha + beta + third box") == Animation("alpha + beta", ("third box",))
    assert named("alpha + beta") == Animation("alpha + beta")


def test_a_name_stands_for_the_actions_its_button_stands_for_and_its_checkboxes():
    assert labels_for("alpha + beta + third box") == Labels(("alpha", "beta"), ("third box",))
    assert labels_for("an action no button has") == Labels()


def test_a_video_is_the_animation_whose_button_stands_for_its_actions_in_any_order():
    assert animation_of(_video(("beta", "alpha"), ("third box",))) == "alpha + beta + third box"
    assert animation_of(_video(("alpha",))) == "alpha"


def test_a_video_whose_actions_no_button_stands_for_is_no_animation():
    assert animation_of(_video(("gamma",))) == ""
    assert animation_of(_video(())) == ""
    assert animation_of({}) == ""


def test_an_image_is_the_button_its_actions_stand_for():
    assert image_button_of({"image_actions": json.dumps(["beta", "alpha"])}) == "state two"
    assert image_button_of({"image_actions": json.dumps(["delta"])}) == ""
    assert image_button_of(None) == ""
