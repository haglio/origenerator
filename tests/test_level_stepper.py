"""Stepping the versions of the picture on screen.

Shift+Left/Right moves within one image's enhancement levels rather than along
the set. Which versions exist, which picture they belong to, and which of them
is showing were three fields on the slideshow, read and written from five of its
methods; they are one small object now, and this is what it promises.
"""

import pytest

from origenerator.gui.level_stepper import LevelStepper

# Two pictures. The first has three versions, newest first, as the gallery hands
# them over: (path, media_type, label). The second has only itself.
_LEVELS = {
    "a.png": [("a-v3.png", "image", "Level 3"),
              ("a-v2.png", "image", "Level 2"),
              ("a.png", "image", "Base")],
    "b.png": [("b.png", "image", "Base")],
}


@pytest.fixture
def armed():
    stepper = LevelStepper()
    stepper.arm(_LEVELS)
    return stepper


def test_a_fresh_stepper_has_nothing_to_step():
    stepper = LevelStepper()

    assert stepper.step(1, base="a.png") is None
    assert stepper.levels(base="a.png") == []
    assert stepper.index == 0


def test_stepping_moves_within_the_one_picture(armed):
    assert armed.step(1, base="a.png") == ("a-v2.png", "image", "Level 2")
    assert armed.step(1, base="a.png") == ("a.png", "image", "Base")
    assert armed.index == 2


def test_the_versions_wrap_round_in_both_directions(armed):
    assert armed.step(-1, base="a.png") == ("a.png", "image", "Base")
    assert armed.index == 2
    assert armed.step(1, base="a.png") == ("a-v3.png", "image", "Level 3")
    assert armed.index == 0


def test_a_picture_with_one_version_does_not_step(armed):
    # And says so by answering nothing, so the caller can leave the set alone
    # rather than stepping it when the shift was the whole point.
    assert armed.step(1, base="b.png") is None
    assert armed.index == 0


def test_a_picture_with_no_versions_at_all_does_not_step(armed):
    assert armed.step(1, base="never-enhanced.png") is None


def test_the_picture_being_stepped_stays_the_key_once_stepping_starts(armed):
    # The file on screen is no longer the one the set lists the image under the
    # moment a level is showing, so the base is remembered rather than re-asked.
    armed.step(1, base="a.png")

    assert armed.step(1, base="a-v2.png") == ("a.png", "image", "Base")


def test_a_new_slide_starts_again_at_the_top_version(armed):
    armed.step(1, base="a.png")

    armed.restart()

    assert armed.index == 0
    assert armed.step(1, base="a.png") == ("a-v2.png", "image", "Level 2")


def test_the_levels_on_offer_are_the_ones_for_the_picture_being_stepped(armed):
    assert len(armed.levels(base="a.png")) == 3
    assert len(armed.levels(base="b.png")) == 1
    assert armed.levels(base="unknown.png") == []

    armed.step(1, base="a.png")
    assert len(armed.levels(base="a-v2.png")) == 3  # still a.png's, being stepped


def test_re_arming_replaces_what_there_is_to_step(armed):
    armed.arm({"c.png": [("c.png", "image", "Base")]})

    assert armed.levels(base="a.png") == []
    assert len(armed.levels(base="c.png")) == 1


def test_the_keys_and_the_lists_are_taken_as_this_object_s_own(armed):
    # The gallery rebuilds its map on every poll, and the paths arrive as Paths
    # as often as strings; neither may reach back in here afterwards.
    from pathlib import Path

    versions = [("d.png", "image", "Base"), ("d-v2.png", "image", "Level 2")]
    stepper = LevelStepper()
    stepper.arm({Path("d.png"): versions})
    versions.append(("d-v3.png", "image", "Level 3"))

    assert len(stepper.levels(base="d.png")) == 2
