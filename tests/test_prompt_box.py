"""Dragging a prompt box taller, and the height it keeps afterwards."""

import pytest
from PyQt6.QtCore import QPoint, Qt

from origenerator.gui.prompt_box import (
    DEFAULT_HEIGHT, MAX_HEIGHT, PROMPT_HEIGHTS, PromptBox,
)


@pytest.fixture(autouse=True)
def _forget_dragged_heights():
    """Start and end each test with no remembered heights.

    They are app-wide by design — one number per param for the whole process —
    so without this one test's drag would set the next one's starting size.
    """
    PROMPT_HEIGHTS.restore({})
    yield
    PROMPT_HEIGHTS.restore({})


def _box(qtbot, key="positive_prompt"):
    box = PromptBox(key)
    qtbot.addWidget(box)
    box.resize(300, box.height())
    box.show()
    qtbot.waitExposed(box)
    return box


def _drag_edge(qtbot, box, dy):
    """Grab the box's bottom edge and pull it ``dy`` pixels down (up, if negative)."""
    grab = QPoint(box.viewport().width() // 2, box.viewport().height() - 1)
    drop = grab + QPoint(0, dy)
    qtbot.mousePress(box.viewport(), Qt.MouseButton.LeftButton, pos=grab)
    qtbot.mouseMove(box.viewport(), drop)
    qtbot.mouseRelease(box.viewport(), Qt.MouseButton.LeftButton, pos=drop)


def test_a_fresh_prompt_box_is_the_familiar_height(qtbot):
    # Nothing dragged yet: the size prompts have always been, so the form looks
    # the same until the user asks for something else.
    assert _box(qtbot).height() == DEFAULT_HEIGHT


def test_dragging_the_bottom_edge_makes_the_box_taller(qtbot):
    box = _box(qtbot)
    _drag_edge(qtbot, box, 80)
    assert box.height() == DEFAULT_HEIGHT + 80


def test_dragging_the_bottom_edge_up_makes_it_shorter(qtbot):
    box = _box(qtbot)
    _drag_edge(qtbot, box, -40)
    assert box.height() == DEFAULT_HEIGHT - 40


def test_a_drag_far_up_stops_at_one_readable_line(qtbot):
    # The handle can't be dragged into nothing: a box you can't read a line of is
    # a box you can no longer find the handle on either.
    box = _box(qtbot)
    _drag_edge(qtbot, box, -500)
    assert box.height() < DEFAULT_HEIGHT           # it did shrink
    assert box.height() >= box.fontMetrics().lineSpacing()
    assert box.viewport().height() >= box.fontMetrics().lineSpacing()


def test_a_runaway_drag_stops_at_the_cap(qtbot):
    box = _box(qtbot)
    _drag_edge(qtbot, box, 9000)
    assert box.height() == MAX_HEIGHT


def test_pressing_in_the_middle_types_rather_than_resizes(qtbot):
    # Only the bottom edge is a handle; the rest of the field is for writing in.
    box = _box(qtbot)
    box.setPlainText("a fox in snow")
    middle = QPoint(box.viewport().width() // 2, box.viewport().height() // 2)
    qtbot.mousePress(box.viewport(), Qt.MouseButton.LeftButton, pos=middle)
    qtbot.mouseMove(box.viewport(), middle + QPoint(0, 60))
    qtbot.mouseRelease(box.viewport(), Qt.MouseButton.LeftButton, pos=middle + QPoint(0, 60))
    assert box.height() == DEFAULT_HEIGHT


def test_the_height_sticks_to_the_param_not_the_widget(qtbot):
    # The form is rebuilt on every workflow switch and every new tab, so a height
    # that lived on the widget would be gone by the next click.
    box = _box(qtbot)
    _drag_edge(qtbot, box, 70)

    assert PromptBox("positive_prompt").height() == DEFAULT_HEIGHT + 70
    # …and only that param's: the short negative prompt isn't dragged open too.
    assert PromptBox("negative_prompt").height() == DEFAULT_HEIGHT


def test_boxes_already_open_follow_the_drag(qtbot):
    # Two tabs showing the same prompt: dragging one and finding the other still
    # small would make "this box is this tall" untrue the moment you switch tabs.
    dragged = _box(qtbot)
    other = _box(qtbot)
    _drag_edge(qtbot, dragged, 50)
    assert other.height() == DEFAULT_HEIGHT + 50


def test_dragged_heights_survive_a_snapshot_and_restore(qtbot):
    box = _box(qtbot)
    _drag_edge(qtbot, box, 90)
    saved = PROMPT_HEIGHTS.snapshot()

    PROMPT_HEIGHTS.restore({})                     # a fresh process, nothing dragged
    assert box.height() == DEFAULT_HEIGHT
    PROMPT_HEIGHTS.restore(saved)                  # the session state, reloaded
    assert box.height() == DEFAULT_HEIGHT + 90
    assert PromptBox("positive_prompt").height() == DEFAULT_HEIGHT + 90


@pytest.mark.parametrize("stored", [None, "300", {"positive_prompt": "tall"},
                                    {"positive_prompt": True}, [100]])
def test_a_corrupt_stored_height_opens_at_the_default(qtbot, stored):
    # ui_state.json is hand-editable and outlives any one version of this app; a
    # value that isn't a height must cost the default, not the launch.
    PROMPT_HEIGHTS.restore(stored)
    assert _box(qtbot).height() == DEFAULT_HEIGHT
